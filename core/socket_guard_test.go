package core

import (
	"context"
	"net"
	"os"
	"slices"
	"sync"
	"syscall"
	"testing"
)

type recordingProtector struct {
	mu     sync.Mutex
	refuse bool
	fds    []int
}

func (r *recordingProtector) protectSocket(fd int) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.refuse {
		return false
	}
	r.fds = append(r.fds, fd)
	return true
}

func (r *recordingProtector) protected(fd int) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Contains(r.fds, fd)
}

func listenGuarded(t *testing.T, g *socketGuard) (net.PacketConn, int) {
	t.Helper()
	lc := net.ListenConfig{Control: func(_, _ string, c syscall.RawConn) error {
		return g.protect(c)
	}}
	pc, err := lc.ListenPacket(context.Background(), "udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = pc.Close() })
	raw, err := pc.(*net.UDPConn).SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	fd := -1
	if err := raw.Control(func(f uintptr) { fd = int(f) }); err != nil {
		t.Fatal(err)
	}
	return pc, fd
}

func TestSocketGuardProtectsSocketsOpenedBeforeActivation(t *testing.T) {
	var g socketGuard
	_, fd := listenGuarded(t, &g)
	p := &recordingProtector{}
	g.activate(p)
	if !p.protected(fd) {
		t.Fatalf("socket %d opened before activation was never protected: %v", fd, p.fds)
	}
}

func TestSocketGuardProtectsSocketsOpenedWhileActive(t *testing.T) {
	var g socketGuard
	p := &recordingProtector{}
	g.activate(p)
	_, fd := listenGuarded(t, &g)
	if !p.protected(fd) {
		t.Fatalf("socket %d was not protected at creation: %v", fd, p.fds)
	}
}

func TestSocketGuardSkipsClosedDeferredSockets(t *testing.T) {
	var g socketGuard
	pc, fd := listenGuarded(t, &g)
	_ = pc.Close()
	p := &recordingProtector{}
	g.activate(p)
	if len(p.fds) != 0 {
		t.Fatalf("closed socket %d reached protect: %v", fd, p.fds)
	}
}

func TestSocketGuardHandsRefusedSocketToNextProtector(t *testing.T) {
	var g socketGuard
	stale := &recordingProtector{refuse: true}
	g.activate(stale)
	_, fd := listenGuarded(t, &g)
	next := &recordingProtector{}
	g.activate(next)
	if !next.protected(fd) {
		t.Fatalf("socket %d refused by a cleared handler was lost: %v", fd, next.fds)
	}
}

func TestSocketGuardDeactivateKeepsNewerProtector(t *testing.T) {
	var g socketGuard
	old, current := &recordingProtector{}, &recordingProtector{}
	g.activate(old)
	g.activate(current)
	g.deactivate(old)
	_, fd := listenGuarded(t, &g)
	if !current.protected(fd) {
		t.Fatalf("stopping the old handler unhooked the current one")
	}
}

func TestSocketGuardPrunesClosedSocketsAtCap(t *testing.T) {
	var g socketGuard
	for range maxDeferredSockets {
		pc, _ := listenGuarded(t, &g)
		_ = pc.Close()
	}
	_, fd := listenGuarded(t, &g)
	if len(g.deferred) != 1 {
		t.Fatalf("deferred = %d sockets, want only the open one", len(g.deferred))
	}
	p := &recordingProtector{}
	g.activate(p)
	if !p.protected(fd) {
		t.Fatalf("open socket %d did not survive pruning", fd)
	}
}

func socketFd(t *testing.T, c syscall.Conn) int {
	t.Helper()
	raw, err := c.SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	fd := -1
	if err := raw.Control(func(f uintptr) { fd = int(f) }); err != nil {
		t.Fatal(err)
	}
	return fd
}

func openReusing(t *testing.T, fd int) {
	t.Helper()
	pc, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = pc.Close() })
	if got := socketFd(t, pc.(*net.UDPConn)); got != fd {
		t.Skipf("fd %d was not reused (got %d), nothing to replay onto", fd, got)
	}
}

func TestRawConnControlRefusesClosedSocket(t *testing.T) {
	pc, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := pc.(*net.UDPConn).SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	_ = pc.Close()
	called := false
	if err := raw.Control(func(uintptr) { called = true }); err == nil || called {
		t.Fatalf("Control on a closed socket: err = %v, f called = %v", err, called)
	}
}

func TestSocketGuardReplayMissesReusedFd(t *testing.T) {
	var g socketGuard
	pc, fd := listenGuarded(t, &g)
	_ = pc.Close()
	openReusing(t, fd)
	p := &recordingProtector{}
	g.activate(p)
	if len(p.fds) != 0 {
		t.Fatalf("replay protected fd %d, now owned by another socket: %v", fd, p.fds)
	}
}

// sing-tun's ping opens its socket with a raw syscall, hands the hook an
// os.File RawConn, then dups the fd into a net.Conn and closes the file.
func TestSocketGuardReplayMissesReusedFdOfClosedFile(t *testing.T) {
	var g socketGuard
	sysfd, err := syscall.Socket(syscall.AF_INET, syscall.SOCK_DGRAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	file := os.NewFile(uintptr(sysfd), "raw")
	raw, err := file.SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	if err := g.protect(raw); err != nil {
		t.Fatal(err)
	}
	dup, err := net.FilePacketConn(file)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = dup.Close() })
	_ = file.Close()
	openReusing(t, sysfd)
	p := &recordingProtector{}
	g.activate(p)
	if len(p.fds) != 0 {
		t.Fatalf("replay protected fd %d, now owned by another socket: %v", sysfd, p.fds)
	}
}

//go:build android

package core

import (
	"context"
	"net"
	"net/netip"
	"slices"
	"sync"
	"testing"

	"github.com/metacubex/mihomo/component/dialer"
)

type recordingCallbacks struct {
	mu  sync.Mutex
	fds []int
}

func (r *recordingCallbacks) Protect(fd int) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.fds = append(r.fds, fd)
	return true
}

func (r *recordingCallbacks) ResolveUid(protocol int, source, target string) int { return -1 }

func (r *recordingCallbacks) ResolvePackage(uid int) string { return "" }

func (r *recordingCallbacks) protected(fd int) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Contains(r.fds, fd)
}

func listenThroughDialer(t *testing.T) int {
	t.Helper()
	installHooks()
	pc, err := dialer.ListenPacket(context.Background(), "udp4", "127.0.0.1:0", netip.AddrPort{})
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
	return fd
}

func TestSocketHookProtectsSocketsOpenedWithoutTunHandler(t *testing.T) {
	fd := listenThroughDialer(t)
	callbacks := &recordingCallbacks{}
	th := &TunHandler{callbacks: callbacks}
	th.initHook()
	t.Cleanup(th.close)
	if !callbacks.protected(fd) {
		t.Fatalf("socket %d opened before the tun started was never protected: %v", fd, callbacks.fds)
	}
}

func TestSocketHookProtectsSocketsOpenedWhileTunStarts(t *testing.T) {
	callbacks := &recordingCallbacks{}
	th := &TunHandler{callbacks: callbacks}
	th.initHook()
	t.Cleanup(th.close)
	fd := listenThroughDialer(t)
	if !callbacks.protected(fd) {
		t.Fatalf("socket %d opened before the listener was set went unprotected: %v", fd, callbacks.fds)
	}
}

package core

import (
	"slices"
	"sync"
	"syscall"
)

type socketProtector interface {
	protectSocket(fd int) bool
}

const maxDeferredSockets = 1024

// Android routes an unprotected socket into whichever VPN is up when it sends,
// so one opened while no tun handler exists loops through the next tun for its
// whole life. Such sockets wait here for the next protector; a new mark drops
// the route a connected socket cached.
type socketGuard struct {
	mu       sync.Mutex
	active   socketProtector
	deferred []syscall.RawConn
}

func (g *socketGuard) current() socketProtector {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.active
}

func (g *socketGuard) activate(p socketProtector) {
	g.mu.Lock()
	g.active = p
	deferred := g.deferred
	g.deferred = nil
	g.mu.Unlock()
	for _, conn := range deferred {
		_ = g.protect(conn)
	}
}

func (g *socketGuard) deactivate(p socketProtector) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.active == p {
		g.active = nil
	}
}

func (g *socketGuard) protect(conn syscall.RawConn) error {
	var refused socketProtector
	for {
		g.mu.Lock()
		p := g.active
		if p == nil || p == refused {
			g.deferLocked(conn)
			g.mu.Unlock()
			return nil
		}
		g.mu.Unlock()
		protected := false
		if err := conn.Control(func(fd uintptr) {
			protected = p.protectSocket(int(fd))
		}); err != nil {
			return err
		}
		if protected {
			return nil
		}
		refused = p
	}
}

func (g *socketGuard) deferLocked(conn syscall.RawConn) {
	if len(g.deferred) >= maxDeferredSockets {
		g.deferred = slices.DeleteFunc(g.deferred, socketClosed)
	}
	if len(g.deferred) >= maxDeferredSockets {
		g.deferred = slices.Delete(g.deferred, 0, 1)
	}
	g.deferred = append(g.deferred, conn)
}

func socketClosed(conn syscall.RawConn) bool {
	return conn.Control(func(uintptr) {}) != nil
}

package logstore

import (
	"os"
	"strings"
	"testing"
	"time"
)

func BenchmarkRetainedRestart(b *testing.B) {
	b.StopTimer()
	dir := os.Getenv("FLCLASH_LOG_BENCH_DIR")
	if dir == "" {
		dir = b.TempDir()
		s, err := OpenRetained(dir, 5*1024*1024, 14)
		if err != nil {
			b.Fatal(err)
		}
		for i := 0; i < 4096; i++ {
			if err := s.Append(Record{Time: time.Now(), Message: strings.Repeat("x", 16*1024)}); err != nil {
				b.Fatal(err)
			}
		}
		if err := s.Close(); err != nil {
			b.Fatal(err)
		}
	}
	started := time.Now()
	s, err := OpenRetained(dir, 5*1024*1024, 14)
	if err != nil {
		b.Fatal(err)
	}
	b.Logf("initial open: %s", time.Since(started))
	started = time.Now()
	for more := true; more; {
		more, err = s.MigrateNext()
		if err != nil {
			b.Fatal(err)
		}
	}
	b.Logf("legacy migration: %s", time.Since(started))
	if err := s.Close(); err != nil {
		b.Fatal(err)
	}
	b.ResetTimer()
	b.StartTimer()
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		s, err := OpenRetained(dir, 5*1024*1024, 14)
		if err != nil {
			b.Fatal(err)
		}
		if err := s.Close(); err != nil {
			b.Fatal(err)
		}
	}
}

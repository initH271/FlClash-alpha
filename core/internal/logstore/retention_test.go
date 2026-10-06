package logstore

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAgeRetentionKeepsMoreThanTwentyRecentSegments(t *testing.T) {
	now := time.Date(2026, 10, 6, 12, 0, 0, 0, time.UTC)
	s, err := openStore(t.TempDir(), 256, 0, 14, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for i := 0; i < 30; i++ {
		if err := s.Append(Record{Time: now, Level: "info", Message: strings.Repeat("x", 150)}); err != nil {
			t.Fatal(err)
		}
	}
	files, err := s.files()
	if err != nil || len(files) != 30 {
		t.Fatalf("recent files=%d err=%v", len(files), err)
	}
}

func TestAgeRetentionFiltersMixedFileByRecordTime(t *testing.T) {
	now := time.Date(2026, 10, 6, 12, 0, 0, 0, time.UTC)
	dir := t.TempDir()
	s, err := openStore(dir, 4096, 0, 30, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	for _, age := range []time.Duration{15 * 24 * time.Hour, 14 * 24 * time.Hour, 13 * 24 * time.Hour, time.Hour} {
		if err := s.Append(Record{Time: now.Add(-age), Level: "info", Message: age.String()}); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(dir, "unrelated.log"), []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.SetRetention(14); err != nil {
		t.Fatal(err)
	}
	if err := s.Flush(); err != nil {
		t.Fatal(err)
	}
	records := readRecords(t, dir)
	if len(records) != 2 {
		t.Fatalf("retained %d records", len(records))
	}
	if err := s.Append(Record{Time: now, Level: "info", Message: "after prune"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "unrelated.log")); err != nil {
		t.Fatal(err)
	}
	if len(readRecords(t, dir)) != 3 {
		t.Fatal("active file did not survive rewrite")
	}
}

func TestAgeRetentionPrunesOnRestartAndExport(t *testing.T) {
	now := time.Date(2026, 10, 6, 12, 0, 0, 0, time.UTC)
	dir := t.TempDir()
	s, err := openStore(dir, 4096, 0, 30, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Append(Record{Time: now.Add(-20 * 24 * time.Hour), Level: "info", Message: "expired"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Append(Record{Time: now, Level: "info", Message: "recent"}); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s, err = openStore(dir, 4096, 0, 14, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if len(readRecords(t, dir)) != 1 {
		t.Fatal("restart retained expired record")
	}
	now = now.Add(15 * 24 * time.Hour)
	if err := s.Export(filepath.Join(t.TempDir(), "history.zip")); err != nil {
		t.Fatal(err)
	}
	if len(readRecords(t, dir)) != 0 {
		t.Fatal("export retained expired record")
	}
}

func TestRetentionChangeValidatesAndExtendsWithoutDroppingRecentRecords(t *testing.T) {
	now := time.Now()
	s, err := openStore(t.TempDir(), 4096, 0, 14, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	for _, days := range []int{0, -1, 36501} {
		if s.SetRetention(days) == nil {
			t.Fatalf("accepted days=%d", days)
		}
	}
	if err := s.Append(Record{Time: now.Add(-10 * 24 * time.Hour), Level: "info", Message: "keep"}); err != nil {
		t.Fatal(err)
	}
	if err := s.SetRetention(30); err != nil {
		t.Fatal(err)
	}
	s.Flush()
	if len(readRecords(t, s.dir)) != 1 {
		t.Fatal("extension deleted recent records")
	}
}

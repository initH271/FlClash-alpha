package logstore

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestMigrationYieldsBetweenSegmentsAndKeepsNewWrites(t *testing.T) {
	now := time.Now().UTC()
	dir := t.TempDir()
	for _, name := range []string{"core-20261001T000000.000000000Z.jsonl", "core-20261002T000000.000000000Z.jsonl"} {
		line, _ := json.Marshal(Record{Time: now.Add(-30 * 24 * time.Hour), Message: "expired"})
		if err := os.WriteFile(filepath.Join(dir, name), append(line, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
	s, err := OpenRetained(dir, 4096, 14)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	more, err := s.MigrateNext()
	if err != nil || !more {
		t.Fatalf("first migration: more=%v err=%v", more, err)
	}
	if got := readRecords(t, dir); len(got) != 1 {
		t.Fatal("migration did not yield after a single segment")
	}
	if err := s.Append(Record{Time: now, Message: "during migration"}); err != nil {
		t.Fatal(err)
	}
	if more, err = s.MigrateNext(); err != nil || more {
		t.Fatalf("last migration: more=%v err=%v", more, err)
	}
	if err := s.Append(Record{Time: now, Message: "after migration"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Flush(); err != nil {
		t.Fatal(err)
	}
	if got := readRecords(t, dir); len(got) != 2 || got[0].Message != "during migration" || got[1].Message != "after migration" {
		t.Fatal("migration lost writes or left the active segment closed")
	}
}

func TestLegacySegmentsAreMigratedAfterOpen(t *testing.T) {
	now := time.Now().UTC()
	dir := t.TempDir()
	path := filepath.Join(dir, "core-20261001T000000.000000000Z.jsonl")
	var data []byte
	for _, age := range []time.Duration{30 * 24 * time.Hour, time.Hour} {
		line, _ := json.Marshal(Record{Time: now.Add(-age), Message: age.String()})
		data = append(data, append(line, '\n')...)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	s, err := OpenRetained(dir, 4096, 14)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if got := readRecords(t, dir); len(got) != 2 {
		t.Fatal("opening legacy history performed synchronous retention")
	}
	if err := s.Prune(); err != nil {
		t.Fatal(err)
	}
	if got := readRecords(t, dir); len(got) != 1 || got[0].Time != now.Add(-time.Hour) {
		t.Fatal("background migration did not filter expired records")
	}
}

func TestRestartIndexKeepsClockRollbackRecords(t *testing.T) {
	now := time.Now().UTC()
	dir := t.TempDir()
	s, err := OpenRetained(dir, 4096, 30)
	if err != nil {
		t.Fatal(err)
	}
	for _, age := range []time.Duration{time.Hour, 20 * 24 * time.Hour, 2 * time.Hour} {
		if err := s.Append(Record{Time: now.Add(-age), Message: age.String()}); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenRetained(dir, 4096, 14)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if got := readRecords(t, dir); len(got) != 2 || got[1].Message != "2h0m0s" {
		t.Fatal("index ignored an expired record between recent records")
	}
}

func TestUncleanAppendInvalidatesTheSavedSpan(t *testing.T) {
	now := time.Now().UTC()
	dir := t.TempDir()
	s, err := OpenRetained(dir, 4096, 14)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Append(Record{Time: now, Message: "recent"}); err != nil {
		t.Fatal(err)
	}
	files, _ := s.files()
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	line, _ := json.Marshal(Record{Time: now.Add(-30 * 24 * time.Hour), Message: "expired"})
	f, err := os.OpenFile(files[0], os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.Write(append(line, '\n'))
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	s, err = OpenRetained(dir, 4096, 14)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if err := s.Prune(); err != nil {
		t.Fatal(err)
	}
	if got := readRecords(t, dir); len(got) != 1 || got[0].Message != "recent" {
		t.Fatal("stale index allowed expired appended data to survive")
	}
}

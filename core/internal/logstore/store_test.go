package logstore

import (
	"archive/zip"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func sample(message string) Record {
	return Record{Time: time.Date(2026, 9, 19, 12, 0, 0, 0, time.UTC), Level: "debug", Message: message}
}

func openTestStore(t *testing.T, dir string, bytes int64, count int) *Store {
	t.Helper()
	s, err := Open(dir, bytes, count)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func readRecords(t *testing.T, dir string) []Record {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var records []Record
	for _, entry := range entries {
		if !segmentName.MatchString(entry.Name()) {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		for _, line := range strings.Split(strings.TrimSuffix(string(data), "\n"), "\n") {
			if line == "" {
				continue
			}
			var record Record
			if err := json.Unmarshal([]byte(line), &record); err != nil {
				t.Fatal(err)
			}
			records = append(records, record)
		}
	}
	return records
}

func TestRetentionRestartAndMultiline(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "unrelated.log"), []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, dir, 512, 3)
	for i := 0; i < 30; i++ {
		if err := s.Append(sample(strings.Repeat("中", 30))); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	files, err := s.files()
	if err != nil || len(files) != 3 {
		t.Fatalf("files=%v, err=%v", files, err)
	}
	for _, path := range files {
		info, _ := os.Stat(path)
		if info.Size() > 512 {
			t.Fatalf("oversized segment: %d", info.Size())
		}
	}
	s = openTestStore(t, dir, 512, 3)
	want := "after restart\nDNS 图片\nsecond line"
	if err := s.Append(sample(want)); err != nil {
		t.Fatal(err)
	}
	if err := s.Flush(); err != nil {
		t.Fatal(err)
	}
	records := readRecords(t, dir)
	if records[len(records)-1].Message != want {
		t.Fatal("restart or multiline payload lost")
	}
	if _, err := os.Stat(filepath.Join(dir, "unrelated.log")); err != nil {
		t.Fatal("pruned unrelated file")
	}
}

func TestRepairsIncompleteTailAndExportsFlushedSnapshot(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "core-20260919T120000.000000000Z.jsonl")
	valid, _ := json.Marshal(sample("before crash"))
	if err := os.WriteFile(path, append(append(valid, '\n'), []byte(`{"time":"partial`)...), 0600); err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, dir, 4096, 3)
	if err := s.Append(sample("after crash")); err != nil {
		t.Fatal(err)
	}
	export := filepath.Join(t.TempDir(), "history.zip")
	if err := s.Export(export); err != nil {
		t.Fatal(err)
	}
	archive, err := zip.OpenReader(export)
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	if len(archive.File) != 2 {
		t.Fatalf("unexpected archive entries: %d", len(archive.File))
	}
	reader, err := archive.File[0].Open()
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(reader)
	_ = reader.Close()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "partial") || !strings.Contains(string(data), "after crash") {
		t.Fatalf("bad snapshot: %s", data)
	}
	if len(readRecords(t, dir)) != 2 {
		t.Fatal("records not recovered")
	}
}

func TestConcurrentExportAndAppend(t *testing.T) {
	dir := t.TempDir()
	s := openTestStore(t, dir, 1024*1024, 3)
	var wg sync.WaitGroup
	for worker := 0; worker < 4; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 100; i++ {
				if err := s.Append(sample("parallel")); err != nil {
					t.Error(err)
					return
				}
			}
		}()
	}
	if err := s.Export(filepath.Join(t.TempDir(), "snapshot.zip")); err != nil {
		t.Fatal(err)
	}
	wg.Wait()
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if len(readRecords(t, dir)) != 400 {
		t.Fatal("concurrent records lost")
	}
	if err := s.Append(sample("closed")); err == nil {
		t.Fatal("accepted write after close")
	}
}

func TestStorageErrorsAndOversizedRecord(t *testing.T) {
	dir := t.TempDir()
	s := openTestStore(t, dir, 256, 2)
	if err := s.Append(sample(strings.Repeat("x", 1000))); err == nil {
		t.Fatal("oversized record accepted")
	}
	if err := s.Export(filepath.Join(dir, "missing", "history.zip")); err == nil {
		t.Fatal("export error hidden")
	}
	if err := s.Append(sample("still usable")); err != nil {
		t.Fatal(err)
	}
	if err := s.Flush(); err != nil {
		t.Fatal(err)
	}
	if len(readRecords(t, dir)) != 1 {
		t.Fatal("failed export damaged store")
	}
}

func TestClockRollbackAndRepeatedExports(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "core-20990101T000000.000000000Z.jsonl")
	data, _ := json.Marshal(sample(strings.Repeat("x", 100)))
	if err := os.WriteFile(path, append(data, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	s := openTestStore(t, dir, 256, 2)
	for i := 0; i < 4; i++ {
		if err := s.Append(sample(strings.Repeat("y", 100))); err != nil {
			t.Fatal(err)
		}
	}
	export := filepath.Join(t.TempDir(), "history.zip")
	for i := 0; i < 2; i++ {
		if err := s.Export(export); err != nil {
			t.Fatal(err)
		}
	}
	files, err := s.files()
	if err != nil || len(files) != 2 {
		t.Fatalf("retention after clock rollback: %v %v", files, err)
	}
	if records := readRecords(t, dir); len(records) != 2 || records[1].Message != strings.Repeat("y", 100) {
		t.Fatal("clock rollback deleted new records")
	}
}

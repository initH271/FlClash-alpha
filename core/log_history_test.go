package main

import (
	"archive/zip"
	"core/internal/logstore"
	"io"
	"path/filepath"
	"strings"
	"testing"
	"time"

	logrus "github.com/sirupsen/logrus"
)

func TestLogHistoryWithoutUILogSubscription(t *testing.T) {
	home := t.TempDir()
	startLogHistory(home)
	t.Cleanup(stopLogHistory)
	handleStopLog()
	logrus.Info("history survives disabled UI subscription")
	path, err := handleExportLogHistory()
	if err != nil {
		t.Fatal(err)
	}
	if path != filepath.Join(home, "log-history-export.zip") {
		t.Fatal(path)
	}
	archive, err := zip.OpenReader(path)
	if err != nil {
		t.Fatal(err)
	}
	var found bool
	for _, f := range archive.File {
		reader, err := f.Open()
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(reader)
		_ = reader.Close()
		if err != nil {
			t.Fatal(err)
		}
		found = found || strings.Contains(string(data), "history survives disabled UI subscription")
	}
	_ = archive.Close()
	if !found {
		t.Fatal("core log was not persisted without UI")
	}
	stopLogHistory()
	startLogHistory(home)
	logrus.Info("after restart")
	if _, err := handleExportLogHistory(); err != nil {
		t.Fatal(err)
	}
}

func TestHistoryQueueOverflowIsRecorded(t *testing.T) {
	stopLogHistory()
	home := t.TempDir()
	store, err := logstore.Open(filepath.Join(home, "log-history"), historySegmentBytes, historySegmentCount)
	if err != nil {
		t.Fatal(err)
	}
	r := &historyRecorder{queue: make(chan historyItem, 1), done: make(chan struct{}), store: store, home: home}
	historyState.Lock()
	historyState.recorder, historyState.initError = r, nil
	historyState.Unlock()
	entry := &logrus.Entry{Time: time.Now(), Level: logrus.InfoLevel, Message: "queued record"}
	_ = (historyHook{}).Fire(entry)
	_ = (historyHook{}).Fire(entry)
	safeGoDetached("history test", r.run)
	t.Cleanup(stopLogHistory)
	path, err := handleExportLogHistory()
	if err != nil {
		t.Fatal(err)
	}
	archive, err := zip.OpenReader(path)
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	var data strings.Builder
	for _, file := range archive.File {
		if !strings.HasSuffix(file.Name, ".jsonl") {
			continue
		}
		reader, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		_, err = io.Copy(&data, reader)
		_ = reader.Close()
		if err != nil {
			t.Fatal(err)
		}
	}
	if !strings.Contains(data.String(), "1 records dropped") || !strings.Contains(data.String(), "queued record") {
		t.Fatalf("missing overflow evidence: %s", data.String())
	}
}

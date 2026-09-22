package main

import (
	"core/internal/logstore"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	logrus "github.com/sirupsen/logrus"
)

const historySegmentBytes = 5 * 1024 * 1024
const historySegmentCount = 20

var historyState struct {
	sync.RWMutex
	once      sync.Once
	recorder  *historyRecorder
	initError error
}

type historyItem struct {
	record logstore.Record
	export chan historyResult
}

type historyResult struct {
	path string
	err  error
}

type historyRecorder struct {
	mu      sync.RWMutex
	closed  bool
	queue   chan historyItem
	done    chan struct{}
	dropped atomic.Uint64
	store   *logstore.Store
	home    string
}

type historyHook struct{}

func (historyHook) Levels() []logrus.Level { return logrus.AllLevels }

func (historyHook) Fire(entry *logrus.Entry) error {
	historyState.RLock()
	r := historyState.recorder
	historyState.RUnlock()
	if r == nil {
		return nil
	}
	message := entry.Message
	if len(message) > 32*1024 {
		message = string([]rune(message[:32*1024])) + " [truncated]"
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	if !r.closed {
		select {
		case r.queue <- historyItem{record: logstore.Record{Time: entry.Time, Level: entry.Level.String(), Message: message}}:
		default:
			r.dropped.Add(1)
		}
	}
	return nil
}

func startLogHistory(home string) {
	stopLogHistory()
	store, err := logstore.Open(filepath.Join(home, "log-history"), historySegmentBytes, historySegmentCount)
	historyState.Lock()
	historyState.initError = err
	if err != nil {
		historyState.Unlock()
		fmt.Fprintf(os.Stderr, "log history unavailable: %v\n", err)
		return
	}
	r := &historyRecorder{queue: make(chan historyItem, 1024), done: make(chan struct{}), store: store, home: home}
	historyState.recorder = r
	historyState.Unlock()
	historyState.once.Do(func() { logrus.AddHook(historyHook{}) })
	safeGoDetached("log history", r.run)
}

func (r *historyRecorder) run() {
	defer close(r.done)
	defer r.store.Close()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	var writeError error
	report := func(err error) {
		if err != nil && writeError == nil {
			fmt.Fprintf(os.Stderr, "log history write failed: %v\n", err)
			writeError = err
		}
	}
	reportDrops := func() {
		if count := r.dropped.Swap(0); count > 0 {
			report(r.store.Append(logstore.Record{Time: time.Now(), Level: "warning", Message: fmt.Sprintf("[LOG HISTORY] %d records dropped because the disk queue was full", count)}))
		}
	}
	for {
		select {
		case item, ok := <-r.queue:
			reportDrops()
			if !ok {
				report(r.store.Flush())
				return
			}
			if item.export != nil {
				path := filepath.Join(r.home, "log-history-export.zip")
				err := errors.Join(writeError, r.store.Export(path))
				item.export <- historyResult{path: path, err: err}
			} else {
				report(r.store.Append(item.record))
			}
		case <-ticker.C:
			reportDrops()
			report(r.store.Flush())
		}
	}
}

func stopLogHistory() {
	historyState.Lock()
	r := historyState.recorder
	historyState.recorder = nil
	historyState.Unlock()
	if r != nil {
		r.mu.Lock()
		r.closed = true
		close(r.queue)
		r.mu.Unlock()
		<-r.done
	}
}

func handleExportLogHistory() (string, error) {
	historyState.RLock()
	r, err := historyState.recorder, historyState.initError
	historyState.RUnlock()
	if err != nil {
		return "", err
	}
	if r == nil {
		return "", errors.New("start the core before exporting log history")
	}
	result := make(chan historyResult, 1)
	timer := time.NewTimer(time.Minute)
	defer timer.Stop()
	r.mu.RLock()
	if r.closed {
		r.mu.RUnlock()
		return "", errors.New("log history is closing")
	}
	select {
	case r.queue <- historyItem{export: result}:
		r.mu.RUnlock()
	case <-timer.C:
		r.mu.RUnlock()
		return "", errors.New("log history export queue timed out")
	}
	select {
	case value := <-result:
		if value.err == nil {
			initOwnership(r.home)
		}
		return value.path, value.err
	case <-r.done:
		return "", errors.New("log history stopped during export")
	case <-timer.C:
		return "", errors.New("log history export timed out")
	}
}

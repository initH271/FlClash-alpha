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
const defaultHistoryRetentionDays = 14

var historyState struct {
	sync.RWMutex
	once      sync.Once
	recorder  *historyRecorder
	initError error
}

type historyItem struct {
	record    logstore.Record
	export    chan historyResult
	retention *historyRetentionChange
}

type historyRetentionChange struct {
	days   int
	result chan error
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
	startLogHistoryWithRetention(home, defaultHistoryRetentionDays)
}

func startLogHistoryWithRetention(home string, days int) {
	stopLogHistory()
	if days == 0 {
		days = defaultHistoryRetentionDays
	}
	store, err := logstore.OpenRetained(filepath.Join(home, "log-history"), historySegmentBytes, days)
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
	cleanup := time.NewTicker(time.Minute)
	defer cleanup.Stop()
	migration := time.NewTicker(100 * time.Millisecond)
	defer migration.Stop()
	migrate := migration.C
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
			if item.retention != nil {
				item.retention.result <- r.store.SetRetention(item.retention.days)
			} else if item.export != nil {
				path := filepath.Join(r.home, "log-history-export.zip")
				err := errors.Join(writeError, r.store.Export(path))
				item.export <- historyResult{path: path, err: err}
			} else {
				report(r.store.Append(item.record))
			}
		case <-ticker.C:
			reportDrops()
			report(r.store.Flush())
		case <-cleanup.C:
			if migrate == nil {
				report(r.store.Prune())
			}
		case <-migrate:
			more, err := r.store.MigrateNext()
			report(err)
			if !more || err != nil {
				migration.Stop()
				migrate = nil
			}
		}
	}
}

func handleSetLogHistoryRetention(days int) error {
	if days < 1 || days > 36500 {
		return errors.New("log retention must be between 1 and 36500 days")
	}
	historyState.RLock()
	r := historyState.recorder
	historyState.RUnlock()
	if r == nil {
		return errors.New("log history is not initialized")
	}
	result := make(chan error, 1)
	timer := time.NewTimer(time.Minute)
	defer timer.Stop()
	r.mu.RLock()
	if r.closed {
		r.mu.RUnlock()
		return errors.New("log history is closing")
	}
	select {
	case r.queue <- historyItem{retention: &historyRetentionChange{days: days, result: result}}:
		r.mu.RUnlock()
	case <-timer.C:
		r.mu.RUnlock()
		return errors.New("log retention update queue timed out")
	}
	select {
	case err := <-result:
		return err
	case <-r.done:
		return errors.New("log history stopped during retention update")
	case <-timer.C:
		return errors.New("log retention update timed out")
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
	timer := time.NewTimer(5 * time.Minute)
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

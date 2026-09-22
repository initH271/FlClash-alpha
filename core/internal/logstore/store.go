package logstore

import (
	"archive/zip"
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

var segmentName = regexp.MustCompile(`^core-\d{8}T\d{6}\.\d{9}Z\.jsonl$`)

type Record struct {
	Time    time.Time `json:"time"`
	Level   string    `json:"level"`
	Message string    `json:"message"`
}

type Store struct {
	mu        sync.Mutex
	dir       string
	maxBytes  int64
	maxFiles  int
	file      *os.File
	buffer    *bufio.Writer
	size      int64
	closed    bool
	lastStamp time.Time
}

func Open(dir string, maxBytes int64, maxFiles int) (*Store, error) {
	if maxBytes < 256 || maxFiles < 1 {
		return nil, errors.New("invalid log retention limits")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	s := &Store{dir: dir, maxBytes: maxBytes, maxFiles: maxFiles}
	files, err := s.files()
	if err != nil {
		return nil, err
	}
	if len(files) > 0 {
		path := files[len(files)-1]
		s.lastStamp, _ = time.Parse("20060102T150405.000000000Z", strings.TrimSuffix(strings.TrimPrefix(filepath.Base(path), "core-"), ".jsonl"))
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		end := len(data)
		for end > 0 && data[end-1] != '\n' {
			end--
		}
		if end != len(data) {
			if err := os.Truncate(path, int64(end)); err != nil {
				return nil, err
			}
		}
		if err := s.openFile(path); err != nil {
			return nil, err
		}
	}
	if err := s.prune(); err != nil {
		_ = s.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) files() ([]string, error) {
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, entry := range entries {
		if entry.Type().IsRegular() && segmentName.MatchString(entry.Name()) {
			files = append(files, filepath.Join(s.dir, entry.Name()))
		}
	}
	sort.Strings(files)
	return files, nil
}

func (s *Store) prune() error {
	files, err := s.files()
	if err != nil {
		return err
	}
	for len(files) > s.maxFiles {
		if err := os.Remove(files[0]); err != nil {
			return err
		}
		files = files[1:]
	}
	return nil
}

func (s *Store) openFile(path string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return err
	}
	s.file, s.buffer, s.size = f, bufio.NewWriterSize(f, 64*1024), info.Size()
	return nil
}

func (s *Store) closeFile() error {
	if s.file == nil {
		return nil
	}
	err := errors.Join(s.buffer.Flush(), s.file.Close())
	s.file, s.buffer = nil, nil
	return err
}

func (s *Store) Append(record Record) error {
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if int64(len(data)) > s.maxBytes {
		return errors.New("log record exceeds segment size")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return os.ErrClosed
	}
	if s.file == nil || s.size+int64(len(data)) > s.maxBytes {
		if err := s.closeFile(); err != nil {
			return err
		}
		stamp := time.Now().UTC()
		if !stamp.After(s.lastStamp) {
			stamp = s.lastStamp.Add(time.Nanosecond)
		}
		s.lastStamp = stamp
		path := filepath.Join(s.dir, "core-"+stamp.Format("20060102T150405.000000000Z")+".jsonl")
		if err := s.openFile(path); err != nil {
			return err
		}
		if err := s.prune(); err != nil {
			return err
		}
	}
	n, err := s.buffer.Write(data)
	s.size += int64(n)
	return err
}

func (s *Store) Flush() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.buffer == nil {
		return nil
	}
	return s.buffer.Flush()
}

func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.closed = true
	return s.closeFile()
}

func (s *Store) Export(path string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.buffer != nil {
		if err := s.buffer.Flush(); err != nil {
			return err
		}
	}
	files, err := s.files()
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".log-history-export-*.zip")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	w := zip.NewWriter(f)
	for _, name := range files {
		if err = addFile(w, name); err != nil {
			break
		}
	}
	if err == nil {
		err = writeCoverage(w, files, s.maxBytes)
	}
	if err == nil {
		var readme io.Writer
		readme, err = w.Create("README.txt")
		if err == nil {
			_, err = fmt.Fprintf(readme, "FlClash core log history\nJSON Lines; timestamps include timezone. Files sort oldest to newest.\nRetention: %d files, %d bytes each. Older segments are deleted automatically.\ncoverage.txt lists the first and last record time of each retained file.\nCore logs persist independently of the UI. Flutter [APP] logs remain in the original log export.\nBuffered writes flush every second; abrupt process termination may lose the last buffered records.\n", s.maxFiles, s.maxBytes)
		}
	}
	err = errors.Join(err, w.Close(), f.Close())
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	return err
}

func writeCoverage(w *zip.Writer, files []string, maxLine int64) error {
	out, err := w.Create("coverage.txt")
	if err != nil {
		return err
	}
	if _, err = fmt.Fprint(out, "Core log coverage\nfile first-record last-record\n"); err != nil {
		return err
	}
	for _, path := range files {
		first, last, ok, err := segmentSpan(path, maxLine)
		if err != nil {
			return err
		}
		name := filepath.Base(path)
		if !ok {
			_, err = fmt.Fprintf(out, "%s no records\n", name)
		} else {
			_, err = fmt.Fprintf(out, "%s %s %s\n", name, first.UTC().Format(time.RFC3339Nano), last.UTC().Format(time.RFC3339Nano))
		}
		if err != nil {
			return err
		}
	}
	return nil
}

func segmentSpan(path string, maxLine int64) (time.Time, time.Time, bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return time.Time{}, time.Time{}, false, err
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), int(maxLine)+1024)
	var firstLine, lastLine string
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		if firstLine == "" {
			firstLine = line
		}
		lastLine = line
	}
	if err = scanner.Err(); err != nil {
		return time.Time{}, time.Time{}, false, err
	}
	if firstLine == "" {
		return time.Time{}, time.Time{}, false, nil
	}
	var first, last Record
	if err = json.Unmarshal([]byte(firstLine), &first); err != nil {
		return time.Time{}, time.Time{}, false, err
	}
	if err = json.Unmarshal([]byte(lastLine), &last); err != nil {
		return time.Time{}, time.Time{}, false, err
	}
	return first.Time, last.Time, true, nil
}

func addFile(w *zip.Writer, path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	entry, err := w.Create(filepath.Base(path))
	if err != nil {
		return err
	}
	_, err = io.Copy(entry, f)
	return err
}

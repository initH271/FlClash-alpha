package logstore

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"
)

type segmentIndex struct {
	Earliest time.Time `json:"earliest"`
	Latest   time.Time `json:"latest"`
	Size     int64     `json:"size"`
	Modified int64     `json:"modified"`
}

func loadSpan(path string) (recordSpan, bool) {
	f, err := os.Open(path + ".span.json")
	if err != nil {
		return recordSpan{}, false
	}
	defer f.Close()
	var index segmentIndex
	if json.NewDecoder(io.LimitReader(f, 1024)).Decode(&index) != nil || index.Earliest.IsZero() || index.Latest.Before(index.Earliest) {
		return recordSpan{}, false
	}
	info, err := os.Stat(path)
	if err != nil || info.Size() != index.Size || info.ModTime().UnixNano() != index.Modified {
		return recordSpan{}, false
	}
	return recordSpan{earliest: index.Earliest, latest: index.Latest}, true
}

func (s *Store) saveSpan(path string) error {
	span, known := s.spans[path]
	if !known || s.retentionDays == 0 {
		return nil
	}
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	index := segmentIndex{
		Earliest: span.earliest,
		Latest:   span.latest,
		Size:     info.Size(),
		Modified: info.ModTime().UnixNano(),
	}
	if s.indexedPath == path && s.indexed == index {
		return nil
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".log-span-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	err = json.NewEncoder(f).Encode(index)
	err = errors.Join(err, f.Close())
	if err == nil {
		err = os.Rename(f.Name(), path+".span.json")
	}
	if err == nil {
		s.indexedPath, s.indexed = path, index
	}
	return err
}

func removeSegment(path string) error {
	if err := os.Remove(path); err != nil {
		return err
	}
	if err := os.Remove(path + ".span.json"); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

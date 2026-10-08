package main

import "testing"

func TestListenerRejectsUninitializedAndUnconfiguredCore(t *testing.T) {
	configMu.Lock()
	oldConfig, oldInit, oldRunning := currentConfig, isInit.Load(), isRunning.Load()
	currentConfig = nil
	isInit.Store(false)
	isRunning.Store(false)
	configMu.Unlock()
	t.Cleanup(func() {
		configMu.Lock()
		currentConfig = oldConfig
		isInit.Store(oldInit)
		isRunning.Store(oldRunning)
		configMu.Unlock()
	})
	for _, initialized := range []bool{false, true} {
		isInit.Store(initialized)
		if handleStartListener() || isRunning.Load() {
			t.Fatal("core started without an applied configuration")
		}
	}
}

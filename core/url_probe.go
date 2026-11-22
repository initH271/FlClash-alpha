package core

import (
	"context"
	"net/http"
)

type URLProbeParams struct {
	Url       string `json:"url"`
	ProxyName string `json:"proxy-name"`
	Timeout   int64  `json:"timeout"`
}

type URLProbeResult struct {
	StatusCode   int        `json:"status-code"`
	Delay        int64      `json:"delay"`
	Chains       []string   `json:"chains"`
	Error        string     `json:"error,omitempty"`
	Message      string     `json:"message,omitempty"`
	CoreEpoch    uint64     `json:"core-epoch"`
	RouteVersion uint64     `json:"route-version"`
	Hits         []RouteHit `json:"hits"`
}

// A request that never got a probe slot answers as a timeout, so every call
// carries the route it was made under.
func handleProbeURL(params *URLProbeParams) *URLProbeResult {
	epoch, version := routeStamp()
	hits := &hitRecorder{}
	result := runProbe(context.Background(), probeRequest{
		method:    http.MethodGet,
		url:       params.Url,
		proxyName: params.ProxyName,
		timeout:   timeoutFromMillis(params.Timeout, defaultProbeTimeout),
		recorder:  hits,
	})
	if result == nil {
		return &URLProbeResult{
			Chains:       []string{},
			Error:        probeErrorTimeout,
			CoreEpoch:    epoch,
			RouteVersion: version,
			Hits:         hits.list(),
		}
	}
	return &URLProbeResult{
		StatusCode:   result.StatusCode,
		Delay:        result.Delay,
		Chains:       result.Chains,
		Error:        result.Error,
		Message:      result.Message,
		CoreEpoch:    result.CoreEpoch,
		RouteVersion: result.RouteVersion,
		Hits:         hits.list(),
	}
}

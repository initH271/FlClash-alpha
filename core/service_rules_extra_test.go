package core

import (
	"net/http"
	"testing"
)

func TestBinanceStatus(t *testing.T) {
	cases := []struct {
		code int
		body string
		want string
	}{
		{http.StatusOK, "{}", serviceAvailable},
		{http.StatusUnavailableForLegalReasons, `{"code":0,"msg":"Service unavailable from a restricted location according to 'b. Eligibility'"}`, serviceUnsupportedRegion},
		{http.StatusForbidden, "", serviceRestricted},
		{http.StatusBadGateway, "", serviceUnavailable},
	}
	for _, c := range cases {
		got := binanceStatus(&ProbeResult{StatusCode: c.code, Body: c.body})
		if got != c.want {
			t.Errorf("binanceStatus(%d, %q) = %q, want %q", c.code, c.body, got, c.want)
		}
	}
}

func TestBybitStatus(t *testing.T) {
	cases := []struct {
		code int
		body string
		want string
	}{
		{http.StatusOK, `{"retCode":0}`, serviceAvailable},
		{http.StatusForbidden, "The Amazon CloudFront distribution is configured to block access from your country.", serviceUnsupportedRegion},
		{http.StatusForbidden, "Request blocked.", serviceRestricted},
		{http.StatusServiceUnavailable, "", serviceUnavailable},
	}
	for _, c := range cases {
		got := bybitStatus(&ProbeResult{StatusCode: c.code, Body: c.body})
		if got != c.want {
			t.Errorf("bybitStatus(%d, %q) = %q, want %q", c.code, c.body, got, c.want)
		}
	}
}

func TestServiceCheckersHaveUniqueNames(t *testing.T) {
	seen := map[string]bool{}
	for _, checker := range serviceCheckers {
		if seen[checker.name] {
			t.Errorf("checker %q is registered twice", checker.name)
		}
		seen[checker.name] = true
	}
}

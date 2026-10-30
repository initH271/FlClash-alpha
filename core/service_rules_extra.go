package core

import "github.com/metacubex/http"

func checkBinance(env serviceEnv) ServiceCheckItem {
	result := env.get("https://api.binance.com/api/v3/ping", serviceSmallMaxBody)
	item := itemFrom(result)
	if !answered(item, result) {
		return item
	}
	item.Status = binanceStatus(result)
	return item
}

// Binance answers 451 "restricted location" where its terms exclude you.
func binanceStatus(result *ProbeResult) string {
	if result.StatusCode == http.StatusUnavailableForLegalReasons ||
		bodyContains(result, "restricted location") {
		return serviceUnsupportedRegion
	}
	return statusFromCode(result.StatusCode)
}

func checkBybit(env serviceEnv) ServiceCheckItem {
	result := env.get("https://api.bybit.com/v5/market/time", serviceSmallMaxBody)
	item := itemFrom(result)
	if !answered(item, result) {
		return item
	}
	item.Status = bybitStatus(result)
	return item
}

// Only CloudFront's country block names the country; other 403s are WAF ones.
func bybitStatus(result *ProbeResult) string {
	if result.StatusCode == http.StatusForbidden &&
		bodyContains(result, "block access from your country") {
		return serviceUnsupportedRegion
	}
	return statusFromCode(result.StatusCode)
}

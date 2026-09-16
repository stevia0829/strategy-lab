package engine

import (
	"encoding/json"
	"math"
	"os"
	"testing"
)

func TestIndicatorsAndWarmup(t *testing.T) {
	bars := make([]Bar, 45)
	for i := range bars {
		v := float64(10 + i)
		bars[i] = Bar{Open: v, High: v + 1, Low: v - 1, Close: v, Volume: 100}
	}
	for _, kind := range []string{"sma", "ema"} {
		v := Calculate(bars, Indicator{Kind: kind, Period: 3})
		if !math.IsNaN(v[1]) || v[2] != 11 || v[3] != 12 {
			t.Fatalf("%s: %v", kind, v[:4])
		}
	}
	rsi := Calculate(bars, Indicator{Kind: "rsi", Period: 14})
	if !math.IsNaN(rsi[13]) || rsi[14] != 100 {
		t.Fatal("RSI warmup")
	}
	macd := Calculate(bars, Indicator{Kind: "macd"})
	if !math.IsNaN(macd[32]) || math.Abs(macd[33]) > 1e-12 {
		t.Fatal("MACD warmup")
	}
	for _, kind := range []string{"sma", "ema", "rsi", "macd", "roc", "momentum_score", "atr", "highest", "lowest"} {
		full := Calculate(bars, Indicator{Kind: kind, Period: 7})
		prefix := Calculate(bars[:30], Indicator{Kind: kind, Period: 7})
		for i, v := range prefix {
			if math.IsNaN(v) && math.IsNaN(full[i]) {
				continue
			}
			if v != full[i] {
				t.Fatalf("future leak %s %d", kind, i)
			}
		}
	}
}
func TestMissingNotAndCross(t *testing.T) {
	var rule any
	json.Unmarshal([]byte(`{"not":{"left":"x","op":"gt","right":0}}`), &rule)
	series := map[string][]float64{"x": {math.NaN(), 0, 1}}
	if Evaluate(rule, series, 0) != -1 {
		t.Fatal("NOT converted warmup into a buy")
	}
	json.Unmarshal([]byte(`{"left":"x","op":"cross_above","right":0}`), &rule)
	if Evaluate(rule, series, 2) != 1 {
		t.Fatal("cross missing")
	}
}
func TestNextOpenAndUnrealizedDrawdown(t *testing.T) {
	raw, err := os.ReadFile("../examples/buy_hold.json")
	if err != nil {
		t.Fatal(err)
	}
	s, err := ParseStrategy(raw)
	if err != nil {
		t.Fatal(err)
	}
	s.Universe = []string{"A"}
	s.Benchmark = "A"
	s.Start = ""
	s.End = ""
	s.Execution = Execution{InitialCash: 1000, LotSize: 1, MaxExposure: 1}
	data := "date,symbol,open,high,low,close,volume\n2024-01-01,A,10,10,10,10,1000\n2024-01-02,A,20,20,20,20,1000\n2024-01-03,A,20,20,10,10,1000\n2024-01-04,A,30,30,30,30,1000\n"
	r, err := Run(s, data)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Fills) != 1 || r.Fills[0].Price != 20 || r.Fills[0].SignalDate != "2024-01-01" {
		t.Fatal(r.Fills)
	}
	if r.Metrics["max_drawdown"] != .5 || r.Metrics["max_drawdown_recovery_days"] != 2 {
		t.Fatal(r.Metrics)
	}
	if len(r.Closed) != 0 {
		t.Fatal("forced last-day liquidation")
	}
}
func TestCSVRejectsInvalidData(t *testing.T) {
	for _, text := range []string{"date,symbol,open,high,low,close,volume\n2024-01-01,A,10,9,10,10,10\n", "date,symbol,open,high,low,close,volume\n2024-01-01,A,NaN,10,10,10,10\n"} {
		if _, err := ReadCSV(text); err == nil {
			t.Fatal("accepted malformed CSV")
		}
	}
}

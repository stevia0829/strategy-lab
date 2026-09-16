package engine

import (
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Bar struct {
	Date, Symbol                                       string
	Open, High, Low, Close, Volume, LimitUp, LimitDown float64
}

func (b Bar) Field(f string) float64 {
	switch f {
	case "open":
		return b.Open
	case "high":
		return b.High
	case "low":
		return b.Low
	case "volume":
		return b.Volume
	}
	return b.Close
}
func ReadCSV(text string) (map[string]map[string]Bar, error) {
	r := csv.NewReader(strings.NewReader(strings.TrimPrefix(text, "\ufeff")))
	header, err := r.Read()
	if err != nil {
		return nil, err
	}
	idx := map[string]int{}
	for i, k := range header {
		if _, ok := idx[k]; ok {
			return nil, fmt.Errorf("duplicate CSV header")
		}
		if !contains([]string{"date", "symbol", "open", "high", "low", "close", "volume", "limit_up", "limit_down"}, k) {
			return nil, fmt.Errorf("unknown CSV header")
		}
		idx[k] = i
	}
	for _, k := range []string{"date", "symbol", "open", "high", "low", "close", "volume"} {
		if _, ok := idx[k]; !ok {
			return nil, fmt.Errorf("missing CSV header %s", k)
		}
	}
	data := map[string]map[string]Bar{}
	count := 0
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		count++
		if count > 100000 {
			return nil, fmt.Errorf("CSV exceeds 100000 rows")
		}
		d, c := row[idx["date"]], row[idx["symbol"]]
		t, err := time.Parse("2006-01-02", d)
		if err != nil || t.Format("2006-01-02") != d || c == "" {
			return nil, fmt.Errorf("invalid date/symbol")
		}
		nums := map[string]float64{}
		for _, k := range []string{"open", "high", "low", "close", "volume", "limit_up", "limit_down"} {
			j, ok := idx[k]
			if !ok || row[j] == "" {
				nums[k] = 0
				continue
			}
			v, err := strconv.ParseFloat(row[j], 64)
			if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || v < 0 {
				return nil, fmt.Errorf("invalid CSV number")
			}
			nums[k] = v
		}
		b := Bar{d, c, nums["open"], nums["high"], nums["low"], nums["close"], nums["volume"], nums["limit_up"], nums["limit_down"]}
		if b.Open <= 0 || b.High <= 0 || b.Low <= 0 || b.Close <= 0 || b.Low > math.Min(b.Open, b.Close) || b.High < math.Max(b.Open, b.Close) || b.High < b.Low {
			return nil, fmt.Errorf("invalid OHLC")
		}
		if data[c] == nil {
			data[c] = map[string]Bar{}
		}
		if _, ok := data[c][d]; ok {
			return nil, fmt.Errorf("duplicate symbol/date")
		}
		data[c][d] = b
	}
	if count == 0 {
		return nil, fmt.Errorf("empty CSV")
	}
	return data, nil
}
func sortedKeys[T any](m map[string]T) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Package engine implements the independent Go daily-bar replay engine.
package engine

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"strings"
	"time"
)

const Version = "0.1.0"

var fields = []string{"open", "high", "low", "close", "volume"}

type Indicator struct {
	Kind   string `json:"kind"`
	Field  string `json:"field,omitempty"`
	Period int    `json:"period,omitempty"`
	Fast   int    `json:"fast,omitempty"`
	Slow   int    `json:"slow,omitempty"`
	Signal int    `json:"signal,omitempty"`
	Output string `json:"output,omitempty"`
}
type Selection struct {
	MaxPositions int    `json:"max_positions"`
	RankBy       string `json:"rank_by"`
	Descending   bool   `json:"descending"`
	Mode         string `json:"mode"`
}
type Execution struct {
	InitialCash    float64 `json:"initial_cash"`
	CommissionRate float64 `json:"commission_rate"`
	MinCommission  float64 `json:"min_commission"`
	Slippage       float64 `json:"slippage"`
	LotSize        int     `json:"lot_size"`
	MaxExposure    float64 `json:"max_exposure"`
}
type Strategy struct {
	Version    int                  `json:"version"`
	Name       string               `json:"name"`
	Universe   []string             `json:"universe"`
	Benchmark  string               `json:"benchmark"`
	Start      string               `json:"start,omitempty"`
	End        string               `json:"end,omitempty"`
	Indicators map[string]Indicator `json:"indicators"`
	Entry      any                  `json:"entry"`
	Exit       any                  `json:"exit"`
	Selection  Selection            `json:"selection"`
	Execution  Execution            `json:"execution"`
}

func required(raw []byte, names []string) error {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(raw, &obj); err != nil {
		return err
	}
	for _, k := range names {
		if v, ok := obj[k]; !ok || string(v) == "null" {
			return fmt.Errorf("missing field %s", k)
		}
	}
	return nil
}
func ParseStrategy(raw []byte) (Strategy, error) {
	var s Strategy
	if err := required(raw, []string{"version", "name", "universe", "benchmark", "indicators", "entry", "exit", "selection", "execution"}); err != nil {
		return s, err
	}
	var obj map[string]json.RawMessage
	_ = json.Unmarshal(raw, &obj)
	if err := required(obj["selection"], []string{"max_positions", "rank_by", "descending", "mode"}); err != nil {
		return s, err
	}
	if err := required(obj["execution"], []string{"initial_cash", "commission_rate", "min_commission", "slippage", "lot_size", "max_exposure"}); err != nil {
		return s, err
	}

	for _, key := range []string{"start", "end"} {
		if value, ok := obj[key]; ok {
			var text any
			_ = json.Unmarshal(value, &text)
			if _, ok := text.(string); !ok {
				return s, fmt.Errorf("date must be a string")
			}
		}
	}
	var specs map[string]map[string]any
	if err := json.Unmarshal(obj["indicators"], &specs); err != nil {
		return s, err
	}
	for _, spec := range specs {
		if value, exists := spec["field"]; exists {
			text, ok := value.(string)
			if !ok || !contains(fields, text) {
				return s, fmt.Errorf("invalid indicator field")
			}
		}
		if spec["kind"] == "macd" {
			for _, key := range []string{"fast", "slow", "signal"} {
				if value, exists := spec[key]; exists {
					n, ok := value.(float64)
					if !ok || n < 2 || n > 500 || math.Trunc(n) != n {
						return s, fmt.Errorf("invalid MACD period")
					}
				}
			}
			if value, exists := spec["output"]; exists {
				text, ok := value.(string)
				if !ok || !contains([]string{"line", "signal", "hist"}, text) {
					return s, fmt.Errorf("invalid MACD output")
				}
			}
		}
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return s, err
	}
	var tail any
	if err := dec.Decode(&tail); err != io.EOF {
		return s, fmt.Errorf("trailing JSON content")
	}
	if err := s.Validate(); err != nil {
		return s, err
	}
	return s, nil
}
func (s Strategy) Validate() error {
	fail := func() error { return fmt.Errorf("invalid strategy configuration") }
	if s.Version != 1 || strings.TrimSpace(s.Name) == "" || s.Benchmark == "" || len(s.Universe) < 1 || len(s.Universe) > 100 || len(s.Indicators) > 40 {
		return fail()
	}
	seen := map[string]bool{}
	for _, c := range s.Universe {
		if c == "" || seen[c] {
			return fail()
		}
		seen[c] = true
	}
	for _, d := range []string{s.Start, s.End} {
		if d != "" {
			v, err := time.Parse("2006-01-02", d)
			if err != nil || v.Format("2006-01-02") != d {
				return fail()
			}
		}
	}
	if s.Start != "" && s.End != "" && s.Start > s.End {
		return fail()
	}
	refs := map[string]bool{}
	for _, f := range fields {
		refs[f] = true
	}
	for name, spec := range s.Indicators {
		if name == "" || refs[name] {
			return fail()
		}
		refs[name] = true
		if spec.Field != "" && !contains(fields, spec.Field) {
			return fail()
		}
		if !contains([]string{"sma", "ema", "rsi", "macd", "roc", "momentum_score", "atr", "highest", "lowest"}, spec.Kind) {
			return fail()
		}
		if spec.Kind == "macd" {
			f, sl, sg := macdParams(spec)
			if f < 2 || sl < 2 || sg < 2 || f > 500 || sl > 500 || sg > 500 || f >= sl || !contains([]string{"", "line", "signal", "hist"}, spec.Output) {
				return fail()
			}
		} else if spec.Period < 2 || spec.Period > 500 {
			return fail()
		}
	}
	if err := validateRule(s.Entry, refs, 0); err != nil {
		return err
	}
	if err := validateRule(s.Exit, refs, 0); err != nil {
		return err
	}
	sel, e := s.Selection, s.Execution
	if sel.MaxPositions < 1 || sel.MaxPositions > len(s.Universe) || !refs[sel.RankBy] || !contains([]string{"hold", "rotate"}, sel.Mode) {
		return fail()
	}
	for _, v := range []float64{e.InitialCash, e.CommissionRate, e.MinCommission, e.Slippage, e.MaxExposure} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return fail()
		}
	}
	if e.InitialCash <= 0 || e.InitialCash > 1e12 || e.CommissionRate < 0 || e.CommissionRate > .05 || e.MinCommission < 0 || e.Slippage < 0 || e.Slippage > .1 || e.MaxExposure < 0 || e.MaxExposure > 1 || e.LotSize < 1 || e.LotSize > 1000000 {
		return fail()
	}
	return nil
}
func contains(a []string, k string) bool {
	for _, v := range a {
		if v == k {
			return true
		}
	}
	return false
}
func macdParams(s Indicator) (int, int, int) {
	f, sl, sg := s.Fast, s.Slow, s.Signal
	if f == 0 {
		f = 12
	}
	if sl == 0 {
		sl = 26
	}
	if sg == 0 {
		sg = 9
	}
	return f, sl, sg
}
func validateRule(node any, refs map[string]bool, depth int) error {
	fail := func() error { return fmt.Errorf("invalid rule or unknown indicator") }
	if depth > 8 {
		return fail()
	}
	if _, ok := node.(bool); ok {
		return nil
	}
	m, ok := node.(map[string]any)
	if !ok {
		return fail()
	}
	for _, g := range []string{"all", "any", "not"} {
		if child, ok := m[g]; ok {
			if len(m) != 1 {
				return fail()
			}
			if g == "not" {
				return validateRule(child, refs, depth+1)
			}
			a, ok := child.([]any)
			if !ok || len(a) == 0 || len(a) > 20 {
				return fail()
			}
			for _, c := range a {
				if err := validateRule(c, refs, depth+1); err != nil {
					return err
				}
			}
			return nil
		}
	}
	if len(m) != 3 {
		return fail()
	}
	op, ok := m["op"].(string)
	if !ok || !contains([]string{"gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below"}, op) {
		return fail()
	}
	for _, k := range []string{"left", "right"} {
		switch v := m[k].(type) {
		case string:
			if !refs[v] {
				return fail()
			}
		case float64:
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return fail()
			}
		default:
			return fail()
		}
	}
	return nil
}

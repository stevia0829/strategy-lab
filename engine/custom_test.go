package engine

import (
	"os"
	"testing"
)

func TestCustomTargetsAreCausalAndTradeNextOpen(t *testing.T) {
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
	s.Start, s.End = "", ""
	s.Execution.InitialCash = 1000
	s.Execution.CommissionRate = 0
	s.Execution.MinCommission = 0
	s.Execution.Slippage = 0
	s.Execution.LotSize = 1
	csv := "date,symbol,open,high,low,close,volume\n" +
		"2024-01-01,A,10,10,10,10,100\n" +
		"2024-01-02,A,11,11,11,11,100\n" +
		"2024-01-03,A,12,12,12,12,100\n"
	lengths := []int{}
	r, err := RunWithTargets(s, csv, func(ctx Context) ([]string, error) {
		lengths = append(lengths, len(ctx.History["A"]))
		for _, bar := range ctx.History["A"] {
			if bar.Date > ctx.Date {
				t.Fatal("future bar in context")
			}
		}
		if ctx.Date == "2024-01-01" {
			return []string{"A"}, nil
		}
		return nil, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Fills) != 2 || r.Fills[0].Date != "2024-01-02" || r.Fills[1].Date != "2024-01-03" {
		t.Fatalf("unexpected fills: %+v", r.Fills)
	}
	if len(lengths) != 3 || lengths[0] != 1 || lengths[1] != 2 || lengths[2] != 3 {
		t.Fatalf("unexpected history lengths: %v", lengths)
	}
	_, err = RunWithTargets(s, csv, func(ctx Context) ([]string, error) {
		return []string{"A", "A"}, nil
	})
	if err == nil {
		t.Fatal("duplicate targets accepted")
	}
}

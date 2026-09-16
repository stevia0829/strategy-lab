package main

import (
	"math"
	"strategylab/engine"
)

// Decide runs at each close. Its targets are traded at the next session's open.
func Decide(ctx engine.Context) []string {
	bars := ctx.History["510300"]
	values := engine.Calculate(bars, engine.Indicator{Kind: "rsi", Period: 14})
	if len(values) == 0 {
		return nil
	}
	latest := values[len(values)-1]
	if !math.IsNaN(latest) && latest > 50 {
		return []string{"510300"}
	}
	return nil
}

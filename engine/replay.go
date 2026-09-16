package engine

import (
	"crypto/sha256"
	"fmt"
	"math"
	"sort"
	"strings"
)

type Fill struct {
	Date       string  `json:"date"`
	SignalDate string  `json:"signal_date"`
	Symbol     string  `json:"symbol"`
	Side       string  `json:"side"`
	Quantity   int     `json:"quantity"`
	Price      float64 `json:"price"`
	Fee        float64 `json:"fee"`
}
type Closed struct {
	Symbol    string  `json:"symbol"`
	EntryDate string  `json:"entry_date"`
	ExitDate  string  `json:"exit_date"`
	Quantity  int     `json:"quantity"`
	PnL       float64 `json:"pnl"`
}
type Rejection struct {
	Date   string `json:"date"`
	Symbol string `json:"symbol"`
	Side   string `json:"side"`
	Reason string `json:"reason"`
}
type Point struct {
	Date      string         `json:"date"`
	Equity    float64        `json:"equity"`
	Cash      float64        `json:"cash"`
	Exposure  float64        `json:"exposure"`
	Benchmark float64        `json:"benchmark"`
	Stale     []string       `json:"stale_symbols"`
	Positions map[string]int `json:"positions"`
}
type Signal struct {
	Date    string   `json:"date"`
	Targets []string `json:"targets"`
}
type Result struct {
	Engine        string         `json:"engine"`
	EngineVersion string         `json:"engine_version"`
	StrategyName  string         `json:"strategy_name"`
	DataSHA       string         `json:"data_sha256"`
	Metrics       map[string]any `json:"metrics"`
	Equity        []Point        `json:"equity"`
	Fills         []Fill         `json:"fills"`
	Closed        []Closed       `json:"closed"`
	Rejected      []Rejection    `json:"rejected"`
	Signals       []Signal       `json:"signals"`
	Warnings      []string       `json:"warnings"`
}
type position struct {
	Quantity int
	Date     string
	Cost     float64
}

// Context contains only bars known through the signal date. Custom strategies
// choose target symbols; the engine retains its normal next-open execution.
type Context struct {
	Date      string
	History   map[string][]Bar
	Positions map[string]int
	Cash      float64
	Equity    float64
}

type TargetDecider func(Context) ([]string, error)

// Run executes yesterday's close signals at the next calendar session's open.
func Run(s Strategy, text string) (Result, error) {
	return RunWithTargets(s, text, nil)
}

// RunWithTargets lets a local Go strategy choose daily targets without changing
// portfolio accounting. A nil decider preserves the declarative strategy.
func RunWithTargets(s Strategy, text string, decide TargetDecider) (Result, error) {
	r := Result{Engine: "go", EngineVersion: Version, StrategyName: s.Name, DataSHA: fmt.Sprintf("%x", sha256.Sum256([]byte(text))), Equity: []Point{}, Fills: []Fill{}, Closed: []Closed{}, Rejected: []Rejection{}, Signals: []Signal{}}
	if err := s.Validate(); err != nil {
		return r, err
	}
	data, err := ReadCSV(text)
	if err != nil {
		return r, err
	}
	universe := append([]string{}, s.Universe...)
	sort.Strings(universe)
	needed := map[string]bool{s.Benchmark: true}
	for _, c := range universe {
		needed[c] = true
	}
	cal := map[string]bool{}
	synthetic := false
	for c := range needed {
		if len(data[c]) == 0 {
			return r, fmt.Errorf("CSV missing requested symbol %s", c)
		}
		for d := range data[c] {
			cal[d] = true
		}
		if strings.HasPrefix(c, "DEMO") {
			synthetic = true
		}
	}
	calendar := sortedKeys(cal)
	dates := []string{}
	for _, d := range calendar {
		if (s.Start == "" || d >= s.Start) && (s.End == "" || d <= s.End) {
			dates = append(dates, d)
		}
	}
	if len(dates) == 0 {
		return r, fmt.Errorf("no sessions in range")
	}
	series := map[string]map[string][]float64{}
	indices := map[string]map[string]int{}
	for _, c := range universe {
		days := sortedKeys(data[c])
		bars := make([]Bar, len(days))
		indices[c] = map[string]int{}
		series[c] = map[string][]float64{}
		for i, d := range days {
			bars[i] = data[c][d]
			indices[c][d] = i
		}
		for _, f := range fields {
			v := make([]float64, len(days))
			for i, b := range bars {
				v[i] = b.Field(f)
			}
			series[c][f] = v
		}
		for key, spec := range s.Indicators {
			series[c][key] = Calculate(bars, spec)
		}
	}
	e, sel := s.Execution, s.Selection
	cash := e.InitialCash
	positions := map[string]position{}
	marks := map[string]float64{}
	costs, turnover := 0.0, 0.0
	targets := func(day string, equityHint float64) ([]string, error) {
		if decide != nil {
			history := map[string][]Bar{}
			for c := range needed {
				history[c] = []Bar{}
				for _, d := range sortedKeys(data[c]) {
					if d > day {
						break
					}
					history[c] = append(history[c], data[c][d])
				}
			}
			posCopy := map[string]int{}
			for c, p := range positions {
				posCopy[c] = p.Quantity
			}
			chosen, err := decide(Context{day, history, posCopy, cash, equityHint})
			if err != nil {
				return nil, fmt.Errorf("decide(%s): %w", day, err)
			}
			if len(chosen) > sel.MaxPositions {
				return nil, fmt.Errorf("decide(%s): targets exceed max_positions", day)
			}
			seen := map[string]bool{}
			for _, c := range chosen {
				if !needed[c] || !contains(universe, c) || seen[c] {
					return nil, fmt.Errorf("decide(%s): duplicate or unknown target %q", day, c)
				}
				seen[c] = true
			}
			sort.Strings(chosen)
			return chosen, nil
		}
		keep, candidates := []string{}, []string{}
		for _, c := range universe {
			i, ok := indices[c][day]
			_, held := positions[c]
			if !ok {
				if held {
					keep = append(keep, c)
				}
				continue
			}
			v := series[c]
			exiting := Evaluate(s.Exit, v, i) == 1
			if held && !exiting {
				if sel.Mode == "hold" {
					keep = append(keep, c)
				} else {
					candidates = append(candidates, c)
				}
				continue
			}
			if !held && !exiting && Evaluate(s.Entry, v, i) == 1 {
				candidates = append(candidates, c)
			}
		}
		type ranked struct {
			code  string
			value float64
		}
		rows := []ranked{}
		for _, c := range candidates {
			v := series[c][sel.RankBy][indices[c][day]]
			if !math.IsNaN(v) {
				rows = append(rows, ranked{c, v})
			} else if _, held := positions[c]; held {
				keep = append(keep, c)
			}
		}
		sort.Slice(rows, func(i, j int) bool {
			if rows[i].value == rows[j].value {
				return rows[i].code < rows[j].code
			}
			if sel.Descending {
				return rows[i].value > rows[j].value
			}
			return rows[i].value < rows[j].value
		})
		sort.Strings(keep)
		for _, row := range rows {
			keep = append(keep, row.code)
		}
		if len(keep) > sel.MaxPositions {
			keep = keep[:sel.MaxPositions]
		}
		sort.Strings(keep)
		return keep, nil
	}
	previous := ""
	startIndex := sort.SearchStrings(calendar, dates[0])
	pending := []string{}
	if startIndex > 0 {
		previous = calendar[startIndex-1]
		pending, err = targets(previous, e.InitialCash)
		if err != nil {
			return r, err
		}
	}
	for _, c := range universe {
		for _, d := range sortedKeys(data[c]) {
			if d < dates[0] {
				marks[c] = data[c][d].Close
			}
		}
	}
	base, benchmarkMark := 0.0, 0.0
	for _, day := range dates {
		bb, ok := data[s.Benchmark][day]
		if base == 0 {
			if !ok {
				return r, fmt.Errorf("benchmark missing on first session")
			}
			base = bb.Open
		}
		if ok {
			benchmarkMark = bb.Close
		}
		reject := func(c, side, reason string) { r.Rejected = append(r.Rejected, Rejection{day, c, side, reason}) }
		for _, c := range sortedKeys(positions) {
			if contains(pending, c) {
				continue
			}
			b, ok := data[c][day]
			if !ok || b.Volume <= 0 {
				reject(c, "sell", "missing_or_paused")
				continue
			}
			if b.LimitDown > 0 && b.Open <= b.LimitDown {
				reject(c, "sell", "limit_down")
				continue
			}
			p := positions[c]
			price := b.Open * (1 - e.Slippage)
			notional := float64(p.Quantity) * price
			fee := math.Max(e.MinCommission, notional*e.CommissionRate)
			if cash+notional < fee {
				reject(c, "sell", "insufficient_cash")
				continue
			}
			cash += notional - fee
			costs += fee + float64(p.Quantity)*(b.Open-price)
			turnover += notional
			r.Fills = append(r.Fills, Fill{day, previous, c, "sell", p.Quantity, price, fee})
			r.Closed = append(r.Closed, Closed{c, p.Date, day, p.Quantity, notional - fee - p.Cost})
			delete(positions, c)
		}
		heldValue := func() float64 {
			v := 0.0
			for _, c := range sortedKeys(positions) {
				price := marks[c]
				if b, ok := data[c][day]; ok {
					price = b.Open
				}
				v += float64(positions[c].Quantity) * price
			}
			return v
		}
		openingEquity := cash + heldValue()
		for _, c := range pending {
			if _, ok := positions[c]; ok {
				continue
			}
			if len(positions) >= sel.MaxPositions {
				reject(c, "buy", "slots_full")
				continue
			}
			b, ok := data[c][day]
			if !ok || b.Volume <= 0 {
				reject(c, "buy", "missing_or_paused")
				continue
			}
			if b.LimitUp > 0 && b.Open >= b.LimitUp {
				reject(c, "buy", "limit_up")
				continue
			}
			budget := math.Min(cash, math.Min(openingEquity*e.MaxExposure/float64(sel.MaxPositions), math.Max(0, openingEquity*e.MaxExposure-heldValue())))
			price := b.Open * (1 + e.Slippage)
			lot := float64(e.LotSize)
			qty := int(math.Floor(budget/(price*(1+e.CommissionRate))/lot)) * e.LotSize
			fee := math.Max(e.MinCommission, float64(qty)*price*e.CommissionRate)
			if float64(qty)*price+fee > budget {
				qty = int(math.Max(0, math.Floor((budget-e.MinCommission)/price/lot))) * e.LotSize
				fee = math.Max(e.MinCommission, float64(qty)*price*e.CommissionRate)
			}
			if qty <= 0 || float64(qty)*price+fee > budget+1e-8 {
				reject(c, "buy", "insufficient_cash")
				continue
			}
			cash -= float64(qty)*price + fee
			costs += fee + float64(qty)*(price-b.Open)
			turnover += float64(qty) * price
			positions[c] = position{qty, day, float64(qty)*price + fee}
			r.Fills = append(r.Fills, Fill{day, previous, c, "buy", qty, price, fee})
		}
		stale := []string{}
		for _, c := range universe {
			if b, ok := data[c][day]; ok {
				marks[c] = b.Close
			} else if _, held := positions[c]; held {
				stale = append(stale, c)
			}
		}
		value := 0.0
		posCopy := map[string]int{}
		for _, c := range sortedKeys(positions) {
			value += float64(positions[c].Quantity) * marks[c]
			posCopy[c] = positions[c].Quantity
		}
		equity := cash + value
		exposure := 0.0
		if equity > 0 {
			exposure = value / equity
		}
		r.Equity = append(r.Equity, Point{day, equity, cash, exposure, e.InitialCash * benchmarkMark / base, stale, posCopy})
		pending, err = targets(day, equity)
		if err != nil {
			return r, err
		}
		r.Signals = append(r.Signals, Signal{day, pending})
		previous = day
	}
	r.Metrics = summarize(r, e.InitialCash, costs, turnover)
	warning := "Data adjustments, survivorship and calendar quality are the data provider responsibility."
	if synthetic {
		warning = "Synthetic/demo data is not investment evidence."
	}
	r.Warnings = []string{warning, "Open positions are marked to close at the end; no forced liquidation.", "Exposure cap applies at entry; existing holdings are not rebalanced daily."}
	return r, nil
}
func summarize(r Result, initial, costs, turnover float64) map[string]any {
	n := len(r.Equity)
	returns := make([]float64, n)
	previous := initial
	for i, p := range r.Equity {
		returns[i] = p.Equity/previous - 1
		previous = p.Equity
	}
	mean := average(returns)
	std := 0.0
	if n > 1 {
		for _, v := range returns {
			std += (v - mean) * (v - mean)
		}
		std = math.Sqrt(std / float64(n-1))
	}
	peak, peakI, worstPeak, trough, maxDD := initial, -1, -1, -1, 0.0
	worstValue, longest := initial, 0
	for i, p := range r.Equity {
		if p.Equity >= peak {
			peak, peakI = p.Equity, i
		}
		dd := 1 - p.Equity/peak
		if dd > maxDD {
			maxDD, worstPeak, trough, worstValue = dd, peakI, i, peak
		}
		if i-peakI > longest {
			longest = i - peakI
		}
	}
	var recovery, peakDate, troughDate any
	if trough >= 0 {
		pi := worstPeak
		if pi < 0 {
			pi = 0
		}
		peakDate = r.Equity[pi].Date
		troughDate = r.Equity[trough].Date
		for i := trough + 1; i < n; i++ {
			if r.Equity[i].Equity >= worstValue {
				recovery = i - worstPeak
				break
			}
		}
	} else {
		recovery = 0
	}
	final := r.Equity[n-1]
	total := final.Equity/initial - 1
	var annual, sharpe, calmar, winRate any
	if final.Equity > 0 {
		exponent := math.Log(final.Equity/initial) * 252 / float64(n)
		if exponent < 700 {
			annual = math.Expm1(exponent)
		}
	} else {
		annual = -1.0
	}
	if std > 0 {
		sharpe = mean / std * math.Sqrt(252)
	}
	if a, ok := annual.(float64); ok && maxDD > 0 {
		calmar = a / maxDD
	}
	entries, wins := 0, 0
	for _, f := range r.Fills {
		if f.Side == "buy" {
			entries++
		}
	}
	for _, t := range r.Closed {
		if t.PnL > 0 {
			wins++
		}
	}
	if len(r.Closed) > 0 {
		winRate = float64(wins) / float64(len(r.Closed))
	}
	exposure := 0.0
	for _, p := range r.Equity {
		exposure += p.Exposure
	}
	return map[string]any{"total_return": total, "annual_return": annual, "max_drawdown": maxDD, "max_drawdown_peak_date": peakDate, "max_drawdown_trough_date": troughDate, "max_drawdown_recovery_days": recovery, "longest_underwater_days": longest, "sharpe": sharpe, "calmar": calmar, "entries": entries, "closed_trades": len(r.Closed), "win_rate": winRate, "total_costs": costs, "traded_notional_over_initial": turnover / initial, "average_exposure": exposure / float64(n), "benchmark_return": final.Benchmark/initial - 1, "excess_return": total - (final.Benchmark/initial - 1), "sessions": n, "final_equity": final.Equity}
}

package engine

import "math"

func blank(n int) []float64 {
	out := make([]float64, n)
	for i := range out {
		out[i] = math.NaN()
	}
	return out
}
func average(a []float64) float64 {
	s := 0.0
	for _, v := range a {
		s += v
	}
	return s / float64(len(a))
}
func ema(values []float64, p int) []float64 {
	out := blank(len(values))
	buf := []float64{}
	previous := math.NaN()
	for i, v := range values {
		if math.IsNaN(v) {
			buf = []float64{}
			previous = math.NaN()
		} else if math.IsNaN(previous) {
			buf = append(buf, v)
			if len(buf) == p {
				previous = average(buf)
			}
		} else {
			previous += 2 / float64(p+1) * (v - previous)
		}
		out[i] = previous
	}
	return out
}

// Calculate uses only prefixes: SMA-seeded EMA, Wilder RSI/ATR, unscaled MACD histogram.
func Calculate(bars []Bar, s Indicator) []float64 {
	field := s.Field
	if field == "" {
		field = "close"
	}
	values := make([]float64, len(bars))
	for i, b := range bars {
		values[i] = b.Field(field)
	}
	n, p := len(values), s.Period
	out := blank(n)
	if s.Kind == "ema" {
		return ema(values, p)
	}
	if s.Kind == "macd" {
		f, sl, sg := macdParams(s)
		fast, slow := ema(values, f), ema(values, sl)
		line := blank(n)
		for i := range line {
			line[i] = fast[i] - slow[i]
		}
		signal := ema(line, sg)
		if s.Output == "line" {
			return line
		}
		if s.Output == "signal" {
			return signal
		}
		for i := range out {
			out[i] = line[i] - signal[i]
		}
		return out
	}
	if s.Kind == "rsi" {
		gain, loss := 0.0, 0.0
		for i := 1; i < n; i++ {
			d := values[i] - values[i-1]
			up, down := math.Max(0, d), math.Max(0, -d)
			if i <= p {
				gain += up / float64(p)
				loss += down / float64(p)
			} else {
				gain = (gain*float64(p-1) + up) / float64(p)
				loss = (loss*float64(p-1) + down) / float64(p)
			}
			if i >= p {
				if gain == 0 && loss == 0 {
					out[i] = 50
				} else if loss == 0 {
					out[i] = 100
				} else {
					out[i] = 100 - 100/(1+gain/loss)
				}
			}
		}
		return out
	}
	if s.Kind == "atr" {
		avg := 0.0
		for i, b := range bars {
			tr := b.High - b.Low
			if i > 0 {
				tr = math.Max(tr, math.Max(math.Abs(b.High-bars[i-1].Close), math.Abs(b.Low-bars[i-1].Close)))
			}
			if i < p {
				avg += tr / float64(p)
			} else {
				avg = (avg*float64(p-1) + tr) / float64(p)
			}
			if i >= p-1 {
				out[i] = avg
			}
		}
		return out
	}
	for i := range values {
		if s.Kind == "roc" {
			if i >= p && values[i-p] > 0 {
				out[i] = (values[i]/values[i-p] - 1) * 100
			}
			continue
		}
		if i < p-1 {
			continue
		}
		segment := values[i+1-p : i+1]
		switch s.Kind {
		case "sma":
			out[i] = average(segment)
		case "highest":
			out[i] = segment[0]
			for _, v := range segment {
				out[i] = math.Max(out[i], v)
			}
		case "lowest":
			out[i] = segment[0]
			for _, v := range segment {
				out[i] = math.Min(out[i], v)
			}
		case "momentum_score":
			y, w := make([]float64, p), make([]float64, p)
			sw, sx, sy, sxx, sxy := 0.0, 0.0, 0.0, 0.0, 0.0
			valid := true
			for j, v := range segment {
				if v <= 0 {
					valid = false
					break
				}
				y[j] = math.Log(v)
				w[j] = 1 + float64(j)/float64(p-1)
				fw := w[j] * w[j]
				x := float64(j)
				sw += fw
				sx += fw * x
				sy += fw * y[j]
				sxx += fw * x * x
				sxy += fw * x * y[j]
			}
			if !valid {
				continue
			}
			slope := (sw*sxy - sx*sy) / (sw*sxx - sx*sx)
			intercept := (sy - slope*sx) / sw
			mean := average(y)
			total, res := 0.0, 0.0
			for j, v := range y {
				d := v - mean
				total += w[j] * d * d
				r := v - slope*float64(j) - intercept
				res += w[j] * r * r
			}
			r2 := 0.0
			if total > 1e-15 {
				r2 = 1 - res/total
			}
			out[i] = math.Expm1(slope*250) * r2
		}
		if math.IsInf(out[i], 0) {
			out[i] = math.NaN()
		}
	}
	return out
}

// Evaluate returns -1 for unavailable warmup, 0 false, 1 true; NOT never converts missing data to true.
func Evaluate(node any, series map[string][]float64, i int) int {
	truth := func(b bool) int {
		if b {
			return 1
		}
		return 0
	}
	if b, ok := node.(bool); ok {
		return truth(b)
	}
	m := node.(map[string]any)
	if child, ok := m["not"]; ok {
		v := Evaluate(child, series, i)
		if v < 0 {
			return -1
		}
		return 1 - v
	}
	for _, g := range []string{"all", "any"} {
		if child, ok := m[g]; ok {
			missing := false
			for _, c := range child.([]any) {
				v := Evaluate(c, series, i)
				if g == "all" && v == 0 {
					return 0
				}
				if g == "any" && v == 1 {
					return 1
				}
				if v < 0 {
					missing = true
				}
			}
			if missing {
				return -1
			}
			return truth(g == "all")
		}
	}
	value := func(v any, idx int) float64 {
		if idx < 0 {
			return math.NaN()
		}
		if ref, ok := v.(string); ok {
			return series[ref][idx]
		}
		return v.(float64)
	}
	a, b := value(m["left"], i), value(m["right"], i)
	if math.IsNaN(a) || math.IsNaN(b) {
		return -1
	}
	switch m["op"].(string) {
	case "gt":
		return truth(a > b)
	case "gte":
		return truth(a >= b)
	case "lt":
		return truth(a < b)
	case "lte":
		return truth(a <= b)
	case "eq":
		return truth(a == b)
	}
	pa, pb := value(m["left"], i-1), value(m["right"], i-1)
	if math.IsNaN(pa) || math.IsNaN(pb) {
		return -1
	}
	if m["op"] == "cross_above" {
		return truth(pa <= pb && a > b)
	}
	return truth(pa >= pb && a < b)
}

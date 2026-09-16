"""Independent, standard-library Python daily-bar replay engine. No Go/JQ imports."""
import csv
import hashlib
import io
import json
import math
from datetime import date

VERSION = '0.1.0'
KINDS = ('sma', 'ema', 'rsi', 'macd', 'roc', 'momentum_score', 'atr', 'highest', 'lowest')
FIELDS = ('open', 'high', 'low', 'close', 'volume')
OPS = ('gt', 'gte', 'lt', 'lte', 'eq', 'cross_above', 'cross_below')


def keys(obj, allowed, required, where):
    if not isinstance(obj, dict):
        raise ValueError(where + ' must be an object')
    if set(obj) - set(allowed) or set(required) - set(obj):
        raise ValueError(where + ': unknown or missing fields')


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def integer(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def validate(s):
    keys(s, ('version', 'name', 'universe', 'benchmark', 'start', 'end', 'indicators', 'entry', 'exit', 'selection', 'execution'),
         ('version', 'name', 'universe', 'benchmark', 'indicators', 'entry', 'exit', 'selection', 'execution'), 'strategy')
    if type(s['version']) is not int or s['version'] != 1:
        raise ValueError('version must be 1')
    if not isinstance(s['name'], str) or not s['name'].strip():
        raise ValueError('name is required')
    u = s['universe']
    if not isinstance(u, list) or not 1 <= len(u) <= 100 or any(not isinstance(x, str) or not x for x in u) or len(set(u)) != len(u):
        raise ValueError('universe needs 1..100 unique symbols')
    if not isinstance(s['benchmark'], str) or not s['benchmark']:
        raise ValueError('benchmark is required')
    for key in ('start', 'end'):
        if key in s and not isinstance(s[key], str):
            raise ValueError(key + ' must be a string')
        if s.get(key):
            if not isinstance(s[key], str) or date.fromisoformat(s[key]).isoformat() != s[key]:
                raise ValueError(key + ' must be YYYY-MM-DD')
    if s.get('start') and s.get('end') and s['start'] > s['end']:
        raise ValueError('start is after end')
    if not isinstance(s['indicators'], dict) or len(s['indicators']) > 40:
        raise ValueError('at most 40 indicators')
    for name, spec in s['indicators'].items():
        if not name or name in FIELDS:
            raise ValueError('indicator name conflicts with price fields')
        keys(spec, ('kind', 'field', 'period', 'fast', 'slow', 'signal', 'output'), ('kind',), 'indicator')
        kind = spec['kind']
        if kind not in KINDS or spec.get('field', 'close') not in FIELDS:
            raise ValueError('unsupported indicator/field')
        if kind == 'macd':
            for param, default in (('fast', 12), ('slow', 26), ('signal', 9)):
                if not integer(spec.get(param, default), 2, 500):
                    raise ValueError('MACD periods must be 2..500')
            if spec.get('fast', 12) >= spec.get('slow', 26) or spec.get('output', 'hist') not in ('line', 'signal', 'hist'):
                raise ValueError('invalid MACD fast/slow/output')
        elif not integer(spec.get('period'), 2, 500):
            raise ValueError('indicator period must be 2..500')
    refs = set(FIELDS) | set(s['indicators'])
    def rule(node, depth=0):
        if depth > 8:
            raise ValueError('rule nesting exceeds 8')
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise ValueError('invalid rule')
        for group in ('all', 'any', 'not'):
            if group in node:
                if len(node) != 1:
                    raise ValueError('group must have exactly one key')
                if group == 'not':
                    rule(node[group], depth + 1)
                else:
                    if not isinstance(node[group], list) or not 1 <= len(node[group]) <= 20:
                        raise ValueError('group requires 1..20 rules')
                    for child in node[group]:
                        rule(child, depth + 1)
                return
        keys(node, ('left', 'op', 'right'), ('left', 'op', 'right'), 'condition')
        if node['op'] not in OPS:
            raise ValueError('unsupported operator')
        for v in (node['left'], node['right']):
            if not number(v) and not (isinstance(v, str) and v in refs):
                raise ValueError('operand must be finite number or known indicator')
    rule(s['entry']); rule(s['exit'])
    sel = s['selection']
    keys(sel, ('max_positions', 'rank_by', 'descending', 'mode'), ('max_positions', 'rank_by', 'descending', 'mode'), 'selection')
    if not integer(sel['max_positions'], 1, len(u)) or sel['rank_by'] not in refs or not isinstance(sel['descending'], bool) or sel['mode'] not in ('hold', 'rotate'):
        raise ValueError('invalid selection')
    e = s['execution']
    ef = ('initial_cash', 'commission_rate', 'min_commission', 'slippage', 'lot_size', 'max_exposure')
    keys(e, ef, ef, 'execution')
    if not all(number(e[k]) for k in ef):
        raise ValueError('execution values must be finite numbers')
    if not 0 < e['initial_cash'] <= 1e12 or not 0 <= e['commission_rate'] <= .05 or not 0 <= e['slippage'] <= .1 or e['min_commission'] < 0 or not 0 <= e['max_exposure'] <= 1 or not integer(e['lot_size'], 1, 1000000):
        raise ValueError('invalid execution values')
    return s


def read_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = ('date', 'symbol', 'open', 'high', 'low', 'close', 'volume')
    if not reader.fieldnames or not set(required) <= set(reader.fieldnames) or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('CSV requires unique date,symbol,open,high,low,close,volume headers')
    if set(reader.fieldnames) - set(required + ('limit_up', 'limit_down')):
        raise ValueError('unknown CSV columns')
    rows = {}
    count = 0
    for row in reader:
        count += 1
        if count > 100000 or None in row or any(v is None for v in row.values()):
            raise ValueError('CSV too large or malformed')
        day, symbol = row['date'], row['symbol']
        if date.fromisoformat(day).isoformat() != day or not symbol:
            raise ValueError('invalid date/symbol')
        item = {'date': day, 'symbol': symbol}
        for k in FIELDS + ('limit_up', 'limit_down'):
            value = float(row.get(k) or 0)
            if not math.isfinite(value) or value < 0:
                raise ValueError('invalid numeric CSV value')
            item[k] = value
        if min(item[k] for k in FIELDS[:4]) <= 0 or item['low'] > min(item['open'], item['close']) or item['high'] < max(item['open'], item['close']) or item['high'] < item['low']:
            raise ValueError('invalid OHLC range')
        if day in rows.setdefault(symbol, {}):
            raise ValueError('duplicate symbol/date')
        rows[symbol][day] = item
    if not count:
        raise ValueError('empty CSV')
    return rows


def ema(values, period):
    result, buf, previous = [], [], None
    for v in values:
        if v is None:
            buf, previous = [], None
            result.append(None)
        elif previous is None:
            buf.append(v)
            if len(buf) == period:
                previous = sum(buf) / period
            result.append(previous)
        else:
            previous += 2.0 / (period + 1) * (v - previous)
            result.append(previous)
    return result


def indicator(bars, spec):
    values = [b[spec.get('field', 'close')] for b in bars]
    n, kind, period = len(values), spec['kind'], spec.get('period', 14)
    out = [None] * n
    if kind == 'ema':
        return ema(values, period)
    if kind == 'macd':
        fast, slow = ema(values, spec.get('fast', 12)), ema(values, spec.get('slow', 26))
        line = [a - b if a is not None and b is not None else None for a, b in zip(fast, slow)]
        signal = ema(line, spec.get('signal', 9))
        return {'line': line, 'signal': signal, 'hist': [a - b if a is not None and b is not None else None for a, b in zip(line, signal)]}[spec.get('output', 'hist')]
    if kind == 'rsi':
        gain = loss = 0.0
        for i in range(1, n):
            diff = values[i] - values[i - 1]
            up, down = max(0, diff), max(0, -diff)
            if i <= period:
                gain += up / period; loss += down / period
            else:
                gain = (gain * (period - 1) + up) / period
                loss = (loss * (period - 1) + down) / period
            if i >= period:
                out[i] = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        return out
    if kind == 'atr':
        avg = 0.0
        for i, b in enumerate(bars):
            tr = b['high'] - b['low']
            if i:
                tr = max(tr, abs(b['high'] - bars[i - 1]['close']), abs(b['low'] - bars[i - 1]['close']))
            if i < period:
                avg += tr / period
            else:
                avg = (avg * (period - 1) + tr) / period
            if i >= period - 1:
                out[i] = avg
        return out
    for i in range(n):
        if kind == 'roc':
            if i >= period and values[i - period] > 0:
                out[i] = (values[i] / values[i - period] - 1) * 100
            continue
        if i < period - 1:
            continue
        segment = values[i + 1 - period:i + 1]
        if kind == 'sma': out[i] = sum(segment) / period
        elif kind == 'highest': out[i] = max(segment)
        elif kind == 'lowest': out[i] = min(segment)
        elif kind == 'momentum_score' and min(segment) > 0:
            y = [math.log(v) for v in segment]
            w = [1.0 + j / (period - 1) for j in range(period)]
            fw = [v * v for v in w]
            sw = sum(fw); sx = sum(fw[j] * j for j in range(period)); sy = sum(fw[j] * y[j] for j in range(period))
            sxx = sum(fw[j] * j * j for j in range(period)); sxy = sum(fw[j] * j * y[j] for j in range(period))
            slope = (sw * sxy - sx * sy) / (sw * sxx - sx * sx)
            intercept = (sy - slope * sx) / sw
            mean = sum(y) / period
            total = sum(w[j] * (y[j] - mean) ** 2 for j in range(period))
            residual = sum(w[j] * (y[j] - slope * j - intercept) ** 2 for j in range(period))
            r2 = 1 - residual / total if total > 1e-15 else 0.0
            try: out[i] = math.expm1(slope * 250) * r2
            except OverflowError: pass
    return [v if v is None or math.isfinite(v) else None for v in out]


def evaluate(rule, series, i):
    if isinstance(rule, bool): return rule
    if 'not' in rule:
        v = evaluate(rule['not'], series, i)
        return None if v is None else not v
    for group in ('all', 'any'):
        if group in rule:
            values = [evaluate(r, series, i) for r in rule[group]]
            if group == 'all' and False in values: return False
            if group == 'any' and True in values: return True
            return None if None in values else group == 'all'
    def value(operand, idx):
        if idx < 0: return None
        return series[operand][idx] if isinstance(operand, str) else operand
    a, b, op = value(rule['left'], i), value(rule['right'], i), rule['op']
    if a is None or b is None: return None
    if op == 'gt': return a > b
    if op == 'gte': return a >= b
    if op == 'lt': return a < b
    if op == 'lte': return a <= b
    if op == 'eq': return a == b
    pa, pb = value(rule['left'], i - 1), value(rule['right'], i - 1)
    if pa is None or pb is None: return None
    return (pa <= pb and a > b) if op == 'cross_above' else (pa >= pb and a < b)


def metrics(equity, closed, fills, initial, costs, turnover):
    values = [p['equity'] for p in equity]
    returns = [v / (values[i - 1] if i else initial) - 1 for i, v in enumerate(values)]
    n = len(values); mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)) if n > 1 else 0
    peak, peak_i, worst_peak, trough, maxdd = initial, -1, -1, -1, 0.0
    worst_value, longest = initial, 0
    for i, v in enumerate(values):
        if v >= peak:
            peak, peak_i = v, i
        dd = 1 - v / peak
        if dd > maxdd:
            maxdd, worst_peak, trough, worst_value = dd, peak_i, i, peak
        longest = max(longest, i - peak_i)
    recovery = None
    if trough >= 0:
        for i in range(trough + 1, n):
            if values[i] >= worst_value:
                recovery = i - worst_peak
                break
    else: recovery = 0
    total = values[-1] / initial - 1
    exponent = math.log(values[-1] / initial) * 252 / n if values[-1] > 0 else None
    annual = math.expm1(exponent) if exponent is not None and exponent < 700 else (-1.0 if exponent is None else None)
    return {'total_return': total, 'annual_return': annual, 'max_drawdown': maxdd,
            'max_drawdown_peak_date': equity[max(0, worst_peak)]['date'] if trough >= 0 else None,
            'max_drawdown_trough_date': equity[trough]['date'] if trough >= 0 else None,
            'max_drawdown_recovery_days': recovery, 'longest_underwater_days': longest,
            'sharpe': mean / std * math.sqrt(252) if std > 0 else None,
            'calmar': annual / maxdd if maxdd > 0 and annual is not None else None,
            'entries': sum(f['side'] == 'buy' for f in fills), 'closed_trades': len(closed),
            'win_rate': sum(t['pnl'] > 0 for t in closed) / len(closed) if closed else None,
            'total_costs': costs, 'traded_notional_over_initial': turnover / initial,
            'average_exposure': sum(p['exposure'] for p in equity) / n,
            'benchmark_return': equity[-1]['benchmark'] / initial - 1,
            'excess_return': total - (equity[-1]['benchmark'] / initial - 1),
            'sessions': n, 'final_equity': values[-1]}


def run(strategy, csv_text, decide=None):
    s = validate(strategy); data = read_csv(csv_text)
    universe = sorted(s['universe']); needed = sorted(set(universe + [s['benchmark']]))
    if any(c not in data for c in needed): raise ValueError('CSV is missing requested symbols/benchmark')
    calendar = sorted({d for c in needed for d in data[c]})
    dates = [d for d in calendar if (not s.get('start') or d >= s['start']) and (not s.get('end') or d <= s['end'])]
    if not dates: raise ValueError('no sessions in date range')
    series, indices = {}, {}
    for c in universe:
        days = sorted(data[c]); bars = [data[c][d] for d in days]
        series[c] = {f: [b[f] for b in bars] for f in FIELDS}
        series[c].update({key: indicator(bars, spec) for key, spec in s['indicators'].items()})
        indices[c] = {d: i for i, d in enumerate(days)}
    e, sel = s['execution'], s['selection']
    initial = float(e['initial_cash']); cash = initial; positions = {}; marks = {}
    fills, closed, rejected, curve, signals = [], [], [], [], []
    costs = turnover = 0.0
    def targets(day, equity_hint=None):
        if decide is not None:
            history = {c: [dict(data[c][d]) for d in sorted(data[c]) if d <= day]
                       for c in needed}
            context = {'date': day, 'history': history,
                       'positions': {c: p['quantity'] for c, p in sorted(positions.items())},
                       'cash': cash, 'equity': initial if equity_hint is None else equity_hint}
            chosen = decide(context)
            if (not isinstance(chosen, list) or len(chosen) > sel['max_positions']
                    or any(not isinstance(c, str) or c not in universe for c in chosen)
                    or len(set(chosen)) != len(chosen)):
                raise ValueError('decide(' + day + ') must return unique universe symbols, at most max_positions')
            return sorted(chosen)
        keep, candidates = [], []
        for c in universe:
            if day not in indices[c]:
                if c in positions: keep.append(c)
                continue
            i = indices[c][day]; v = series[c]
            exiting = evaluate(s['exit'], v, i) is True
            if c in positions and not exiting:
                if sel['mode'] == 'hold': keep.append(c); continue
                candidates.append(c); continue
            if c not in positions and not exiting and evaluate(s['entry'], v, i) is True:
                candidates.append(c)
        ranked = []
        for c in candidates:
            value = series[c][sel['rank_by']][indices[c][day]]
            if value is not None: ranked.append((c, value))
            elif c in positions: keep.append(c)
        ranked.sort(key=lambda p: ((-p[1] if sel['descending'] else p[1]), p[0]))
        return sorted((sorted(keep) + [c for c, v in ranked])[:sel['max_positions']])
    start_index = calendar.index(dates[0])
    previous = calendar[start_index - 1] if start_index else None
    pending = targets(previous) if previous else []
    # Historical closes may value missing first-session bars, never future bars.
    for c in universe:
        earlier = [d for d in data[c] if d < dates[0]]
        if earlier: marks[c] = data[c][max(earlier)]['close']
    benchmark_base = None; benchmark_mark = None
    for day in dates:
        bar_b = data[s['benchmark']].get(day)
        if benchmark_base is None:
            if bar_b is None: raise ValueError('benchmark missing on first session')
            benchmark_base = bar_b['open']
        if bar_b: benchmark_mark = bar_b['close']
        def reject(c, side, reason):
            rejected.append({'date': day, 'symbol': c, 'side': side, 'reason': reason})
        for c in sorted(set(positions) - set(pending)):
            b = data[c].get(day)
            if b is None or b['volume'] <= 0: reject(c, 'sell', 'missing_or_paused'); continue
            if b['limit_down'] and b['open'] <= b['limit_down']: reject(c, 'sell', 'limit_down'); continue
            pos = positions[c]; price = b['open'] * (1 - e['slippage'])
            notional = pos['quantity'] * price; fee = max(e['min_commission'], notional * e['commission_rate'])
            # No borrowing to fund an exit commission.
            if cash + notional < fee: reject(c, 'sell', 'insufficient_cash'); continue
            cash += notional - fee; costs += fee + pos['quantity'] * (b['open'] - price); turnover += notional
            fills.append({'date': day, 'signal_date': previous, 'symbol': c, 'side': 'sell', 'quantity': pos['quantity'], 'price': price, 'fee': fee})
            closed.append({'symbol': c, 'entry_date': pos['date'], 'exit_date': day, 'quantity': pos['quantity'], 'pnl': notional - fee - pos['cost']})
            del positions[c]
        opening_equity = cash + sum(p['quantity'] * (data[c][day]['open'] if day in data[c] else marks[c]) for c, p in sorted(positions.items()))
        for c in sorted(set(pending) - set(positions)):
            if len(positions) >= sel['max_positions']: reject(c, 'buy', 'slots_full'); continue
            b = data[c].get(day)
            if b is None or b['volume'] <= 0: reject(c, 'buy', 'missing_or_paused'); continue
            if b['limit_up'] and b['open'] >= b['limit_up']: reject(c, 'buy', 'limit_up'); continue
            held_value = sum(p['quantity'] * (data[k][day]['open'] if day in data[k] else marks[k]) for k, p in sorted(positions.items()))
            budget = min(cash, opening_equity * e['max_exposure'] / sel['max_positions'], max(0, opening_equity * e['max_exposure'] - held_value))
            price = b['open'] * (1 + e['slippage']); lot = int(e['lot_size'])
            qty = math.floor(budget / (price * (1 + e['commission_rate'])) / lot) * lot
            fee = max(e['min_commission'], qty * price * e['commission_rate'])
            if qty * price + fee > budget:
                qty = max(0, math.floor((budget - e['min_commission']) / price / lot) * lot)
                fee = max(e['min_commission'], qty * price * e['commission_rate'])
            if qty <= 0 or qty * price + fee > budget + 1e-8: reject(c, 'buy', 'insufficient_cash'); continue
            cash -= qty * price + fee; costs += fee + qty * (price - b['open']); turnover += qty * price
            positions[c] = {'quantity': qty, 'date': day, 'cost': qty * price + fee}
            fills.append({'date': day, 'signal_date': previous, 'symbol': c, 'side': 'buy', 'quantity': qty, 'price': price, 'fee': fee})
        stale = []
        for c in universe:
            if day in data[c]: marks[c] = data[c][day]['close']
            elif c in positions: stale.append(c)
        value = sum(p['quantity'] * marks[c] for c, p in sorted(positions.items()))
        equity = cash + value
        curve.append({'date': day, 'equity': equity, 'cash': cash, 'exposure': value / equity if equity > 0 else 0,
                      'benchmark': initial * benchmark_mark / benchmark_base, 'stale_symbols': stale,
                      'positions': {c: p['quantity'] for c, p in sorted(positions.items())}})
        pending = targets(day, equity); signals.append({'date': day, 'targets': pending})
        previous = day
    return {'engine': 'python', 'engine_version': VERSION, 'strategy_name': s['name'],
            'data_sha256': hashlib.sha256(csv_text.encode()).hexdigest(),
            'metrics': metrics(curve, closed, fills, initial, costs, turnover),
            'equity': curve, 'fills': fills, 'closed': closed, 'rejected': rejected, 'signals': signals,
            'warnings': ['Synthetic/demo data is not investment evidence.' if any(c.startswith('DEMO') for c in needed) else 'Data adjustments, survivorship and calendar quality are the data provider responsibility.',
                         'Open positions are marked to close at the end; no forced liquidation.',
                         'Exposure cap applies at entry; existing holdings are not rebalanced daily.']}

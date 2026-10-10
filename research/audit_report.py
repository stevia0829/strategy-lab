"""Independently reconcile a Strategy Lab report against its input OHLCV CSV.

This checks accounting and execution against the supplied bars. It does not
establish that the supplied bars are correctly adjusted or match another vendor.
"""

import argparse
from collections import defaultdict
import csv
from decimal import Decimal
import json
from pathlib import Path


def close(actual, expected, label):
    if abs(Decimal(str(actual)) - expected) > max(Decimal('0.00001'), abs(expected) * Decimal('1e-9')):
        raise AssertionError(f'{label}: reported {actual}, independently calculated {expected}')


def audit(strategy, bars_path, report):
    bars = {}
    with Path(bars_path).open(newline='') as stream:
        for row in csv.DictReader(stream):
            key = (row['date'], row['symbol'])
            if key in bars:
                raise AssertionError('duplicate bar ' + str(key))
            bars[key] = {name: Decimal(row[name]) for name in
                         ('open', 'high', 'low', 'close', 'volume')}
    execution = strategy['execution']
    cash = Decimal(str(execution['initial_cash']))
    initial = cash
    rate = Decimal(str(execution['commission_rate']))
    min_fee = Decimal(str(execution['min_commission']))
    slip = Decimal(str(execution['slippage']))
    lot = execution['lot_size']
    positions = {}
    marks = {}
    fills_by_day = defaultdict(list)
    for fill in report['fills']:
        fills_by_day[fill['date']].append(fill)
    signals = {signal['date']: set(signal['targets']) for signal in report['signals']}
    benchmark_base = None
    benchmark_mark = None
    last_date = None
    high = initial
    max_drawdown = Decimal('0')
    for point in report['equity']:
        day = point['date']
        if last_date is not None and day <= last_date:
            raise AssertionError('equity dates are not strictly increasing')
        benchmark_bar = bars.get((day, strategy['benchmark']))
        if benchmark_base is None:
            if benchmark_bar is None:
                raise AssertionError('benchmark missing on first session')
            benchmark_base = benchmark_bar['open']
        if benchmark_bar is not None:
            benchmark_mark = benchmark_bar['close']
        seen_buy = False
        for fill in fills_by_day[day]:
            symbol, side, qty = fill['symbol'], fill['side'], fill['quantity']
            if side == 'buy':
                seen_buy = True
            elif seen_buy:
                raise AssertionError(f'{day}: sell occurred after a buy')
            if symbol not in strategy['universe'] or not isinstance(qty, int) or qty <= 0 or qty % lot:
                raise AssertionError(f'{day}: invalid fill quantity or symbol')
            if fill['signal_date'] >= day:
                raise AssertionError(f'{day}: fill uses current/future signal')
            if fill['signal_date'] in signals and (symbol in signals[fill['signal_date']]) != (side == 'buy'):
                raise AssertionError(f'{day}: fill conflicts with prior target')
            bar = bars.get((day, symbol))
            if bar is None or bar['volume'] <= 0:
                raise AssertionError(f'{day}: traded missing/paused {symbol}')
            expected_price = bar['open'] * (1 + slip if side == 'buy' else 1 - slip)
            close(fill['price'], expected_price, f'{day} {symbol} fill price')
            price = Decimal(str(fill['price']))
            expected_fee = max(min_fee, qty * price * rate)
            close(fill['fee'], expected_fee, f'{day} {symbol} fee')
            fee = Decimal(str(fill['fee']))
            if side == 'sell':
                if positions.get(symbol) != qty:
                    raise AssertionError(f'{day}: sell quantity exceeds holdings')
                cash += qty * price - fee
                del positions[symbol]
            else:
                if symbol in positions or len(positions) >= strategy['selection']['max_positions']:
                    raise AssertionError(f'{day}: duplicate or excessive position')
                cash -= qty * price + fee
                if cash < Decimal('-0.00001'):
                    raise AssertionError(f'{day}: negative cash')
                positions[symbol] = qty
        for symbol in positions:
            bar = bars.get((day, symbol))
            if bar is not None:
                marks[symbol] = bar['close']
            if symbol not in marks:
                raise AssertionError(f'{day}: holding has no historical mark')
        equity = cash + sum((qty * marks[symbol] for symbol, qty in positions.items()), Decimal('0'))
        exposure = (equity - cash) / equity if equity > 0 else Decimal('0')
        if point['positions'] != positions:
            raise AssertionError(f'{day}: holdings disagree with fills')
        close(point['cash'], cash, f'{day} cash')
        close(point['equity'], equity, f'{day} equity')
        close(point['exposure'], exposure, f'{day} exposure')
        close(point['benchmark'], initial * benchmark_mark / benchmark_base, f'{day} benchmark')
        high = max(high, equity)
        max_drawdown = max(max_drawdown, 1 - equity / high)
        last_date = day
    close(report['metrics']['final_equity'], equity, 'final equity')
    close(report['metrics']['total_return'], equity / initial - 1, 'total return')
    close(report['metrics']['max_drawdown'], max_drawdown, 'max drawdown')
    return {'sessions': len(report['equity']), 'fills': len(report['fills']),
            'final_equity': str(equity), 'max_drawdown': str(max_drawdown)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--bars', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    strategy = json.loads(Path(args.strategy).read_text())
    report = json.loads(Path(args.report).read_text())
    print(json.dumps(audit(strategy, args.bars, report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

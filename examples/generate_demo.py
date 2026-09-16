"""Deterministic synthetic scenarios, NOT real exchange data or investment evidence."""
import csv
import math
from datetime import date, timedelta
from pathlib import Path

path = Path(__file__).with_name('demo.csv')
with path.open('w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['date','symbol','open','high','low','close','volume'])
    day = date(2023, 1, 2)
    prices = [100.0, 90.0, 105.0]
    symbols = ['DEMO_EQ', 'DEMO_GOLD', 'DEMO_BOND']
    for i in range(800):
        while day.weekday() >= 5: day += timedelta(days=1)
        for j, symbol in enumerate(symbols):
            regime = (i // 100 + j) % 4
            drift = [.0013, -.0011, .0001, .0008][regime]
            scale = [.008, .006, .001][j]
            opening = prices[j] * (1 + .001 * math.sin(i * .71 + j))
            close = opening * (1 + drift / (j + 1) + scale * math.sin(i * .18 + j * 2) + scale * .6 * math.cos(i * .83 + j))
            writer.writerow([day.isoformat(), symbol, '%.8f' % opening, '%.8f' % (max(opening, close) * 1.004),
                             '%.8f' % (min(opening, close) * .996), '%.8f' % close, 1000000 + i * 100])
            prices[j] = close
        day += timedelta(days=1)
print(path)

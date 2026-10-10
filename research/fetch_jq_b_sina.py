"""Download a reproducible raw-price CSV for the user-supplied JQ B comparison.

Sina's public daily endpoint is a diagnostic fallback. Its bars are unadjusted,
so results from this CSV cannot be treated as an exact JoinQuant pre-adjusted replay.
"""

import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'research/jq_rotation_guard_b.json').read_text())
URL = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'


def fetch(symbol):
    prefix = 'sh' if symbol == '000300' or symbol[0] in '569' else 'sz'
    query = urlencode({'symbol': prefix + symbol, 'scale': '240', 'ma': 'no', 'datalen': '1023'})
    request = Request(URL + '?' + query, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, list) or not payload:
        raise ValueError(symbol + ' has no Sina daily bars')
    rows = []
    seen = set()
    for bar in payload:
        day = date.fromisoformat(bar['day'])
        if day in seen:
            raise ValueError(symbol + ' has duplicate date ' + str(day))
        seen.add(day)
        if not date(2023, 11, 1) <= day <= date(2026, 9, 15):
            continue
        opening, high, low, close, volume = (
            Decimal(bar[key]) for key in ('open', 'high', 'low', 'close', 'volume'))
        if (not all(value.is_finite() for value in (opening, high, low, close, volume))
                or min(opening, high, low, close) <= 0 or volume < 0
                or low > min(opening, close) or high < max(opening, close)):
            raise ValueError(symbol + ' has invalid OHLCV on ' + str(day))
        rows.append((day.isoformat(), symbol, opening, high, low, close, volume))
    if not rows:
        raise ValueError(symbol + ' has no bars in requested range')
    return symbol, rows


def main():
    symbols = sorted(set(CONFIG['universe']) | {CONFIG['benchmark']})
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(fetch, symbols))
    rows = sorted((row for _, bars in fetched for row in bars))
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
    writer.writerows(rows)
    csv_text = output.getvalue()
    target = Path('/tmp/strategy-lab-jq-b-sina-raw.csv')
    target.write_text(csv_text)
    meta = {'source': 'Sina CN_MarketData.getKLineData', 'adjustment': 'raw',
            'strategy': str(ROOT / 'research/jq_rotation_guard_b.json'),
            'sha256': hashlib.sha256(csv_text.encode()).hexdigest(),
            'rows': len(rows), 'symbol_counts': {symbol: len(bars) for symbol, bars in fetched}}
    Path('/tmp/strategy-lab-jq-b-sina-raw-meta.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    print('wrote', target, 'rows', len(rows), 'symbols', len(fetched), flush=True)


if __name__ == '__main__':
    main()

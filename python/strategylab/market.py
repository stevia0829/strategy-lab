"""PostgreSQL-backed, on-demand Eastmoney daily bars for SSE/SZSE stocks and ETFs."""
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import io
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROVIDER = 'eastmoney'
ADJUSTMENT = 'qfq'
API_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
TENCENT_URL = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
DEFAULT_DSN = 'postgresql://strategy_lab:strategy-lab-local@127.0.0.1:55432/strategy_lab'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS market_bars (
    source TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    symbol VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(18, 6) NOT NULL CHECK (open > 0),
    high NUMERIC(18, 6) NOT NULL CHECK (high > 0),
    low NUMERIC(18, 6) NOT NULL CHECK (low > 0),
    close NUMERIC(18, 6) NOT NULL CHECK (close > 0),
    volume NUMERIC(24, 2) NOT NULL CHECK (volume >= 0),
    fetched_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, adjustment, symbol, trade_date),
    CHECK (low <= LEAST(open, close) AND high >= GREATEST(open, close))
);
CREATE TABLE IF NOT EXISTS market_coverage (
    source TEXT NOT NULL,
    adjustment TEXT NOT NULL,
    symbol VARCHAR(6) NOT NULL,
    requested_start DATE NOT NULL,
    requested_end DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    PRIMARY KEY (source, adjustment, symbol),
    CHECK (requested_start <= requested_end)
);
CREATE INDEX IF NOT EXISTS market_bars_date_idx
    ON market_bars (trade_date, symbol);
'''


class MarketDataError(ValueError):
    pass


def symbol_market(symbol):
    if not isinstance(symbol, str) or not re.fullmatch(r'[0-9]{6}', symbol):
        raise MarketDataError('公开行情仅支持六位沪深股票或 ETF 代码，例如 510300、159915、600000')
    if symbol == '000300':
        return '1'  # 沪深300指数在东方财富/腾讯的上海指数代码
    return '1' if symbol[0] in '569' else '0'


def to_decimal(text):
    try:
        value = Decimal(str(text))
    except (InvalidOperation, ValueError):
        raise MarketDataError('行情接口返回非法价格或成交量')
    if not value.is_finite():
        raise MarketDataError('行情接口返回非有限数值')
    return value


def parse_response(payload, symbol, begin, end):
    if not isinstance(payload, dict) or payload.get('rc') != 0:
        raise MarketDataError('公开行情接口响应异常')
    block = payload.get('data')
    if not isinstance(block, dict) or not isinstance(block.get('klines'), list) or not block['klines']:
        raise MarketDataError(symbol + ' 在所选日期没有可用行情；请检查代码、上市时间或接口状态')
    output, seen = [], set()
    for line in block['klines']:
        cells = line.split(',') if isinstance(line, str) else []
        if len(cells) < 6:
            raise MarketDataError(symbol + ' 的行情列不完整')
        try:
            day = date.fromisoformat(cells[0])
        except ValueError:
            raise MarketDataError(symbol + ' 的行情日期无效')
        if not begin <= day <= end or day in seen:
            raise MarketDataError(symbol + ' 的行情日期越界或重复')
        seen.add(day)
        opening, closing, high, low, volume = map(to_decimal, cells[1:6])
        if min(opening, closing, high, low) <= 0 or volume < 0 or low > min(opening, closing) or high < max(opening, closing):
            raise MarketDataError(symbol + ' 的 OHLC/成交量不合理')
        output.append((symbol, day, opening, high, low, closing, volume))
    output.sort(key=lambda row: row[1])
    return output


def fetch_eastmoney(symbol, begin, end, *, opener=urlopen, sleeper=time.sleep):
    params = {'secid': symbol_market(symbol) + '.' + symbol,
              'fields1': 'f1,f2,f3,f4,f5,f6',
              'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
              'ut': '7eea3edcaed734bea9cbfc24409ed989',
              'klt': '101', 'fqt': '0' if symbol == '000300' else '1', 'beg': begin.strftime('%Y%m%d'),
              'end': end.strftime('%Y%m%d')}
    request = Request(API_URL + '?' + urlencode(params), headers={
        'User-Agent': 'Mozilla/5.0 StrategyLab/0.2',
        'Referer': 'https://quote.eastmoney.com/'})
    last_error = None
    for attempt in range(3):
        try:
            with opener(request, timeout=10) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise MarketDataError('公开行情响应超过 8 MB')
            return parse_response(json.loads(raw.decode('utf-8')), symbol, begin, end)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 2:
                sleeper(0.5 * (attempt + 1))
    raise MarketDataError(symbol + ' 行情拉取失败：' + str(last_error)[:200])


def fetch_tencent(symbol, begin, end, *, opener=urlopen, sleeper=time.sleep):
    """Tencent daily qfq fallback; yearly requests avoid its 640-bar response limit."""
    prefix = 'sh' if symbol_market(symbol) == '1' else 'sz'
    code = prefix + symbol
    by_day = {}
    for year in range(begin.year, end.year + 1):
        adjust = '' if symbol == '000300' else 'qfq'
        params = {'_var': 'kline_day' + adjust + str(year),
                  'param': f'{code},day,{year}-01-01,{year + 1}-12-31,640,{adjust}',
                  'r': '0.8205512681390605'}
        request = Request(TENCENT_URL + '?' + urlencode(params), headers={
            'User-Agent': 'Mozilla/5.0 StrategyLab/0.2',
            'Referer': 'https://gu.qq.com/'})
        last_error = None
        for attempt in range(3):
            try:
                with opener(request, timeout=10) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise MarketDataError('腾讯行情响应超过 8 MB')
                marker = raw.find(b'={')
                if marker < 0:
                    raise MarketDataError('腾讯行情响应格式异常')
                payload = json.loads(raw[marker + 1:].decode('utf-8'))
                if payload.get('code') != 0:
                    raise MarketDataError('腾讯行情接口响应异常')
                block = payload.get('data', {}).get(code, {})
                lines = block.get('day' if symbol == '000300' else 'qfqday')
                if not isinstance(lines, list):
                    raise MarketDataError(symbol + ' 没有腾讯日线')
                for cells in lines:
                    if not isinstance(cells, list) or len(cells) < 6:
                        raise MarketDataError(symbol + ' 的腾讯行情列不完整')
                    day = date.fromisoformat(cells[0])
                    if not begin <= day <= end:
                        continue
                    opening, closing, high, low, volume = map(to_decimal, cells[1:6])
                    if min(opening, closing, high, low) <= 0 or volume < 0 or low > min(opening, closing) or high < max(opening, closing):
                        raise MarketDataError(symbol + ' 的腾讯 OHLC/成交量不合理')
                    row = (symbol, day, opening, high, low, closing, volume)
                    if day in by_day and by_day[day] != row:
                        raise MarketDataError(symbol + ' 的腾讯复权行情在重叠年份不一致')
                    by_day[day] = row
                break
            except (HTTPError, URLError, TimeoutError, OSError, UnicodeError,
                    json.JSONDecodeError, ValueError) as error:
                last_error = error
                if attempt < 2:
                    sleeper(0.5 * (attempt + 1))
        else:
            raise MarketDataError(symbol + ' 腾讯行情拉取失败：' + str(last_error)[:200])
    if not by_day:
        raise MarketDataError(symbol + ' 在腾讯接口没有可用行情')
    return [by_day[day] for day in sorted(by_day)]


def warmup_start(strategy):
    if not strategy.get('start') or not strategy.get('end'):
        raise MarketDataError('真实行情回测必须设置开始日期和结束日期')
    start, end = date.fromisoformat(strategy['start']), date.fromisoformat(strategy['end'])
    if end > datetime.now(timezone(timedelta(hours=8))).date():
        raise MarketDataError('结束日期不能超过今天（北京时间）')
    lookback = 2
    for spec in strategy['indicators'].values():
        if spec['kind'] == 'macd':
            lookback = max(lookback, spec.get('slow', 26) + spec.get('signal', 9))
        else:
            lookback = max(lookback, spec.get('period', 14) + 1)
    return start - timedelta(days=max(90, lookback * 2 + 60)), end


def connect_db(dsn=None):
    try:
        import psycopg
    except ImportError:
        raise MarketDataError('缺少 PostgreSQL 驱动：请运行 pip install -e ".[market]"')
    try:
        configured_dsn = dsn or os.environ.get('STRATEGYLAB_DATABASE_URL')
        if configured_dsn:
            return psycopg.connect(configured_dsn, connect_timeout=5, autocommit=True)
        if os.environ.get('STRATEGYLAB_DB_HOST'):
            return psycopg.connect(host=os.environ['STRATEGYLAB_DB_HOST'],
                                   port=os.environ.get('STRATEGYLAB_DB_PORT', '5432'),
                                   dbname=os.environ.get('STRATEGYLAB_DB_NAME', 'strategy_lab'),
                                   user=os.environ.get('STRATEGYLAB_DB_USER', 'strategy_lab'),
                                   password=os.environ.get('STRATEGYLAB_DB_PASSWORD'),
                                   connect_timeout=5, autocommit=True)
        return psycopg.connect(DEFAULT_DSN, connect_timeout=5, autocommit=True)
    except psycopg.Error as error:
        raise MarketDataError('PostgreSQL 连接失败：请先运行 docker compose up -d，并检查 STRATEGYLAB_DATABASE_URL；' + str(error).splitlines()[0][:180])


def ensure_schema(conn):
    for statement in SCHEMA.split(';'):
        if statement.strip():
            conn.execute(statement)
    if not conn.autocommit:
        conn.commit()


def load_market(strategy, *, provider=None, connection=None, now=None):
    """Return engine-ready CSV plus provenance. No synthetic fallback on failure."""
    symbols = sorted(set(strategy['universe']) | {strategy['benchmark']})
    if len(symbols) > 100:
        raise MarketDataError('单次公开行情查询最多 100 个代码（含基准）')
    for symbol in symbols:
        symbol_market(symbol)
    begin, end = warmup_start(strategy)
    owned = connection is None
    conn = connection or connect_db()
    current = now or datetime.now(timezone.utc)
    providers = {'eastmoney': provider} if provider is not None else {
        'eastmoney': fetch_eastmoney, 'tencent': fetch_tencent}
    fetched, cached, selected = [], [], {}
    try:
        ensure_schema(conn)
        for symbol in symbols:
            adjustment = 'raw' if symbol == '000300' else ADJUSTMENT
            with conn.transaction():
                conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',
                             (adjustment + ':' + symbol,))
                coverage = {row[0]: row[1:] for row in conn.execute('''
                    SELECT source, requested_start, requested_end, fetched_at
                    FROM market_coverage WHERE adjustment=%s AND symbol=%s
                    AND source = ANY(%s)''', (adjustment, symbol, list(providers))).fetchall()}
                for source in providers:
                    row = coverage.get(source)
                    if row and row[0] <= begin and row[1] >= end and current - row[2] < timedelta(hours=24):
                        cached.append(symbol)
                        selected[symbol] = source
                        break
                if symbol in selected:
                    continue
                failures = []
                for source, fetch in providers.items():
                    row = coverage.get(source)
                    fetch_start = min(begin, row[0]) if row else begin
                    fetch_end = max(end, row[1]) if row else end
                    try:
                        bars = fetch(symbol, fetch_start, fetch_end)
                        if not bars:
                            raise MarketDataError(symbol + ' 的公开行情为空')
                    except MarketDataError as error:
                        failures.append(source + ': ' + str(error))
                        continue
                    with conn.cursor() as cursor:
                        cursor.executemany('''INSERT INTO market_bars
                            (source, adjustment, symbol, trade_date, open, high, low, close, volume, fetched_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (source, adjustment, symbol, trade_date) DO UPDATE SET
                            open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                            close=EXCLUDED.close, volume=EXCLUDED.volume, fetched_at=EXCLUDED.fetched_at''',
                            [(source, adjustment, *bar, current) for bar in bars])
                    conn.execute('''INSERT INTO market_coverage
                        (source, adjustment, symbol, requested_start, requested_end, fetched_at, row_count)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source, adjustment, symbol) DO UPDATE SET
                        requested_start=EXCLUDED.requested_start, requested_end=EXCLUDED.requested_end,
                        fetched_at=EXCLUDED.fetched_at, row_count=EXCLUDED.row_count''',
                        (source, adjustment, symbol, fetch_start, fetch_end, current, len(bars)))
                    fetched.append(symbol)
                    selected[symbol] = source
                    break
                if symbol not in selected:
                    raise MarketDataError(symbol + ' 无法补齐行情；' + '；'.join(failures))
        rows = []
        for symbol, source in selected.items():
            rows.extend(conn.execute('''SELECT symbol, trade_date, open, high, low, close, volume
                FROM market_bars WHERE source=%s AND adjustment=%s AND symbol=%s
                AND trade_date BETWEEN %s AND %s''',
                (source, 'raw' if symbol == '000300' else ADJUSTMENT, symbol, begin, end)).fetchall())
        rows.sort(key=lambda row: (row[1], row[0]))
        by_symbol = {symbol: 0 for symbol in symbols}
        for row in rows:
            if strategy['start'] <= row[1].isoformat() <= strategy['end']:
                by_symbol[row[0]] += 1
        if not rows or any(not count for count in by_symbol.values()):
            raise MarketDataError('指定区间内至少一只资产没有行情：' + ', '.join(s for s, count in by_symbol.items() if not count))
        if len(rows) > 100000:
            raise MarketDataError('查询结果超过 100,000 行；请缩小日期或资产范围')
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
        for symbol, day, opening, high, low, closing, volume in rows:
            writer.writerow([day.isoformat(), symbol, opening, high, low, closing, volume])
        adjustments = {symbol: 'raw' if symbol == '000300' else ADJUSTMENT for symbol in symbols}
        return out.getvalue(), {'provider': list(set(selected.values()))[0] if len(set(selected.values())) == 1 else 'mixed',
                'symbol_providers': selected, 'symbol_adjustments': adjustments,
                'adjustment': list(set(adjustments.values()))[0] if len(set(adjustments.values())) == 1 else 'mixed',
                'requested_start': strategy['start'], 'requested_end': strategy['end'],
                'warmup_start': begin.isoformat(), 'fetched_symbols': fetched,
                'cached_symbols': cached, 'rows': len(rows), 'checked_at': current.isoformat()}
    except Exception as error:
        if isinstance(error, MarketDataError):
            raise
        try:
            import psycopg
            if isinstance(error, psycopg.Error):
                raise MarketDataError('PostgreSQL 查询或写入失败：' + str(error).splitlines()[0][:180]) from error
        except ImportError:
            pass
        raise
    finally:
        if owned:
            conn.close()

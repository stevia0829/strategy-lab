"""Market parser and PostgreSQL cache behavior without relying on a live quote service."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from strategylab.market import (MarketDataError, fetch_eastmoney, fetch_tencent, load_market,
                                parse_response, symbol_market)


class ParserTests(unittest.TestCase):
    def test_market_codes_and_adjusted_daily_request(self):
        self.assertEqual(symbol_market('510300'), '1')
        self.assertEqual(symbol_market('000300'), '1')
        self.assertEqual(symbol_market('159915'), '0')
        with self.assertRaises(MarketDataError):
            symbol_market('DEMO_EQ')
        requests = []

        def open_fixture(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(json.dumps({'rc': 0, 'data': {'klines': [
                '2024-01-02,3.2,3.1,3.3,3.0,12345,0,0,0,0,0'
            ]}}).encode())

        bars = fetch_eastmoney('510300', date(2024, 1, 1), date(2024, 1, 3),
                               opener=open_fixture)
        self.assertEqual(bars[0][3], Decimal('3.3'))
        params = parse_qs(urlsplit(requests[0][0].full_url).query)
        self.assertEqual((params['secid'], params['klt'], params['fqt']),
                         (['1.510300'], ['101'], ['1']))
        self.assertEqual(requests[0][1], 10)

    def test_invalid_or_duplicate_prices_fail_closed(self):
        payload = {'rc': 0, 'data': {'klines': [
            '2024-01-02,3.2,3.1,3.3,3.0,12345'
        ]}}
        for value in ('NaN', '-1', '4'):
            payload['data']['klines'][0] = f'2024-01-02,3.2,3.1,3.3,{value},12345'
            with self.assertRaises(MarketDataError):
                parse_response(payload, '510300', date(2024, 1, 1), date(2024, 1, 3))
        payload['data']['klines'] = ['2024-01-02,3.2,3.1,3.3,3.0,12345'] * 2
        with self.assertRaises(MarketDataError):
            parse_response(payload, '510300', date(2024, 1, 1), date(2024, 1, 3))

    def test_tencent_adjusted_daily_response(self):
        requests = []

        def open_fixture(request, timeout):
            requests.append(request.full_url)
            payload = {'code': 0, 'data': {'sh510300': {'qfqday': [
                ['2024-01-02', '3.2', '3.1', '3.3', '3.0', '12345']
            ]}}}
            return io.BytesIO(('kline_dayqfq2024=' + json.dumps(payload)).encode())

        bars = fetch_tencent('510300', date(2024, 1, 1), date(2024, 1, 3),
                             opener=open_fixture)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0][5], Decimal('3.1'))
        self.assertIn('sh510300,day,2024-01-01,2025-12-31,640,qfq',
                      parse_qs(urlsplit(requests[0]).query)['param'])

    def test_index_uses_unadjusted_daily_response(self):
        requests = []
        def open_fixture(request, timeout):
            requests.append(request.full_url)
            payload = {'code': 0, 'data': {'sh000300': {'day': [
                ['2024-01-02', '3400', '3410', '3420', '3390', '12345']
            ]}}}
            return io.BytesIO(('kline_day2024=' + json.dumps(payload)).encode())
        bars = fetch_tencent('000300', date(2024, 1, 1), date(2024, 1, 3), opener=open_fixture)
        self.assertEqual(bars[0][5], Decimal('3410'))
        self.assertIn('sh000300,day,2024-01-01,2025-12-31,640,',
                      parse_qs(urlsplit(requests[0]).query)['param'])


@unittest.skipUnless(os.environ.get('STRATEGYLAB_TEST_DATABASE_URL'),
                     'set STRATEGYLAB_TEST_DATABASE_URL for PostgreSQL integration')
class PostgresCacheTests(unittest.TestCase):
    def test_fetch_cache_and_extend_range(self):
        import psycopg
        from psycopg import sql

        dsn = os.environ['STRATEGYLAB_TEST_DATABASE_URL']
        schema = 'test_market_' + uuid4().hex
        admin = psycopg.connect(dsn, autocommit=True)
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        conn = psycopg.connect(dsn, autocommit=True,
                               options='-c search_path=' + schema)
        try:
            strategy = json.loads((ROOT / 'examples/buy_hold.json').read_text())
            strategy.update(universe=['510300'], benchmark='510300',
                            start='2024-01-02', end='2024-01-05')
            calls = []

            def provider(symbol, begin, end):
                calls.append((symbol, begin, end))
                rows = []
                day = begin
                while day <= end:
                    price = Decimal('3.0')
                    rows.append((symbol, day, price, price, price, price,
                                 Decimal('100')))
                    day += timedelta(days=1)
                return rows

            clock = datetime(2024, 2, 1, tzinfo=timezone.utc)
            first, meta = load_market(strategy, provider=provider,
                                      connection=conn, now=clock)
            self.assertEqual(meta['fetched_symbols'], ['510300'])
            self.assertEqual(meta['cached_symbols'], [])
            self.assertIn('2024-01-02,510300,3.000000', first)

            def must_not_fetch(*args):
                raise AssertionError('fresh coverage should come from PostgreSQL')

            second, meta = load_market(strategy, provider=must_not_fetch,
                                       connection=conn, now=clock + timedelta(hours=1))
            self.assertEqual(meta['cached_symbols'], ['510300'])
            self.assertEqual(first, second)

            strategy['end'] = '2024-01-08'
            third, meta = load_market(strategy, provider=provider,
                                      connection=conn, now=clock + timedelta(hours=2))
            self.assertEqual(meta['fetched_symbols'], ['510300'])
            self.assertEqual(len(calls), 2)
            self.assertIn('2024-01-08,510300,3.000000', third)
            self.assertEqual(conn.execute('SELECT count(*) FROM market_bars').fetchone()[0],
                             meta['rows'])

            with patch('strategylab.market.fetch_eastmoney',
                       side_effect=MarketDataError('primary disconnected')), \
                 patch('strategylab.market.fetch_tencent', side_effect=provider):
                _, meta = load_market(strategy, connection=conn,
                                      now=clock + timedelta(hours=27))
            self.assertEqual(meta['symbol_providers'], {'510300': 'tencent'})
            self.assertEqual(meta['fetched_symbols'], ['510300'])

            with patch('strategylab.market.fetch_eastmoney', side_effect=must_not_fetch), \
                 patch('strategylab.market.fetch_tencent', side_effect=must_not_fetch):
                _, meta = load_market(strategy, connection=conn,
                                      now=clock + timedelta(hours=28))
            self.assertEqual(meta['cached_symbols'], ['510300'])
            self.assertEqual(meta['symbol_providers'], {'510300': 'tencent'})
        finally:
            conn.close()
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            admin.close()


if __name__ == '__main__':
    unittest.main()

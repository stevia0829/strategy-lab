"""Persistent backtest records, including strategy generation turns but no API credentials."""
import uuid

from strategylab.market import connect_db

SCHEMA = '''
CREATE TABLE IF NOT EXISTS backtest_runs (
  run_id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  strategy_name TEXT NOT NULL,
  engine TEXT NOT NULL,
  data_source TEXT NOT NULL,
  strategy_mode TEXT NOT NULL,
  total_return DOUBLE PRECISION,
  max_drawdown DOUBLE PRECISION,
  payload JSONB NOT NULL
)
'''


def save_run(bundle):
    try:
        from psycopg.types.json import Jsonb
    except ImportError:
        raise ValueError('历史记录需要 PostgreSQL 驱动 psycopg；本次回测报告仍可下载') from None
    run_id = str(uuid.uuid4())
    with connect_db() as conn:
        conn.execute(SCHEMA)
        conn.execute('''INSERT INTO backtest_runs
                    (run_id, strategy_name, engine, data_source, strategy_mode,
                     total_return, max_drawdown, payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (run_id, bundle['strategy']['name'], bundle['result']['engine'],
                      bundle['source'], bundle['strategy_mode'],
                      bundle['result']['metrics']['total_return'],
                      bundle['result']['metrics']['max_drawdown'],
                      Jsonb(bundle)))
    return run_id


def list_runs():
    with connect_db() as conn:
        conn.execute(SCHEMA)
        rows = conn.execute('''SELECT run_id::text, created_at, strategy_name, engine,
                              data_source, strategy_mode, total_return, max_drawdown
                              FROM backtest_runs ORDER BY created_at DESC LIMIT 100''').fetchall()
    return [{'id': r[0], 'created_at': r[1].isoformat(), 'strategy_name': r[2],
             'engine': r[3], 'source': r[4], 'strategy_mode': r[5],
             'total_return': r[6], 'max_drawdown': r[7]} for r in rows]


def get_run(run_id):
    try:
        normalized = str(uuid.UUID(run_id))
    except ValueError:
        raise ValueError('无效的回测记录编号')
    with connect_db() as conn:
        conn.execute(SCHEMA)
        row = conn.execute('SELECT payload FROM backtest_runs WHERE run_id=%s', (normalized,)).fetchone()
    if not row:
        return None
    return {**row[0], 'run_id': normalized}

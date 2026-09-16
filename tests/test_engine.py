import copy
import csv
import io
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'python'))
sys.path.insert(0,str(ROOT))
from strategylab.engine import run, indicator, evaluate, validate, read_csv
from strategylab.compare import compare
from server import run_engine


def config():
    s=json.loads((ROOT/'examples/buy_hold.json').read_text())
    s['universe']=['A'];s['benchmark']='A';s.pop('start');s.pop('end')
    s['execution'].update(initial_cash=1000,commission_rate=0,min_commission=0,slippage=0,lot_size=1)
    return s


def bars_csv(prices, extra=None):
    out=io.StringIO();w=csv.writer(out);w.writerow(['date','symbol','open','high','low','close','volume','limit_up','limit_down'])
    for i,(opening,close) in enumerate(prices):
        row=['2024-01-%02d'%(i+1),'A',opening,max(opening,close),min(opening,close),close,100000,0,0]
        if extra: extra(i,row)
        w.writerow(row)
    return out.getvalue()


class IndicatorTests(unittest.TestCase):
    def bars(self,values):
        return [dict(open=v,high=v+1,low=v-1,close=v,volume=100) for v in values]

    def test_wilder_rsi_warmup_and_flat(self):
        self.assertEqual(indicator(self.bars([10]*20),{'kind':'rsi','period':14}),[None]*14+[50]*6)
        self.assertEqual(indicator(self.bars(range(10,30)),{'kind':'rsi','period':14})[-1],100)
        self.assertEqual(indicator(self.bars(range(30,10,-1)),{'kind':'rsi','period':14})[-1],0)
        result=indicator(self.bars([10,11,10,12,11]),{'kind':'rsi','period':2})
        self.assertAlmostEqual(result[2],50)
        self.assertAlmostEqual(result[3],83.33333333333333)
        self.assertAlmostEqual(result[4],50)

    def test_sma_seeded_ema_and_atr(self):
        b=self.bars([10,11,12,13])
        self.assertEqual(indicator(b,{'kind':'ema','period':3}),[None,None,11,12])
        self.assertEqual(indicator(b,{'kind':'sma','period':3}),[None,None,11,12])
        self.assertEqual(indicator(b,{'kind':'atr','period':3}),[None,None,2,2])

    def test_macd_signal_warmup(self):
        r=indicator(self.bars(range(10,55)),{'kind':'macd','fast':12,'slow':26,'signal':9})
        self.assertTrue(all(v is None for v in r[:33]))
        self.assertAlmostEqual(r[33],0,places=12)

    def test_momentum_existing_numpy_golden(self):
        values=[1,1.02,1.01,1.04,1.03,1.07,1.06,1.10,1.09,1.13,1.12,1.16,1.15,1.20,1.18,1.23,1.22,1.27,1.25,1.31,1.29]
        self.assertAlmostEqual(indicator(self.bars(values),{'kind':'momentum_score','period':21})[-1],29.14087848599015,places=10)

    def test_rules_crossing_and_three_valued_logic(self):
        series={'x':[None,0,1,1,-1]}
        condition={'left':'x','op':'gt','right':0}
        self.assertIsNone(evaluate({'not':condition},series,0))
        self.assertFalse(evaluate({'all':[False,condition]},series,0))
        self.assertTrue(evaluate({'any':[True,condition]},series,0))
        cross=dict(condition,op='cross_above')
        self.assertTrue(evaluate(cross,series,2));self.assertFalse(evaluate(cross,series,3))
        self.assertTrue(evaluate(dict(condition,op='cross_below'),series,4))

    def test_all_indicators_are_prefix_causal(self):
        b=self.bars([20+math.sin(i*.2)+i*.03 for i in range(100)])
        for kind in ('sma','ema','rsi','macd','roc','momentum_score','atr','highest','lowest'):
            spec={'kind':kind,'period':14}
            long=indicator(b,spec);short=indicator(b[:60],spec)
            self.assertEqual(long[:60],short,kind)


class ReplayTests(unittest.TestCase):
    def test_next_open_daily_mtm_and_recovery(self):
        r=run(config(),bars_csv([(10,10),(20,20),(20,10),(30,30)]))
        self.assertEqual(len(r['fills']),1)
        f=r['fills'][0];self.assertEqual((f['signal_date'],f['date'],f['price'],f['quantity']),('2024-01-01','2024-01-02',20,50))
        self.assertEqual([p['equity'] for p in r['equity']],[1000,1000,500,1500])
        self.assertAlmostEqual(r['metrics']['max_drawdown'],.5)
        self.assertEqual(r['metrics']['max_drawdown_recovery_days'],2)
        self.assertEqual(r['metrics']['closed_trades'],0)
        self.assertIsNone(r['metrics']['win_rate'])

    def test_fee_slippage_lots_no_cash_borrowing(self):
        s=config();s['execution'].update(commission_rate=.01,min_commission=5,slippage=.01,lot_size=10)
        r=run(s,bars_csv([(10,10),(10,10)]));f=r['fills'][0]
        self.assertEqual(f['quantity'],90);self.assertAlmostEqual(f['price'],10.1)
        self.assertAlmostEqual(f['fee'],9.09)
        self.assertAlmostEqual(r['equity'][-1]['cash'],81.91)
        self.assertAlmostEqual(r['metrics']['total_costs'],18.09)

    def test_exit_precedence_and_no_final_bar_fill(self):
        s=config();s['exit']={'left':'close','op':'lt','right':15}
        r=run(s,bars_csv([(20,20),(20,20),(20,10),(12,12)]))
        self.assertEqual([f['side'] for f in r['fills']],['buy','sell'])
        self.assertEqual(r['fills'][-1]['signal_date'],'2024-01-03')
        self.assertEqual(len(run(config(),bars_csv([(10,10)]))['fills']),0)

    def test_insufficient_cash_zero_exposure_and_blocked_exit(self):
        s=config();s['execution']['max_exposure']=0
        self.assertEqual(run(s,bars_csv([(10,10),(10,10)]))['fills'],[])
        s=config();s['exit']={'left':'close','op':'gt','right':15}
        data=bars_csv([(10,10),(10,20),(10,10)],lambda i,row:row.__setitem__(8,10) if i==2 else None)
        r=run(s,data)
        self.assertEqual(r['rejected'][-1]['reason'],'limit_down')
        self.assertIn('A',r['equity'][-1]['positions'])

    def test_missing_bar_preserves_value_with_explicit_flag(self):
        s=config();s['benchmark']='B'
        data=bars_csv([(10,10),(10,10),(10,10),(10,10)])
        lines=data.splitlines();rows=[lines[0]]+[line.replace(',A,',',B,') for line in lines[1:]]+[line for line in lines[1:] if not line.startswith('2024-01-03')]
        r=run(s,'\n'.join(rows)+'\n')
        self.assertEqual(r['equity'][2]['stale_symbols'],['A'])
        self.assertEqual(r['equity'][2]['equity'],1000)

    def test_warmup_before_start_no_prestart_position(self):
        s=config();s['start']='2024-01-03'
        r=run(s,bars_csv([(10,10),(20,20),(30,30)]))
        self.assertEqual(r['fills'][0]['date'],'2024-01-03')
        self.assertEqual(r['fills'][0]['signal_date'],'2024-01-02')
        self.assertEqual(r['fills'][0]['quantity'],33)

    def test_csv_rejects_duplicate_nonfinite_ohlc(self):
        text=bars_csv([(10,10)])
        for invalid in (text+text.splitlines()[1]+'\n',text.replace(',10,',',nan,',1),text.replace(',10,10,10,10,',',10,9,10,10,')):
            with self.assertRaises(ValueError):read_csv(invalid)

    def test_config_rejects_unknown_rules_and_noninteger_periods(self):
        for mutate in (lambda s:s.update(unknown=1),lambda s:s.update(entry={'left':'future_close','op':'gt','right':0}),lambda s:s['indicators'].update(x={'kind':'rsi','period':14.5}),lambda s:s.update(entry={'not':{'foo':'bar'}})):
            s=config();mutate(s)
            with self.assertRaises(ValueError):validate(s)


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'bin/strategy-lab').exists():
            subprocess.run(['go','build','-o','bin/strategy-lab','./cmd/strategy-lab'],cwd=ROOT,check=True)

    def parity(self,s,data):
        result=compare(run_engine('go',s,data),run(s,data))
        self.assertTrue(result['match'],result['differences'])

    def test_all_presets_daily_orders_and_metrics(self):
        data=(ROOT/'examples/demo.csv').read_text()
        for path in sorted((ROOT/'examples').glob('*.json')):
            with self.subTest(path=path.name):self.parity(json.loads(path.read_text()),data)

    def test_edge_cases_across_both_engines(self):
        for costs in (False,True):
            s=config()
            if costs:s['execution'].update(commission_rate=.01,min_commission=5,slippage=.01,lot_size=10)
            for data in (bars_csv([(10,10)]),bars_csv([(10,10)]*5),bars_csv([(10,10),(20,20),(20,10),(30,30)])):
                self.parity(s,data)

    def test_seeded_random_strategies_across_indicators(self):
        rng=random.Random(90210);out=io.StringIO();w=csv.writer(out);w.writerow(['date','symbol','open','high','low','close','volume'])
        from datetime import date,timedelta
        prices={'A':25,'B':30,'C':45}
        for i in range(170):
            for c in prices:
                op=prices[c]*(1+rng.uniform(-.012,.012));cl=op*(1+rng.uniform(-.035,.035));prices[c]=cl
                w.writerow([(date(2024,1,1)+timedelta(days=i)).isoformat(),c,op,max(op,cl)*1.005,min(op,cl)*.995,cl,100000])
        for kind in ('sma','ema','rsi','macd','roc','momentum_score','atr','highest','lowest'):
            s=config();s['universe']=['A','B','C'];s['indicators']={'x':{'kind':kind,'period':7}}
            threshold=50 if kind=='rsi' else 0 if kind in ('macd','roc','momentum_score') else 30
            s['entry']={'left':'x','op':'gt','right':threshold};s['exit']={'left':'x','op':'cross_below','right':threshold}
            s['selection'].update(max_positions=2,rank_by='x',mode='rotate');s['execution'].update(initial_cash=100000,commission_rate=.0003,min_commission=5,slippage=.0005,lot_size=100,max_exposure=.8)
            with self.subTest(kind=kind):self.parity(s,out.getvalue())

    def test_diff_reports_actual_path(self):
        r=run(config(),bars_csv([(10,10),(10,10)]));other=copy.deepcopy(r);other['equity'][1]['equity']+=1
        result=compare(r,other)
        self.assertFalse(result['match']);self.assertEqual(result['differences'][0]['path'],'result.equity[1].equity')


if __name__=='__main__':unittest.main()

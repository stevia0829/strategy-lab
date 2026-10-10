"""Independent ledger audit catches report/accounting drift."""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from strategylab.engine import run
from research.audit_report import audit


class ReportAuditTests(unittest.TestCase):
    def test_demo_report_reconciles_and_tampering_fails(self):
        strategy = json.loads((ROOT / 'examples/buy_hold.json').read_text())
        bars = ROOT / 'examples/demo.csv'
        report = run(strategy, bars.read_text())
        self.assertEqual(audit(strategy, bars, report)['sessions'], len(report['equity']))
        report['equity'][-1]['cash'] += 10
        with self.assertRaisesRegex(AssertionError, 'cash'):
            audit(strategy, bars, report)


if __name__ == '__main__':
    unittest.main()

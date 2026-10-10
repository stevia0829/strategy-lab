"""Known-answer checks for the user-supplied JQ B signal adapter."""

from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from strategylab.engine import indicator


def load_adapter():
    spec = importlib.util.spec_from_file_location(
        'jq_rotation_guard_b', ROOT / 'examples/jq_rotation_guard_b.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JQRotationGuardBTests(unittest.TestCase):
    def test_user_momentum_formula_matches_engine_known_prices(self):
        module = load_adapter()
        prices = [1.0 + i * 0.015 + (i % 3) * 0.002 for i in range(21)]
        expected = module.momentum_score(prices)
        actual = indicator([{'close': price} for price in prices],
                           {'kind': 'momentum_score', 'period': 21})[-1]
        self.assertAlmostEqual(actual, expected, places=12)

    def test_steady_momentum_wins_and_missing_bar_is_not_tradable(self):
        module = load_adapter()
        days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat()
                for i in range(120)]
        history = {}
        for code in {item[:6] for item in module.ETF_POOL} | {'000300'}:
            history[code] = [
                {'date': day, 'close': 1.002 ** i if code == '518880' else 1.0,
                 'volume': 1000} for i, day in enumerate(days)]
        ctx = {'date': days[-1], 'history': history, 'positions': {}}
        self.assertEqual(module.decide(ctx), ['518880'])
        # Sina omits paused sessions; signal alignment carries the last close
        # while marking that session non-tradable.
        module._last_signal = None
        ctx['history']['518880'] = [bar for bar in history['518880']
                                    if bar['date'] != days[-2]]
        aligned, end = module._aligned_history(ctx)
        self.assertFalse(aligned['518880.XSHG']['tradable'][end - 1])
        self.assertEqual(aligned['518880.XSHG']['close'][end - 1],
                         aligned['518880.XSHG']['close'][end - 2])

    def test_guard_confirmation_uses_trading_day_counts(self):
        module = load_adapter()
        state = {'mode': 'normal', 'bad_days': 0, 'good_days': 0}
        bad = {'churn': 0.5, 'continuation': -0.01, 'groups': 10}
        for _ in range(3):
            state = module.next_guard(state, bad, 'bear', True, True)
        self.assertEqual(state['mode'], 'defensive')
        good = {'churn': 0.1, 'continuation': 0.01, 'groups': 10}
        for _ in range(5):
            state = module.next_guard(state, good, 'bear', True, True)
        self.assertEqual(state['mode'], 'normal')


if __name__ == '__main__':
    unittest.main()

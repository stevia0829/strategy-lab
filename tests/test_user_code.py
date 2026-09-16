"""Custom targets must remain causal and trade at the following open."""
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
sys.path.insert(0, str(ROOT))
from strategylab.engine import run
from agent_codegen import generate
from test_engine import config, bars_csv


class CustomStrategyTests(unittest.TestCase):
    def test_causal_context_and_next_open_fills(self):
        observed = []
        def decide(ctx):
            observed.append((ctx['date'], [b['date'] for b in ctx['history']['A']], dict(ctx['positions'])))
            return ['A'] if ctx['date'] == '2024-01-01' else []
        result = run(config(), bars_csv([(10, 10), (11, 11), (12, 12)]), decide)
        self.assertEqual([(f['date'], f['side']) for f in result['fills']],
                         [('2024-01-02', 'buy'), ('2024-01-03', 'sell')])
        self.assertEqual([len(days) for _, days, _ in observed], [1, 2, 3])
        self.assertTrue(all(all(bar <= day for bar in days) for day, days, _ in observed))
        self.assertIn('A', observed[1][2])

    def test_invalid_targets_fail_before_trading(self):
        for targets in (['A', 'A'], ['UNKNOWN'], 'A'):
            with self.assertRaisesRegex(ValueError, 'decide'):
                run(config(), bars_csv([(10, 10), (11, 11)]), lambda ctx: targets)


class AgentGenerationTests(unittest.TestCase):
    def test_fixed_provider_and_key_not_returned(self):
        captured = []
        def opener(request, timeout):
            captured.append(request)
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'```python\ndef decide(ctx): return []\n```'}}]}).encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'secret-key-123',
                   'prompt':'仅在条件满足时持有沪深300 ETF','model':'deepseek-flash'}
        result = generate(payload, opener=opener)
        self.assertEqual(result['code'], 'def decide(ctx): return []')
        self.assertNotIn(payload['api_key'], str(result))
        self.assertEqual(captured[0].full_url, 'https://api.deepseek.com/chat/completions')
        with self.assertRaisesRegex(ValueError, '模型服务'):
            generate(dict(payload, provider='custom'))


if __name__ == '__main__':
    unittest.main()

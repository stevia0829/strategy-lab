"""Custom targets must remain causal and trade at the following open."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import builtins

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
sys.path.insert(0, str(ROOT))
from strategylab.engine import run
from agent_codegen import generate
from history import save_run
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
    def test_provider_defaults_use_documented_endpoint_and_model(self):
        expected = {
            'deepseek': ('https://api.deepseek.com/chat/completions', 'deepseek-flash'),
            'gpt': ('https://api.openai.com/v1/chat/completions', 'gpt-5.6-sol'),
            'minimax': ('https://api.minimax.io/v1/chat/completions', 'MiniMax-M3'),
            'glm': ('https://open.bigmodel.cn/api/paas/v4/chat/completions', 'glm-5.2'),
            'glm_global': ('https://api.z.ai/api/paas/v4/chat/completions', 'glm-5.3'),
            'kimi': ('https://api.moonshot.cn/v1/chat/completions', 'kimi-k2.6'),
            'kimi_global': ('https://api.moonshot.ai/v1/chat/completions', 'kimi-k3'),
        }
        for provider, (endpoint, model) in expected.items():
            with self.subTest(provider=provider):
                requests = []
                def opener(request, timeout):
                    requests.append(request)
                    return io.BytesIO(json.dumps({'choices':[{'message':{
                        'content':'def decide(ctx): return []'}}]}).encode())
                result = generate({'provider':provider, 'engine':'python',
                                   'api_key':'test-token-only',
                                   'prompt':'按照历史收盘价决定下一交易日持仓'}, opener=opener)
                self.assertEqual(requests[0].full_url, endpoint)
                self.assertEqual(json.loads(requests[0].data)['model'], model)
                self.assertEqual(result['model'], model)

    def test_fixed_provider_and_key_not_returned(self):
        captured = []
        def opener(request, timeout):
            captured.append(request)
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'```python\ndef decide(ctx): return []\n```'}}]}).encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'secret-key-123',
                   'prompt':'仅在条件满足时持有沪深300 ETF','model':'deepseek-flash'}
        result = generate(payload, opener=opener)
        self.assertEqual(result['code'], 'def decide(ctx): return []')
        self.assertEqual(result['skill'], 'strategy-lab-script')
        self.assertNotIn(payload['api_key'], str(result))
        self.assertEqual(captured[0].full_url, 'https://api.deepseek.com/chat/completions')
        sent = json.loads(captured[0].data)
        self.assertIn('Strategy Lab 策略脚本', sent['messages'][0]['content'])
        self.assertNotIn(payload['api_key'], str(sent))
        with self.assertRaisesRegex(ValueError, '模型服务'):
            generate(dict(payload, provider='custom'))

    def test_skill_receives_selected_universe_without_key(self):
        requests = []
        def opener(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'def decide(ctx):\n    return []'}}]}).encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'持有资产池中满足趋势条件的 ETF，否则保持现金',
                   'context':{'universe':['510300','518880'],'benchmark':'000300','max_positions':1}}
        result = generate(payload, opener=opener)
        system = requests[0]['messages'][0]['content']
        self.assertIn('510300, 518880', system)
        self.assertIn('最多持仓 1', system)
        self.assertNotIn(payload['api_key'], system)
        self.assertEqual(len(result['skill_sha256']), 64)
        with self.assertRaisesRegex(ValueError, '资产池'):
            generate(dict(payload, context={'universe':['510300','510300'],
                                            'benchmark':'000300','max_positions':1}), opener=opener)

    def test_invalid_draft_is_not_returned_as_runnable(self):
        def invalid(request, timeout):
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'def decide(ctx):\n    return ['}}]}).encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'使用日线收盘趋势判断是否持有资产池中的 ETF'}
        with self.assertRaisesRegex(ValueError, '语法错误'):
            generate(payload, opener=invalid)


class LocalHistoryTests(unittest.TestCase):
    def test_missing_optional_driver_does_not_crash_backtest_request(self):
        original_import = builtins.__import__
        def without_driver(name, *args, **kwargs):
            if name.startswith('psycopg'):
                raise ImportError('optional driver absent')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_driver):
            with self.assertRaisesRegex(ValueError, '历史记录需要 PostgreSQL 驱动'):
                save_run({})


if __name__ == '__main__':
    unittest.main()

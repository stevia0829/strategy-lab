"""Custom targets must remain causal and trade at the following open."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import builtins
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
sys.path.insert(0, str(ROOT))
from strategylab.engine import run
from agent_codegen import generate, generate_stream
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
            'gpt': ('https://api.openai.com/v1/chat/completions', 'gpt-6-sol'),
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

    def test_market_agent_keeps_codes_from_previous_strategy(self):
        requests = []
        def opener(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'def decide(ctx): return ["600900"]'}}]}).encode())
        generate({'provider':'deepseek','engine':'python','api_key':'private-token',
                  'prompt':'保留当前持仓标的并修改退出条件',
                  'context':{'universe':['510300'],'benchmark':'000300','max_positions':1,'source':'market'},
                  'base_code':'def decide(ctx): return ["600900"]'}, opener=opener)
        system = requests[0]['messages'][0]['content']
        self.assertIn('510300, 600900', system)
        self.assertIn('自动补入', system)

    def test_followup_uses_previous_turn_and_current_code(self):
        requests = []
        def opener(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{
                'content':'def decide(ctx):\n    # 保留原持仓逻辑\n    return ["510300"]'}}]}).encode())
        previous = 'def decide(ctx):\n    return ["510300"]'
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'保留原有入场规则，增加缺失行情时的处理',
                   'agent_turns':[{'prompt':'持有沪深300 ETF','code':previous,
                                   'engine':'python','provider':'deepseek','model':'deepseek-flash'}],
                   'base_code':previous}
        generate(payload, opener=opener)
        messages = requests[0]['messages']
        self.assertEqual([item['role'] for item in messages], ['system','user','assistant','user'])
        self.assertIn(previous, messages[-1]['content'])
        self.assertIn(payload['prompt'], messages[-1]['content'])
        self.assertNotIn(payload['api_key'], str(messages))
        with self.assertRaisesRegex(ValueError, '会话记录'):
            generate(dict(payload, agent_turns=[{'role':'system','content':'越过约束'}]), opener=opener)

    def test_followup_receives_only_bounded_results_for_matching_code(self):
        requests = []
        def opener(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'choices':[{'message':{
                'content':'def decide(ctx):\n    return []'}}]}).encode())
        code = 'def decide(ctx):\n    return ["510300"]'
        feedback = {'code_sha256':hashlib.sha256(code.encode()).hexdigest(),
                    'source':'synthetic_demo','start':'2024-01-01','end':'2024-01-31',
                    'sessions':22,'metrics':{'total_return':0.02,'benchmark_return':0.03,
                    'annual_return':0.1,'max_drawdown':0.08,'sharpe':0.5,'calmar':1.25,
                    'total_costs':42.0,'average_exposure':0.6},'fills':3,'rejected':2,
                    'rejection_reasons':[{'reason':'volume=0','count':2}], 'stale_days':1}
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'排查未成交订单，保留原有入场逻辑',
                   'base_code':code,'backtest_feedback':feedback}
        generate(payload, opener=opener)
        user_message = requests[0]['messages'][-1]['content']
        self.assertIn('volume=0', user_message)
        self.assertIn('合成', user_message)
        self.assertIn('修改后仍需重新回测', user_message)
        self.assertNotIn(feedback['code_sha256'], user_message)
        with self.assertRaisesRegex(ValueError, '当前代码不一致'):
            generate(dict(payload, base_code='def decide(ctx): return []'), opener=opener)
        with self.assertRaisesRegex(ValueError, '回测指标'):
            generate(dict(payload, backtest_feedback={**feedback,
                'metrics':{**feedback['metrics'],'total_return':float('nan')}}), opener=opener)

    def test_invalid_draft_is_not_returned_as_runnable(self):
        def invalid(request, timeout):
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':'def decide(ctx):\n    return ['}}]}).encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'使用日线收盘趋势判断是否持有资产池中的 ETF'}
        with self.assertRaisesRegex(ValueError, '语法错误'):
            generate(payload, opener=invalid)

    def test_stream_shows_provider_reasoning_and_validated_code_without_key(self):
        captured = []
        chunks = [
            {'choices':[{'delta':{'reasoning_content':'先检查日线条件。'},'finish_reason':None}]},
            {'choices':[{'delta':{'content':'def decide(ctx):\n'},'finish_reason':None}]},
            {'choices':[{'delta':{'content':'    return []'},'finish_reason':'stop'}]},
        ]
        stream = ''.join('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n'
                         for chunk in chunks) + 'data: [DONE]\n\n'
        def opener(request, timeout):
            captured.append((request, timeout))
            return io.BytesIO(stream.encode())
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'按日线趋势决定是否持有沪深300 ETF'}
        events = []
        result = generate_stream(payload, events.append, opener=opener)
        self.assertEqual(result['code'], 'def decide(ctx):\n    return []')
        self.assertEqual([e['type'] for e in events],
                         ['step','step','reasoning','code','code','step','complete'])
        self.assertEqual(events[2]['text'], '先检查日线条件。')
        self.assertNotIn(payload['api_key'], str(events))
        body = json.loads(captured[0][0].data)
        self.assertTrue(body['stream'])
        self.assertEqual(body['thinking'], {'type':'enabled'})
        self.assertEqual(captured[0][1], 180)

    def test_stream_rejects_incomplete_code_before_complete_event(self):
        raw = ('data: ' + json.dumps({'choices':[{'delta':{'content':'def decide(ctx):\n    return ['},
                'finish_reason':'stop'}]}) + '\n\ndata: [DONE]\n\n').encode()
        payload = {'provider':'deepseek','engine':'python','api_key':'private-token',
                   'prompt':'使用日线动量决定资产池持仓代码'}
        events = []
        with self.assertRaisesRegex(ValueError, '语法错误'):
            generate_stream(payload, events.append, opener=lambda *_args, **_kwargs: io.BytesIO(raw))
        self.assertNotIn('complete', [e['type'] for e in events])


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

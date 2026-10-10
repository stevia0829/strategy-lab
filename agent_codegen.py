"""Skill-guided, fixed-endpoint code generation; never stores API keys."""
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END

PROVIDERS = {
    'deepseek': ('https://api.deepseek.com/chat/completions', 'deepseek-flash'),
    'gpt': ('https://api.openai.com/v1/chat/completions', 'gpt-6-sol'),
    'minimax': ('https://api.minimax.io/v1/chat/completions', 'MiniMax-M3'),
    'glm': ('https://open.bigmodel.cn/api/paas/v4/chat/completions', 'glm-5.2'),
    'glm_global': ('https://api.z.ai/api/paas/v4/chat/completions', 'glm-5.3'),
    'kimi': ('https://api.moonshot.cn/v1/chat/completions', 'kimi-k2.6'),
    'kimi_global': ('https://api.moonshot.ai/v1/chat/completions', 'kimi-k3'),
}
SKILL_NAME = 'strategy-lab-script'
SKILL_PATH = Path(__file__).resolve().parent / '.agents' / 'skills' / SKILL_NAME / 'SKILL.md'


def skill_instructions():
    source = SKILL_PATH.read_text(encoding='utf-8')
    match = re.match(r'\A---\n.*?\n---\n(.+)\Z', source, flags=re.S)
    if not match:
        raise ValueError('策略生成 Skill 缺少有效说明')
    body = match.group(1).strip()
    if not body or len(body) > 12_000:
        raise ValueError('策略生成 Skill 内容无效')
    return body


def generation_context(payload):
    context = payload.get('context')
    if context is None:
        return ''
    if not isinstance(context, dict):
        raise ValueError('策略上下文格式无效')
    universe = context.get('universe')
    benchmark = context.get('benchmark')
    limit = context.get('max_positions')
    valid_code = lambda value: isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,32}', value)
    if (not isinstance(universe, list) or not 1 <= len(universe) <= 100
            or not all(valid_code(code) for code in universe)
            or len(set(universe)) != len(universe)
            or not valid_code(benchmark)
            or type(limit) is not int or not 1 <= limit <= len(universe)):
        raise ValueError('请先填写有效的资产池、基准和最大持仓数')
    if context.get('source') == 'market':
        from code_symbols import explicit_symbols
        current_code = payload.get('base_code')
        if current_code:
            try:
                referenced = explicit_symbols(current_code, payload['engine'])
            except ValueError:
                referenced = []  # Keep code repair possible when the current draft has a syntax error.
            universe = universe + [symbol for symbol in referenced if symbol not in universe]
        if len(set(universe) | {benchmark}) > 100:
            raise ValueError('本次回测包含超过 100 个代码；请缩小策略或手动资产池范围')
        return ('\n本次回测配置：当前已选资产池 ' + ', '.join(universe) + '；基准 ' + benchmark
                + '；最多持仓 ' + str(limit) + '。真实行情模式可按用户要求使用其他六位沪深股票或 ETF 代码；'
                '回测时会自动补入代码中明确引用的标的。')
    return ('\n本次回测配置：资产池 ' + ', '.join(universe) + '；基准 ' + benchmark
            + '；最多持仓 ' + str(limit) + '。生成的目标代码只能取自资产池。')


def validate_agent_turns(turns):
    if turns is None:
        return []
    if not isinstance(turns, list) or len(turns) > 6:
        raise ValueError('会话记录格式无效或轮次过多')
    checked = []
    total = 0
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != {'prompt', 'code', 'engine', 'provider', 'model'}:
            raise ValueError('会话记录格式无效')
        prompt, code = turn['prompt'], turn['code']
        if (not isinstance(prompt, str) or not 1 <= len(prompt) <= 6000
                or not isinstance(code, str) or not 1 <= len(code.encode()) <= 100_000
                or turn['engine'] not in ('python', 'go')
                or turn['provider'] not in PROVIDERS
                or not isinstance(turn['model'], str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', turn['model'])):
            raise ValueError('会话记录内容无效')
        total += len(prompt.encode()) + len(code.encode())
        checked.append({key: turn[key] for key in ('prompt', 'code', 'engine', 'provider', 'model')})
    if total > 300_000:
        raise ValueError('会话记录过长，请缩短历史轮次')
    return checked


def backtest_feedback(payload, base_code):
    """Accept a small, code-bound result summary for the next generation turn."""
    feedback = payload.get('backtest_feedback')
    if feedback is None:
        return ''
    if not isinstance(feedback, dict) or set(feedback) != {
            'code_sha256', 'source', 'start', 'end', 'sessions', 'metrics',
            'fills', 'rejected', 'rejection_reasons', 'stale_days'}:
        raise ValueError('回测反馈格式无效')
    if not base_code or hashlib.sha256(base_code.encode()).hexdigest() != feedback['code_sha256']:
        raise ValueError('回测反馈与当前代码不一致，请重新载入该次回测')
    if (feedback['source'] not in ('market', 'uploaded', 'synthetic_demo')
            or not all(isinstance(feedback[key], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', feedback[key])
                       for key in ('start', 'end'))
            or any(type(feedback[key]) is not int or not 0 <= feedback[key] <= 1_000_000
                   for key in ('sessions', 'fills', 'rejected', 'stale_days'))):
        raise ValueError('回测反馈摘要无效')
    metrics = feedback['metrics']
    names = ('total_return', 'benchmark_return', 'annual_return', 'max_drawdown',
             'sharpe', 'calmar', 'total_costs', 'average_exposure')
    if not isinstance(metrics, dict) or set(metrics) != set(names):
        raise ValueError('回测指标格式无效')
    if any(value is not None and (type(value) not in (int, float) or
                                  not -1e12 <= value <= 1e12)
           for value in metrics.values()):
        raise ValueError('回测指标数值无效')
    reasons = feedback['rejection_reasons']
    if (not isinstance(reasons, list) or len(reasons) > 8 or
            any(not isinstance(item, dict) or set(item) != {'reason', 'count'} or
                not isinstance(item['reason'], str) or len(item['reason']) > 100 or
                type(item['count']) is not int or not 0 <= item['count'] <= feedback['rejected']
                for item in reasons)):
        raise ValueError('拒单摘要无效')
    summary = {key: feedback[key] for key in ('source', 'start', 'end', 'sessions',
                                               'metrics', 'fills', 'rejected',
                                               'rejection_reasons', 'stale_days')}
    return ('\n以下是当前代码上一次回测的历史结果摘要，仅供诊断本轮修改要求。'
            '先根据成交、拒单和风险指标分析可能原因；不要把历史或合成数据表现当成未来收益保证，'
            '不要未经用户要求自行挑选最优参数。修改后仍需重新回测。\n'
            + json.dumps(summary, ensure_ascii=False, allow_nan=False))


def check_draft(code, engine):
    if engine == 'python':
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            raise ValueError('模型生成的 Python 代码有语法错误：第 ' + str(error.lineno) + ' 行')
        if not any(isinstance(node, ast.FunctionDef) and node.name == 'decide' for node in tree.body):
            raise ValueError('模型没有生成顶层 def decide(ctx) 函数')
    elif not re.search(r'(?m)^\s*package\s+main\s*$', code) or not re.search(
            r'\bfunc\s+Decide\s*\(', code):
        raise ValueError('模型没有生成完整的 Go Decide 策略')


def prepare_generation(payload, *, stream=False):
    provider = payload.get('provider')
    if provider not in PROVIDERS:
        raise ValueError('请选择受支持的模型服务')
    engine = payload.get('engine')
    if engine not in ('python', 'go'):
        raise ValueError('请选择 Python 或 Go')
    key = payload.get('api_key')
    prompt = payload.get('prompt')
    if not isinstance(key, str) or not 8 <= len(key) <= 300 or '\n' in key or '\r' in key:
        raise ValueError('请输入有效的 API Key')
    if not isinstance(prompt, str) or not 10 <= len(prompt) <= 6000:
        raise ValueError('请用 10–6000 字描述策略')
    endpoint, default_model = PROVIDERS[provider]
    model = payload.get('model') or default_model
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', model):
        raise ValueError('模型 ID 格式无效')
    instructions = skill_instructions()
    context = generation_context(payload)
    turns = validate_agent_turns(payload.get('agent_turns'))
    base_code = payload.get('base_code')
    if base_code is not None and (not isinstance(base_code, str) or len(base_code.encode()) > 100_000):
        raise ValueError('上一版策略代码过长')
    feedback = backtest_feedback(payload, base_code)
    if any(turn['engine'] != engine for turn in turns):
        raise ValueError('会话记录的策略语言与当前选择不一致')
    messages = [{'role': 'system', 'content': instructions + context + '\n本次只返回完整的 ' + engine
                 + ' 源代码，不要 Markdown 围栏或解释。'}]
    for turn in turns:
        messages.extend(({'role': 'user', 'content': turn['prompt']},
                         {'role': 'assistant', 'content': turn['code']}))
    current_request = prompt + feedback
    if base_code and base_code.strip():
        current_request = ('请以以下当前策略代码为基线完成本轮要求。未要求修改的规则应保留；'
                           '返回可直接运行的完整代码，并更新中文原理与流程注释。\n当前代码：\n'
                           + base_code + '\n本轮要求：\n' + prompt + feedback)
    messages.append({'role': 'user', 'content': current_request})
    body = {'model': model, 'stream': stream, 'messages': messages}
    if stream and provider == 'deepseek':
        body['thinking'] = {'type': 'enabled'}
    request = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    return request, provider, model, engine, instructions


def finish_generation(code, provider, model, engine, instructions):
    if not isinstance(code, str):
        raise ValueError('模型响应不包含文本代码')
    code = re.sub(r'^<think>[\s\S]*?</think>\s*', '', code.strip())
    match = re.fullmatch(r'```(?:python|go)?\s*([\s\S]*?)\s*```', code, flags=re.I)
    if match:
        code = match.group(1).strip()
    if not code or len(code.encode()) > 100_000:
        raise ValueError('模型返回的代码为空或过长')
    check_draft(code, engine)
    return {'code': code, 'provider': provider, 'model': model, 'engine': engine,
            'skill': SKILL_NAME, 'skill_sha256': hashlib.sha256(instructions.encode()).hexdigest()}


class GenerationState(TypedDict, total=False):
    payload: dict
    stream: bool
    request: Request
    provider: str
    model: str
    engine: str
    instructions: str
    code: str
    result: dict


def _emit(state, event):
    if state['stream']:
        get_stream_writer()(event)


def _read_complete(request, provider, opener):
    try:
        with opener(request, timeout=180) as response:
            raw = response.read(200_001)
    except HTTPError as error:
        raise ValueError(provider + ' 接口返回 HTTP ' + str(error.code) + '；请检查 Key、模型和额度')
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(provider + ' 连接失败：' + str(error)[:160])
    if len(raw) > 200_000:
        raise ValueError('模型输出过长')
    try:
        code = json.loads(raw)['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('模型响应不包含可用代码')
    if not isinstance(code, str):
        raise ValueError('模型响应不包含文本代码')
    return code


def _read_stream(state, opener):
    provider = state['provider']
    code_parts = []
    code_bytes = 0
    reasoning_chars = 0
    reasoning_capped = False
    saw_done = False
    finish_reason = None
    try:
        with opener(state['request'], timeout=180) as response:
            _emit(state, {'type': 'step', 'node': 'generate', 'text': '已连接模型，正在接收流式响应'})
            for raw_line in response:
                if len(raw_line) > 200_000:
                    raise ValueError('模型流式分段过长')
                if not raw_line.startswith(b'data:'):
                    continue
                data = raw_line[5:].strip()
                if data == b'[DONE]':
                    saw_done = True
                    break
                if not data:
                    continue
                try:
                    chunk = json.loads(data)
                except (ValueError, UnicodeError):
                    raise ValueError('模型流式响应格式无效')
                if chunk.get('error'):
                    raise ValueError(provider + ' 返回流式错误')
                choices = chunk.get('choices') or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get('delta') or {}
                reasoning = delta.get('reasoning_content') or ''
                if not isinstance(reasoning, str):
                    raise ValueError('模型推理分段格式无效')
                if reasoning and reasoning_chars < 50_000:
                    visible = reasoning[:50_000 - reasoning_chars]
                    reasoning_chars += len(visible)
                    _emit(state, {'type': 'reasoning', 'node': 'generate', 'text': visible})
                if reasoning and reasoning_chars >= 50_000 and not reasoning_capped:
                    reasoning_capped = True
                    _emit(state, {'type': 'step', 'node': 'generate', 'text': '推理展示已达到长度上限，继续等待代码'})
                content = delta.get('content') or ''
                if not isinstance(content, str):
                    raise ValueError('模型代码分段格式无效')
                if content:
                    code_bytes += len(content.encode())
                    if code_bytes > 100_000:
                        raise ValueError('模型输出的代码过长')
                    code_parts.append(content)
                    _emit(state, {'type': 'code', 'node': 'generate', 'text': content})
                if choice.get('finish_reason'):
                    finish_reason = choice['finish_reason']
                    if finish_reason != 'stop':
                        raise ValueError('模型输出提前结束：' + str(finish_reason))
    except HTTPError as error:
        raise ValueError(provider + ' 接口返回 HTTP ' + str(error.code) + '；请检查 Key、模型和额度')
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(provider + ' 连接失败：' + str(error)[:160])
    if not saw_done and finish_reason != 'stop':
        raise ValueError('模型流式响应未正常结束，请重试')
    if not reasoning_chars:
        _emit(state, {'type': 'step', 'node': 'generate', 'text': '该模型未返回可展示的推理文本'})
    return ''.join(code_parts)


def generation_graph(opener):
    """Prepare -> model -> validate. Only explicit safe events leave graph state."""
    def prepare(state):
        request, provider, model, engine, instructions = prepare_generation(
            state['payload'], stream=state['stream'])
        _emit(state, {'type': 'step', 'node': 'prepare',
                      'text': '输入与资产池已校验，策略脚本 Skill 已载入'})
        return {'request': request, 'provider': provider, 'model': model,
                'engine': engine, 'instructions': instructions}

    def model_call(state):
        code = (_read_stream(state, opener) if state['stream'] else
                _read_complete(state['request'], state['provider'], opener))
        return {'code': code}

    def validate_code(state):
        result = finish_generation(state['code'], state['provider'], state['model'],
                                   state['engine'], state['instructions'])
        _emit(state, {'type': 'step', 'node': 'validate',
                      'text': '代码语法与 decide 入口已校验'})
        _emit(state, {'type': 'complete', 'node': 'validate', 'result': result})
        return {'result': result}

    graph = StateGraph(GenerationState)
    graph.add_node('prepare', prepare)
    graph.add_node('generate', model_call)
    graph.add_node('validate', validate_code)
    graph.add_edge(START, 'prepare')
    graph.add_edge('prepare', 'generate')
    graph.add_edge('generate', 'validate')
    graph.add_edge('validate', END)
    return graph.compile()


def generate(payload, *, opener=urlopen):
    return generation_graph(opener).invoke({'payload': payload, 'stream': False})['result']


def generate_stream(payload, emit, *, opener=urlopen):
    result = None
    for event in generation_graph(opener).stream(
            {'payload': payload, 'stream': True}, stream_mode='custom'):
        emit(event)
        if event['type'] == 'complete':
            result = event['result']
    if result is None:
        raise ValueError('生成流程未正常结束')
    return result

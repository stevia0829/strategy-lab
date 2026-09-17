"""Skill-guided, fixed-endpoint code generation; never stores API keys."""
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROVIDERS = {
    'deepseek': ('https://api.deepseek.com/chat/completions', 'deepseek-flash'),
    'gpt': ('https://api.openai.com/v1/chat/completions', 'gpt-5.6-sol'),
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
    return ('\n本次回测配置：资产池 ' + ', '.join(universe) + '；基准 ' + benchmark
            + '；最多持仓 ' + str(limit) + '。生成的目标代码只能取自资产池。')


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


def generate(payload, *, opener=urlopen):
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
    body = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': instructions + context + '\n本次只返回完整的 ' + engine
         + ' 源代码，不要 Markdown 围栏或解释。'},
        {'role': 'user', 'content': prompt}]}
    request = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with opener(request, timeout=60) as response:
            raw = response.read(200_001)
    except HTTPError as error:
        raise ValueError(provider + ' 接口返回 HTTP ' + str(error.code) + '；请检查 Key、模型和额度')
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(provider + ' 连接失败：' + str(error)[:160])
    if len(raw) > 200_000:
        raise ValueError('模型输出过长')
    try:
        parsed = json.loads(raw)
        code = parsed['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError('模型响应不包含可用代码')
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

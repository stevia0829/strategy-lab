"""Fixed-endpoint, user-key-funded code generation; never stores API keys."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROVIDERS = {
    'deepseek': ('https://api.deepseek.com/chat/completions', 'deepseek-flash'),
    'gpt': ('https://api.openai.com/v1/chat/completions', 'gpt-5.1'),
    'minimax': ('https://api.minimax.io/v1/chat/completions', 'MiniMax-M2.7'),
    'glm': ('https://open.bigmodel.cn/api/paas/v4/chat/completions', 'glm-5.2'),
    'kimi': ('https://api.moonshot.cn/v1/chat/completions', 'kimi-k2.6'),
}


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
    if engine == 'python':
        contract = ("Only return runnable Python source. Define def decide(ctx): returning a list of target symbols. "
                    "ctx is a dict with date, history, positions, cash, equity. history maps symbols to past-and-current OHLCV bar dicts. "
                    "Use from strategylab.engine import indicator for RSI/MACD/SMA. No jqdata. No network or file access. "
                    "Do not use any future bars. Example: def decide(ctx): return ['510300'] if ctx['history']['510300'] else [].")
    else:
        contract = ("Only return runnable Go source with package main and func Decide(ctx engine.Context) []string. "
                    "Import strategylab/engine. Context has Date string, History map[string][]engine.Bar, Positions map[string]int, Cash and Equity float64. "
                    "Use engine.Calculate(bars, engine.Indicator{Kind: \"rsi\", Period: 14}) for indicators. "
                    "No network or file access. No future bars. Return []string of target symbols or nil for cash.")
    body = {'model': model, 'stream': False, 'messages': [
        {'role': 'system', 'content': contract + ' The engine trades targets at the next session open; return code only, without Markdown.'},
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
    return {'code': code, 'provider': provider, 'model': model, 'engine': engine}

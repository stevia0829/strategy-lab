"""Find explicit market symbols in strategy source without executing it."""
import ast
import json
import re


# SSE/SZSE A-share and ETF prefixes; skip six-digit dates and unrelated IDs.
SIX_DIGITS = re.compile(r'[01356][0-9]{5}\Z')
GO_TOKENS = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|`[^`]*`')


def explicit_symbols(code, engine):
    """Return six-digit string literals; dynamic symbol selection still uses the configured pool."""
    if not isinstance(code, str):
        raise ValueError('策略代码必须是文本')
    if engine == 'python':
        try:
            values = (node.value for node in ast.walk(ast.parse(code))
                      if isinstance(node, ast.Constant) and isinstance(node.value, str))
            return sorted({value for value in values if SIX_DIGITS.fullmatch(value)})
        except SyntaxError as error:
            raise ValueError('Python 策略语法错误：' + error.msg) from error
    if engine == 'go':
        values = []
        for match in GO_TOKENS.finditer(code):
            token = match.group()
            if token.startswith('//') or token.startswith('/*'):
                continue
            try:
                value = token[1:-1] if token.startswith('`') else json.loads(token)
            except ValueError:
                continue
            if SIX_DIGITS.fullmatch(value):
                values.append(value)
        return sorted(set(values))
    raise ValueError('未知策略语言')


def include_code_symbols(strategy, code, engine):
    """Expand only the current run's universe; keep dynamic strategies' configured pool."""
    symbols = explicit_symbols(code, engine)
    if not symbols:
        return strategy
    universe = list(strategy['universe'])
    universe.extend(symbol for symbol in symbols if symbol not in universe)
    if len(set(universe) | {strategy['benchmark']}) > 100:
        raise ValueError('本次回测包含超过 100 个代码；请缩小策略或手动资产池范围')
    return {**strategy, 'universe': universe}

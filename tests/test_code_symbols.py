"""Explicit code references expand only the current market backtest universe."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'python'))

from code_symbols import explicit_symbols, include_code_symbols
from strategylab.market import symbol_market


class CodeSymbolTests(unittest.TestCase):
    def test_python_literals_and_go_literals_ignore_comments(self):
        python = "# '600001'\nPAIR = ('600900', '159687', '202609')\ndef decide(ctx):\n    return ['512890']"
        go = '// "600001"\n/* `600002` */\nfunc Decide() []string { return []string{"513100", `600900`} }'
        self.assertEqual(explicit_symbols(python, 'python'), ['159687', '512890', '600900'])
        self.assertEqual(explicit_symbols(go, 'go'), ['513100', '600900'])

    def test_expands_explicit_symbols_and_preserves_dynamic_pool(self):
        strategy = {'universe': ['510300', '518880'], 'benchmark': '000300'}
        code = "def decide(ctx):\n    return ['600900'] if ctx['history']['600900'] else []"
        expanded = include_code_symbols(strategy, code, 'python')
        self.assertEqual(expanded['universe'], ['510300', '518880', '600900'])
        self.assertEqual(strategy['universe'], ['510300', '518880'])
        self.assertIs(include_code_symbols(strategy, 'def decide(ctx): return list(ctx["history"])', 'python'), strategy)

    def test_limit_fails_before_loading_market_data(self):
        strategy = {'universe': [f'{n:06d}' for n in range(100)], 'benchmark': '000300'}
        with self.assertRaisesRegex(ValueError, '超过 100'):
            include_code_symbols(strategy, "def decide(ctx): return ['600900']", 'python')

    def test_requested_shanghai_and_shenzhen_codes_supported(self):
        self.assertEqual([symbol_market(code) for code in ('513100', '600900', '159687', '512890')],
                         ['1', '1', '0', '1'])


if __name__ == '__main__':
    unittest.main()

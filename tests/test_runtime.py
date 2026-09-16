"""Runtime selection must not make Python depend on the Go toolchain."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server


class RuntimeTests(unittest.TestCase):
    def test_python_runs_without_building_or_calling_go(self):
        strategy = json.loads((ROOT/'examples/trend.json').read_text())
        data = (ROOT/'examples/demo.csv').read_bytes().decode('utf-8')
        with patch.object(server, 'ensure_go', side_effect=AssertionError('Python must not need Go')):
            report = server.run_engine('python', strategy, data)
        self.assertEqual(report['engine'], 'python')
        self.assertGreater(len(report['equity']), 0)

    def test_web_startup_never_requires_go(self):
        with patch.object(sys, 'argv', ['server.py']), \
             patch.object(server, 'ThreadingHTTPServer') as http, \
             patch.object(server, 'ensure_go', side_effect=AssertionError('startup must not need Go')), \
             patch.object(server.subprocess, 'run', side_effect=AssertionError('no compiler on startup')):
            http.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.main()
            http.assert_called_once_with(('127.0.0.1', 8765), server.Handler)
            http.return_value.server_close.assert_called_once()

    def test_unknown_runtime_rejected(self):
        for runtime in ('compare', 'shell', ''):
            with self.assertRaises(ValueError):
                server.run_engine(runtime, {}, '')

    def test_missing_go_gives_actionable_error(self):
        with patch.object(server.subprocess, 'run', side_effect=FileNotFoundError), \
             patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'mkdir'):
            with self.assertRaisesRegex(ValueError, '请选择 Python'):
                server.ensure_go()

    def test_container_uses_prebuilt_go_without_compiler(self):
        with patch.dict(server.os.environ, {'STRATEGYLAB_PREBUILT_GO': '1'}), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(server.subprocess, 'run', side_effect=AssertionError('do not compile in container')):
            self.assertEqual(server.ensure_go(), ROOT/'bin/strategy-lab')
        with patch.dict(server.os.environ, {'STRATEGYLAB_PREBUILT_GO': '1'}), \
             patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(ValueError, '重新构建镜像'):
                server.ensure_go()

    def test_container_can_bind_all_interfaces_when_requested(self):
        with patch.object(sys, 'argv', ['server.py', '--host', '0.0.0.0']), \
             patch.object(server, 'ThreadingHTTPServer') as http:
            http.return_value.serve_forever.side_effect = KeyboardInterrupt
            server.main()
            http.assert_called_once_with(('0.0.0.0', 8765), server.Handler)


if __name__ == '__main__':
    unittest.main()

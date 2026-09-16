"""Submit code to the offline Docker worker; never execute it in the web process."""
import json
import os
from pathlib import Path
import shutil
import time
import uuid


def run_code(engine, strategy, csv_text, code):
    base = os.environ.get('STRATEGYLAB_JOBS_DIR')
    if not base:
        raise ValueError('代码回测需要隔离 worker；请使用 compose.deploy.yaml 启动')
    if engine not in ('python', 'go'):
        raise ValueError('请选择 Python 或 Go')
    if not isinstance(code, str) or not code.strip() or len(code.encode('utf-8')) > 100_000 or '\x00' in code:
        raise ValueError('策略代码不能为空，且必须小于 100 KB')
    folder = Path(base) / uuid.uuid4().hex
    folder.mkdir(mode=0o700)
    try:
        (folder / 'strategy.json').write_text(json.dumps(strategy, ensure_ascii=False, allow_nan=False))
        (folder / 'bars.csv').write_text(csv_text)
        (folder / ('user_strategy.py' if engine == 'python' else 'user_strategy.go')).write_text(code)
        (folder / 'request.json').write_text(json.dumps({'engine': engine}))
        deadline = time.monotonic() + 190
        while time.monotonic() < deadline:
            status_file = folder / 'status.json'
            if status_file.is_file():
                try:
                    phase = json.loads(status_file.read_text())['phase']
                except (json.JSONDecodeError, KeyError, OSError):
                    phase = None
                if phase == 'done':
                    result = folder / 'result.json'
                    if result.is_file() and result.stat().st_size <= 100 * 1024 * 1024:
                        return json.loads(result.read_text())
                    raise ValueError('隔离 worker 未返回有效回测结果')
                if phase == 'failed':
                    error_file = folder / 'error.json'
                    detail = json.loads(error_file.read_text()).get('error') if error_file.is_file() else '未知错误'
                    raise ValueError('代码回测失败：' + detail)
            time.sleep(0.2)
        raise ValueError('隔离 worker 等待超时，请检查容器状态与日志')
    finally:
        shutil.rmtree(folder, ignore_errors=True)

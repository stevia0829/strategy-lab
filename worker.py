"""Offline worker for trusted strategy code; deployed without network or secrets."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
JOBS = Path(os.environ.get('STRATEGYLAB_JOBS_DIR', '/jobs'))


def publish(job, name, value):
    pending = job / (name + '.tmp')
    pending.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False))
    pending.replace(job / name)


def execute(command, *, cwd, env, timeout):
    output = cwd / 'process.log'
    with output.open('wb') as log:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise ValueError('策略运行超时；请缩小行情区间或检查循环')
    if proc.returncode:
        detail = output.read_bytes()[-2400:].decode('utf-8', errors='replace').strip()
        raise ValueError('策略编译或运行失败：' + (detail or '进程退出 ' + str(proc.returncode)))


def run_job(job):
    request = json.loads((job / 'request.json').read_text())
    engine = request['engine']
    if engine not in ('python', 'go'):
        raise ValueError('未知运行方式')
    env = {'PATH': os.environ.get('PATH', '/usr/local/go/bin:/usr/local/bin:/usr/bin:/bin'),
           'HOME': '/tmp', 'PYTHONPATH': str(ROOT / 'python'),
           'PYTHONDONTWRITEBYTECODE': '1', 'GOPROXY': 'off', 'GOSUMDB': 'off',
           'GOWORK': 'off', 'GOTOOLCHAIN': 'local', 'GOCACHE': '/tmp/go-build',
           'GOPATH': '/tmp/gopath'}
    strategy, bars, result = (job / name for name in ('strategy.json', 'bars.csv', 'result.json'))
    if engine == 'python':
        command = [sys.executable, '-B', '-m', 'strategylab.custom_runner',
                   '--code', str(job / 'user_strategy.py'), '--strategy', str(strategy),
                   '--data', str(bars), '--out', str(result)]
    else:
        publish(job, 'status.json', {'phase': 'compiling'})
        (job / 'runner.go').write_text((ROOT / 'custom/go_runner.txt').read_text())
        (job / 'go.mod').write_text('module strategylabuser\n\ngo 1.23\n\nrequire strategylab v0.0.0\nreplace strategylab => ' + str(ROOT) + '\n')
        binary = job / 'user-strategy'
        execute(['go', 'build', '-o', str(binary), '.'], cwd=job, env=env, timeout=120)
        command = [str(binary), str(strategy), str(bars), str(result)]
    publish(job, 'status.json', {'phase': 'running'})
    execute(command, cwd=job, env=env, timeout=60)
    if not result.is_file() or result.stat().st_size > 100 * 1024 * 1024:
        raise ValueError('策略没有生成有效回测结果')
    json.loads(result.read_text())
    publish(job, 'status.json', {'phase': 'done'})


def main():
    JOBS.mkdir(parents=True, exist_ok=True)
    print('Strategy Lab offline worker ready', flush=True)
    while True:
        for job in JOBS.iterdir():
            if not job.is_dir() or not (job / 'request.json').exists() or (job / 'status.json').exists():
                continue
            publish(job, 'status.json', {'phase': 'starting'})
            try:
                run_job(job)
            except Exception as error:
                publish(job, 'error.json', {'error': str(error)[:2400]})
                publish(job, 'status.json', {'phase': 'failed'})
        time.sleep(0.25)


if __name__ == '__main__':
    main()

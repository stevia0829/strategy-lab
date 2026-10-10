#!/usr/bin/env python3
"""Strategy workbench. Runs fixed engines, never evaluates user source code."""
import argparse
import base64
import binascii
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import CookieError, SimpleCookie
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'python'))
from strategylab.engine import validate
from strategylab.market import load_market, connect_db
from agent_codegen import generate, generate_stream, validate_agent_turns
from history import get_run, list_runs, save_run
from job_queue import run_code
from code_symbols import include_code_symbols
SLOTS = threading.BoundedSemaphore(2)
SESSION_TTL_SECONDS = 12 * 60 * 60


GO_BUILD_LOCK = threading.Lock()


def issue_session(password, now=None):
    timestamp = int(time.time() if now is None else now)
    message = str(timestamp) + ':' + secrets.token_hex(16)
    signature = hmac.new(password.encode(), message.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((message + ':' + signature).encode()).decode().rstrip('=')


def valid_session(token, password, now=None):
    if not isinstance(token, str) or len(token) > 256:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)).decode()
        timestamp, nonce, signature = decoded.split(':')
        current = int(time.time() if now is None else now)
        if (not timestamp.isdigit() or not re.fullmatch(r'[0-9a-f]{32}', nonce)
                or not re.fullmatch(r'[0-9a-f]{64}', signature)
                or not 0 <= current - int(timestamp) <= SESSION_TTL_SECONDS):
            return False
        expected = hmac.new(password.encode(), (timestamp + ':' + nonce).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, UnicodeError):
        return False


def ensure_go():
    binary = ROOT / 'bin/strategy-lab'
    if os.environ.get('STRATEGYLAB_PREBUILT_GO') == '1':
        if not binary.is_file():
            raise ValueError('容器缺少预编译 Go 引擎；请重新构建镜像')
        return binary
    sources = list((ROOT/'engine').glob('*.go')) + list((ROOT/'cmd').rglob('*.go')) + [ROOT/'go.mod']
    with GO_BUILD_LOCK:
        newest = max(p.stat().st_mtime for p in sources)
        if not binary.exists() or binary.stat().st_mtime < newest:
            binary.parent.mkdir(exist_ok=True)
            try:
                proc = subprocess.run(['go', 'build', '-o', str(binary), './cmd/strategy-lab'],
                                      cwd=ROOT, capture_output=True, text=True, timeout=45)
            except FileNotFoundError:
                raise ValueError('Go 尚未安装；请选择 Python，或安装 Go 1.23+ 后重试')
            if proc.returncode:
                raise ValueError('Go 编译失败：' + proc.stderr.strip()[:1500])
    return binary


def run_engine(engine, strategy, csv_text):
    if engine not in ('python', 'go'):
        raise ValueError('请选择 Python 或 Go')
    binary = ensure_go() if engine == 'go' else None
    with tempfile.TemporaryDirectory(prefix='strategylab-') as folder:
        folder = Path(folder)
        (folder/'strategy.json').write_text(json.dumps(strategy,ensure_ascii=False,allow_nan=False))
        (folder/'bars.csv').write_text(csv_text)
        args = ['--strategy', str(folder/'strategy.json'), '--data', str(folder/'bars.csv'), '--out', str(folder/'result.json')]
        command = ([str(binary)] if engine == 'go' else [sys.executable, '-B', '-m', 'strategylab']) + args
        environment = dict(os.environ, PYTHONPATH=str(ROOT/'python'))
        proc = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=45)
        if proc.returncode: raise ValueError(engine + ': ' + proc.stderr.strip()[:1500])
        return json.loads((folder/'result.json').read_text())


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        password = os.environ.get('STRATEGYLAB_APP_PASSWORD')
        if not password:
            return True
        token = self.headers.get('Authorization', '')
        try:
            scheme, encoded = token.split(' ', 1)
            userpass = base64.b64decode(encoded, validate=True).decode() if scheme == 'Basic' else ''
        except (ValueError, UnicodeError, binascii.Error):
            userpass = ''
        if hmac.compare_digest(userpass, 'admin:' + password):
            return True
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie', ''))
            session = cookies.get('strategylab_session')
            return bool(session and valid_session(session.value, password))
        except CookieError:
            return False

    def send(self, status, body, mime='application/json; charset=utf-8', extra_headers=()):
        if not isinstance(body, bytes): body = json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers(); self.wfile.write(body)

    def start_agent_stream(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'close')
        self.end_headers()

    def send_agent_event(self, event):
        data = json.dumps(event, ensure_ascii=False, allow_nan=False)
        self.wfile.write(('data: ' + data + '\n\n').encode())
        self.wfile.flush()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/' and not self.authorized():
            return self.send(200, (ROOT/'web/login.html').read_bytes(), 'text/html; charset=utf-8')
        if path in ('/login.css', '/login.js'):
            mime = 'text/css' if path.endswith('.css') else 'text/javascript'
            return self.send(200, (ROOT/'web'/path[1:]).read_bytes(), mime+'; charset=utf-8')
        if path not in ('/api/health','/api/market/status') and not self.authorized():
            return self.send(401, {'error':'请先登录'})
        assets = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if path in assets:
            mime = {'/':'text/html','/app.js':'text/javascript','/style.css':'text/css'}[path]
            return self.send(200,(ROOT/'web'/assets[path]).read_bytes(),mime+'; charset=utf-8')
        if path == '/api/presets':
            return self.send(200,{name:json.loads((ROOT/'examples'/(name+'.json')).read_text()) for name in ('trend','rsi','rotation','buy_hold')})
        if path == '/api/demo': return self.send(200,(ROOT/'examples/demo.csv').read_bytes(),'text/csv; charset=utf-8')
        if path == '/api/code-examples':
            return self.send(200,{name:(ROOT/'examples'/('custom_rsi.'+extension)).read_text()
                                  for name, extension in (('python','py'),('go','go'))})
        if path == '/api/runs':
            try: return self.send(200,{'runs':list_runs()})
            except ValueError as error: return self.send(503,{'error':str(error)})
        if path.startswith('/api/runs/'):
            try:
                item = get_run(path.removeprefix('/api/runs/'))
                return self.send(200,item) if item else self.send(404,{'error':'回测记录不存在'})
            except ValueError as error: return self.send(400,{'error':str(error)})
        if path == '/api/health': return self.send(200,{'status':'ok','go':(ROOT/'bin/strategy-lab').exists(),'python':True})
        if path == '/api/market/status':
            try:
                with connect_db() as conn:
                    conn.execute('SELECT 1')
                return self.send(200,{'ready':True,'providers':['eastmoney','tencent'],'adjustment':'qfq'})
            except ValueError as error:
                return self.send(200,{'ready':False,'message':str(error)})
        self.send(404,{'error':'not found'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ('/api/login','/api/run','/api/agent/generate','/api/agent/stream'):
            return self.send(404,{'error':'not found'})
        if path != '/api/login' and not self.authorized():
            return self.send(401, {'error':'请先登录'})
        origin = self.headers.get('Origin')
        host = self.headers.get('Host','')
        if origin and origin not in ('http://' + host, 'https://' + host):
            return self.send(403,{'error':'cross-origin request denied'})
        if self.headers.get_content_type() != 'application/json':
            return self.send(415,{'error':'use application/json'})
        try: size = int(self.headers.get('Content-Length','0'))
        except ValueError: return self.send(400,{'error':'invalid content length'})
        limit = 1024 if path == '/api/login' else 10 * 1024 * 1024
        if not 0 < size <= limit: return self.send(413,{'error':'request too large'})
        if path == '/api/login':
            try: payload = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError): return self.send(400, {'error':'请求格式无效'})
            supplied = payload.get('password') if isinstance(payload, dict) else None
            password = os.environ.get('STRATEGYLAB_APP_PASSWORD')
            if not isinstance(supplied, str) or not password or not hmac.compare_digest(supplied, password):
                return self.send(401, {'error':'密码错误'})
            session = issue_session(password)
            secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
            cookie = ('strategylab_session=' + session + '; Path=/; HttpOnly; SameSite=Strict; Max-Age='
                      + str(SESSION_TTL_SECONDS) + secure)
            return self.send(200, {'ok':True}, extra_headers=(('Set-Cookie', cookie),))
        if not SLOTS.acquire(False): return self.send(429,{'error':'two experiments are already running'})
        try:
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload,dict): raise ValueError('request must be an object')
            if path == '/api/agent/generate':
                return self.send(200,generate(payload))
            if path == '/api/agent/stream':
                self.start_agent_stream()
                try:
                    generate_stream(payload, self.send_agent_event)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except (ValueError, KeyError, TypeError, OSError) as error:
                    try: self.send_agent_event({'type':'error','message':str(error)})
                    except (BrokenPipeError, ConnectionResetError): pass
                return
            mode = payload.get('engine','python')
            if mode not in ('go','python'): raise ValueError('unknown engine')
            strategy = validate(payload['strategy'])
            source = payload.get('source') or ('uploaded' if payload.get('csv') is not None else 'synthetic_demo')
            if source not in ('synthetic_demo','uploaded','market'):
                raise ValueError('unknown data source')
            code = payload.get('user_code')
            if code is not None and source == 'market':
                strategy = validate(include_code_symbols(strategy, code, mode))
            if source == 'market':
                if payload.get('csv') is not None: raise ValueError('market request cannot include CSV')
                csv_text, source_meta = load_market(strategy)
            elif source == 'uploaded':
                csv_text, source_meta = payload.get('csv'), None
                if not isinstance(csv_text,str): raise ValueError('csv must be text')
            else:
                csv_text, source_meta = (ROOT/'examples/demo.csv').read_bytes().decode('utf-8'), None
            agent_turns = validate_agent_turns(payload.get('agent_turns')) if code is not None else []
            output = run_code(mode,strategy,csv_text,code) if code is not None else run_engine(mode,strategy,csv_text)
            canonical = json.dumps(strategy,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            bundle = {'strategy':strategy,'strategy_sha256':hashlib.sha256(canonical).hexdigest(),
                      'strategy_mode':'code' if code is not None else 'simple',
                      'user_code':code,'code_sha256':hashlib.sha256(code.encode()).hexdigest() if code is not None else None,
                      'agent_turns':agent_turns,
                      'source':source,'source_meta':source_meta,'result':output}
            try: bundle['run_id'] = save_run(bundle)
            except (ValueError, OSError) as error: bundle['history_error'] = str(error)
            self.send(200,bundle)
        except subprocess.TimeoutExpired:
            self.send(408,{'error':'engine exceeded 45 seconds; reduce rows/indicators'})
        except (ValueError,KeyError,TypeError,OSError) as error:
            self.send(400,{'error':str(error)})
        finally: SLOTS.release()

    def log_message(self, fmt, *args):
        print('%s %s' % (self.log_date_time_string(), fmt % args), flush=True)


def main():
    parser=argparse.ArgumentParser(description='Local Strategy Lab workbench')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',choices=('127.0.0.1','0.0.0.0'),default='127.0.0.1')
    args=parser.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print('Strategy Lab: listening on %s:%d' % (args.host,args.port),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()

"""An isolated DSH SDK conversation with text and image input."""
import json
import shutil
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import secrets
import subprocess
import threading
import time
from runtime_support import node_entry

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/chat'
NODE = os.environ.get('DAFEIYU_NODE') or shutil.which('node') or 'node'
DSH = node_entry(os.environ.get('DAFEIYU_DSH') or shutil.which('dsh') or 'dsh','node_modules/@deepseek-ai/dsh/lib/bin.js')


class DshChat:
    def __init__(self, profile='dafeiyu-group'):
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.use_persona = profile in ('dafeiyu-direct','dafeiyu-group','dafeiyu-owner')
        self.owner_tools = profile == 'dafeiyu-owner'
        self.frames = queue.Queue()
        self.tool_lock = threading.Lock()
        self.tool_context = None
        self.tool_calls = 0
        self.action_server = None
        env = {**os.environ, 'DSH_HOME': os.environ.get('DSH_HOME', str(Path.home()/'.dsh'))}
        command = [NODE, DSH, '--profile', 'dafeiyu-direct' if self.owner_tools else profile]
        if self.owner_tools:
            self.action_token = secrets.token_urlsafe(32)
            self._start_actions()
            directory = Path(__file__).resolve().parent
            command += ['--patch', str(directory / 'owner-tools.patch.yml')]
            env.update({
                'DAFEIYU_TOOLS_MODULE': subprocess.check_output([NODE,'-e',
                    "console.log(require.resolve('@deepseek-ai/dsh-tools',{paths:[process.argv[1]]}))",
                    str(Path(DSH).resolve().parent)],text=True,encoding='utf-8').strip(),
                'DAFEIYU_ACTION_URL': f'http://127.0.0.1:{self.action_server.server_port}/action',
                'DAFEIYU_ACTION_TOKEN': self.action_token,
            })
        self.stderr = open(STATE / 'dsh-diagnostics.log', 'a', encoding='utf-8')
        self.counter = 0
        self.messages = {}
        self.resumed = set()
        try:
            self.proc = subprocess.Popen(
                command, cwd=STATE, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                text=True, encoding='utf-8', bufsize=1)
            threading.Thread(target=self._read, daemon=True).start()
            self.rpc('initialize', {'cwd': str(STATE), 'provider': os.environ.get('DAFEIYU_PROVIDER','configured'),
                                   'model': os.environ.get('DAFEIYU_MODEL','deepseek-chat'), 'maxTokens': 4096}, 40)
        except Exception:
            self.close()
            raise

    def _start_actions(self):
        chat = self

        class ActionHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, status, payload):
                content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                self.connection.settimeout(10)
                if self.path != '/action' or not secrets.compare_digest(
                        self.headers.get('Authorization', '').encode(),
                        ('Bearer ' + chat.action_token).encode()):
                    self.respond(403, {'ok': False, 'error': '操作未授权'})
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 65536:
                        raise ValueError('操作请求过大或为空')
                    request = json.loads(self.rfile.read(size))
                    if (not isinstance(request, dict) or
                            not isinstance(request.get('action'), str) or
                            not isinstance(request.get('args'), dict)):
                        raise ValueError('操作请求格式错误')
                except (ValueError, OSError) as error:
                    self.respond(400, {'ok': False, 'error': str(error)})
                    return
                with chat.tool_lock:
                    context = chat.tool_context
                    if context is None or request.get('session') != context[0]:
                        self.respond(403, {'ok': False, 'error': '当前会话没有操作权限'})
                        return
                    if chat.tool_calls >= 6:
                        self.respond(429, {'ok': False, 'error': '本轮最多调用六次工具'})
                        return
                    chat.tool_calls += 1
                result = queue.Queue()
                chat.frames.put((context, request['action'], request['args'], result))
                while True:
                    try:
                        payload = result.get(timeout=0.2)
                        break
                    except queue.Empty:
                        with chat.tool_lock:
                            if chat.tool_context is not context:
                                payload = {'ok': False, 'error': '本轮操作已结束'}
                                break
                self.respond(200, payload)

        self.action_server = ThreadingHTTPServer(('127.0.0.1', 0), ActionHandler)
        threading.Thread(target=self.action_server.serve_forever, daemon=True).start()

    def _run_action(self, frame):
        context, action, args, result = frame
        with self.tool_lock:
            active = self.tool_context is context
        try:
            if not active:
                raise RuntimeError('本轮操作已结束')
            payload = {'ok': True, 'result': context[1](action, args)}
            json.dumps(payload, allow_nan=False)
        except Exception as error:
            payload = {'ok': False, 'error': str(error)}
        result.put(payload)

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.frames.put(json.loads(line))
                except (ValueError, TypeError):
                    pass
        finally:
            self.frames.put(None)

    def rpc(self, method, params=None, timeout=180):
        self.counter += 1
        request_id = self.counter
        request = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
        if params is not None:
            request['params'] = params
        self.proc.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('DSH request timed out: ' + method)
            frame = self.frames.get(timeout=remaining)
            if frame is None:
                raise RuntimeError('DSH runtime disconnected')
            if isinstance(frame, tuple):
                self._run_action(frame)
                continue
            if frame.get('id') == request_id:
                if 'error' in frame:
                    raise RuntimeError('DSH request failed: ' + method)
                return frame.get('result')
            if frame.get('method') == 'session.event':
                params_in = frame.get('params', {})
                event = params_in.get('event', {})
                if event.get('type') == 'tool/call' and not self.owner_tools:
                    raise RuntimeError('Unexpected tool invocation in text-only profile')
                if event.get('type') == 'assistant/message':
                    data = event.get('data', {})
                    if not data.get('interrupted'):
                        blocks = data.get('message', {}).get('content', [])
                        text = ''.join(x.get('text', '') for x in blocks if x.get('type') == 'text')
                        if self.owner_tools:
                            completed = text.strip() and not any(x.get('type') == 'tool-call' for x in blocks)
                            self.messages[params_in['sessionId']] = [text.strip()] if completed else []
                        elif text.strip():
                            self.messages.setdefault(params_in['sessionId'], []).append(text.strip())

    def reply(self, session_id, prompt, resume=False, images=None, max_chars=1800, tools=None):
        persona = ROOT/'resources/persona.md'
        if self.use_persona and persona.is_file():
            prompt = '使用者配置的人设：\n'+persona.read_text(encoding='utf-8')[:32768]+'\n本轮输入：\n'+prompt
        with self.tool_lock:
            self.tool_context = (session_id, tools) if self.owner_tools and tools is not None else None
            self.tool_calls = 0
        try:
            if resume and session_id not in self.resumed:
                self.rpc('session/resume', {'sessionId': session_id}, 40)
            self.resumed.add(session_id)
            self.messages[session_id] = []
            self.rpc('session/prompt', {'sessionId': session_id,
                     'contentBlocks': [{'type': 'text', 'text': prompt}] + (images or [])}, 40)
            self.rpc('session/wait', {'sessionId': session_id})
        finally:
            with self.tool_lock:
                self.tool_context = None
            replies = self.messages.pop(session_id, [])
        if not replies:
            raise RuntimeError('DSH returned no completed text response')
        return '\n'.join(replies)[:max_chars]

    def close(self):
        with self.tool_lock:
            self.tool_context = None
        if not hasattr(self, 'proc'):
            if self.action_server is not None:
                self.action_server.shutdown()
                self.action_server.server_close()
            self.stderr.close()
            return
        try:
            self.rpc('shutdown', timeout=15)
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.action_server is not None:
            self.action_server.shutdown()
            self.action_server.server_close()
        self.stderr.close()

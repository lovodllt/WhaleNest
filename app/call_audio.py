"""Separate WeChat receive audio from the existing silent transmit microphone."""
import json
from pathlib import Path
import subprocess
import queue
import threading


def ready(process, expected):
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        return lines.get(timeout=5).strip() == expected
    except queue.Empty:
        return False


class NativeCallAudio:
    def __init__(self, container, call_id):
        self.container, self.call_id = container, call_id
        self.sink = 'whalenest_call_rx'
        self.module = None
        self.old_sink = None
        self.lock = None
        self.sink_index = self.mic_index = None

    def command(self, *args):
        return ['docker', 'exec', '-i', '-u', 'webox', '-e', 'HOME=/webox/state/home', '-e', 'DISPLAY=:1',
                '-e', 'PULSE_SERVER=unix:/webox/runtime/pulse/native', self.container, *args]

    def run(self, *args):
        return subprocess.run(self.command(*args), capture_output=True, text=True, encoding='utf-8', check=True, timeout=8).stdout.strip()

    def controls(self, action='probe', frame=None, caller_names=()):
        script = (Path(__file__).resolve().parents[1] / 'plugins/voice/call/ui.py').read_text(encoding='utf-8')
        request = json.dumps({'action': action, 'frame': frame, 'caller_names': list(caller_names)}, ensure_ascii=False)
        command = self.command('python3', '-c', 'import os;os.environ["WHALENEST_CALL_REQUEST"]=' + repr(request) + '\n' + script)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=15)
        if result.returncode:
            raise RuntimeError('通话界面操作失败：' + result.stderr.strip().split('\n')[-1][:240])
        return json.loads(result.stdout)

    def acquire(self):
        script = r'''import fcntl,sys,json,subprocess,os,signal
from pathlib import Path
f=open('/webox/state/weagent/ui-send.lock','a')
fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
old=subprocess.check_output(['pactl','get-default-sink'],text=True).strip()
if old=='whalenest_call_rx':old='voice_bus'
def cleanup():
    for entry in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args=entry.read_bytes().split(b'\0')
            if b'--client-name=WhaleNestCallPlayback' in args or b'--client-name=WhaleNestCallCapture' in args:
                os.kill(int(entry.parent.name),signal.SIGTERM)
        except (OSError,ValueError):pass
    subprocess.run(['pactl','set-default-sink',old],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for item in json.loads(subprocess.check_output(['pactl','-f','json','list','modules'])):
        if 'sink_name=whalenest_call_rx' in item.get('argument','').split():
            subprocess.run(['pactl','unload-module',str(item['index'])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
cleanup()
print('locked',flush=True)
try:sys.stdin.read()
finally:cleanup()
'''
        self.lock = subprocess.Popen(self.command('python3', '-c', script), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if not ready(self.lock, b'locked'):
            self.close()
            raise RuntimeError('微信收发界面当前忙碌')
        self.old_sink = self.run('pactl', 'get-default-sink')
        self.module = self.run('pactl', 'load-module', 'module-null-sink', 'sink_name=' + self.sink, 'rate=16000', 'channels=1')
        self.run('pactl', 'set-default-sink', self.sink)
        self.sink_index = next(s['index'] for s in json.loads(self.run('pactl', '-f', 'json', 'list', 'sinks')) if s['name'] == self.sink)
        self.mic_index = next(s['index'] for s in json.loads(self.run('pactl', '-f', 'json', 'list', 'sources')) if s['name'] == 'dafeiyu_mic')
        self.route()

    def route(self):
        for stream in json.loads(self.run('pactl', '-f', 'json', 'list', 'sink-inputs')):
            props = stream.get('properties', {})
            if 'wechat' in props.get('application.process.binary', '').lower() and stream['sink'] != self.sink_index:
                try:self.run('pactl', 'move-sink-input', str(stream['index']), self.sink)
                except subprocess.CalledProcessError:
                    if any(s['index'] == stream['index'] for s in json.loads(self.run('pactl', '-f', 'json', 'list', 'sink-inputs'))):raise
        for stream in json.loads(self.run('pactl', '-f', 'json', 'list', 'source-outputs')):
            props = stream.get('properties', {})
            if 'wechat' in props.get('application.process.binary', '').lower() and stream['source'] != self.mic_index:
                try:self.run('pactl', 'move-source-output', str(stream['index']), 'dafeiyu_mic')
                except subprocess.CalledProcessError:
                    if any(s['index'] == stream['index'] for s in json.loads(self.run('pactl', '-f', 'json', 'list', 'source-outputs'))):raise

    def capture(self):
        return subprocess.Popen(self.command('parec', '--device=' + self.sink + '.monitor', '--raw', '--format=s16le',
            '--rate=16000', '--channels=1', '--latency-msec=32', '--client-name=WhaleNestCallCapture', '--stream-name=' + self.call_id),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def playback(self, rate, channels):
        args = ['paplay', '--device=voice_bus', '--latency-msec=40', '--raw', '--format=s16le', '--rate=' + str(rate),
                '--channels=' + str(channels), '--client-name=WhaleNestCallPlayback', '--stream-name=' + self.call_id]
        script = 'import subprocess,sys\np=subprocess.Popen(' + repr(args) + ''',stdin=subprocess.PIPE)
print('ready',flush=True)
try:
    while True:
        chunk=sys.stdin.buffer.read(4096)
        if not chunk:break
        p.stdin.write(chunk);p.stdin.flush()
except BrokenPipeError:pass
finally:
    try:p.stdin.close()
    except BrokenPipeError:pass
sys.exit(p.wait())
'''
        process = subprocess.Popen(self.command('python3', '-c', script), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if not ready(process, b'ready'):
            self.stop_streams(playback_only=True)
            process.terminate()
            process.wait(timeout=3)
            raise RuntimeError('通话播放器未启动')
        return process

    def stop_streams(self, playback_only=False):
        names = ['--client-name=WhaleNestCallPlayback']
        if not playback_only:names.append('--client-name=WhaleNestCallCapture')
        script = '''import os,signal,json,sys
from pathlib import Path
names={v.encode() for v in json.loads(sys.argv[1])}
stream=('--stream-name='+sys.argv[2]).encode()
for entry in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        args=set(entry.read_bytes().split(b'\\0'))
        if stream in args and names & args:os.kill(int(entry.parent.name),signal.SIGTERM)
    except (OSError,ValueError):pass
'''
        self.run('python3', '-c', script, json.dumps(names), self.call_id)

    def close(self):
        errors = []
        if self.lock:
            try:
                self.lock.stdin.close()
                self.lock.wait(timeout=5)
                if self.lock.returncode:
                    errors.append('audio_cleanup_failed')
            except (OSError, subprocess.TimeoutExpired):
                errors.append('audio_lock_exit_timeout')
                self.lock.terminate()
            finally:
                self.lock.stdout.close()
                self.lock = None
        return errors

import io
import json
import os
import re
import subprocess
import urllib.request
import uuid
import wave
from pathlib import Path

import chat_style
from chat_rules import load_settings
from dsh_chat import ROOT


def declined(text):
    return bool(re.search(r'(?:别|不要|不用|停止).{0,8}语音',text))


def requested(text, settings):
    if not settings.get('voice_reply', {}).get('enabled', False):
        return False
    if declined(text):
        return False
    return bool(re.search(r'(?:用|发|来|给|录).{0,8}语音|语音.{0,8}(?:回复|说|讲|回答|聊|念|打个?招呼|来一[句段]|发送)', text))


def spontaneous(settings, text, last_sent, now_ms):
    rule = settings.get('voice_reply',{})
    return (rule.get('enabled',False) and rule.get('spontaneous',False) and not declined(text)
            and now_ms-last_sent>=rule.get('spontaneous_interval_minutes',30)*60_000)


class VoiceSendError(RuntimeError):
    def __init__(self, message, before_send):
        super().__init__(message)
        self.before_send = before_send


def send(target, text):
    spoken = ''.join(m[0] for m in chat_style._TOKENS.finditer(text) if m.lastgroup == 'char').strip()
    if not spoken:
        raise ValueError('No spoken text')
    payload={'text':spoken}
    endpoint='http://127.0.0.1:9981/tts.wav'
    if load_settings().get('voice_reply',{}).get('provider','edge')=='gpt-sovits':
        profile=json.loads((ROOT/'config/voice.json').read_text(encoding='utf-8')).get('gpt_sovits',{})
        if not Path(profile.get('reference_audio','')).is_file():raise VoiceSendError('本地音色尚未配置参考音频',True)
        endpoint='http://127.0.0.1:9980/tts'
        payload.update(text_lang='all_zh',ref_audio_path=profile['reference_audio'],prompt_text=profile.get('reference_text',''),
                       prompt_lang='all_zh',media_type='wav',streaming_mode=False,batch_size=1)
    request = urllib.request.Request(endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type':'application/json'})
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with http.open(request, timeout=65) as response:
        audio = response.read()
    return _send_audio(target, audio)


def send_file(target, path):
    return _send_audio(target, Path(path).read_bytes())


def _send_audio(target, audio):
    with wave.open(io.BytesIO(audio)) as sample:
        duration = sample.getnframes() / sample.getframerate()
        if not 1 <= duration <= 55:
            raise ValueError('Voice duration must be 1–55 seconds')
        if sample.getsampwidth() != 2 or sample.getnchannels() not in (1, 2):
            raise ValueError('Voice audio must be mono or stereo PCM16')
    relative = 'outbox/voice-' + uuid.uuid4().hex + '.wav'
    state = Path(os.environ.get('WEBOX_STATE_DIR', ROOT/'data/wechat'))
    path = state/'shared/rooms'/target/relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(audio)
    if load_settings().get('reply_paused', False):
        raise VoiceSendError('WeChat replies are paused', True)
    try:
        result = subprocess.run(['docker','exec','-i','-u','webox','-e','HOME=/webox/state/home','-e','DISPLAY=:1','-e','WEBOX_FAST_UI=1','-e','WEBOX_SKIP_POSTLOGIN_ESCAPE=1',
            'dafeiyu-wechat','/webox/state/weagent/native-reply','--voice',target],
            input=json.dumps({'SharedPath':relative}), capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        raise VoiceSendError('Voice send timed out; no automatic resend', False) from error
    try:
        receipt = json.loads(result.stdout or '{}')
    except ValueError as error:
        raise VoiceSendError('Voice send receipt is unavailable; no automatic resend', False) from error
    if result.returncode or receipt.get('ret') != 0:
        raise VoiceSendError(receipt.get('error','Voice send failed'), receipt.get('before_send',False))
    return receipt

import asyncio
import io
import json
from pathlib import Path

import edge_tts
import soundfile
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
SETTINGS = BASE.parents[1] / 'config/voice.json'
VOICES = BASE.parents[1] / 'data/tts/voices.json'
PREVIEW = BASE.parents[1] / 'data/tts/preview.wav'
app = FastAPI(title='大肥鱼 · 微软语音')


class Profile(BaseModel):
    voice: str
    rate: int = Field(default=0, ge=-50, le=100)
    pitch: int = Field(default=0, ge=-30, le=30)
    volume: int = Field(default=0, ge=-50, le=100)


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class PreviewRequest(Profile, TextRequest):
    pass


def settings():
    return json.loads(SETTINGS.read_text())


async def synthesize(text, profile):
    if not text.strip():
        raise HTTPException(400, '请先输入试听内容')
    if profile.voice not in {v['voice'] for v in json.loads(VOICES.read_text())}:
        raise HTTPException(400, '请选择列表中的声音')
    speech = edge_tts.Communicate(
        text, profile.voice, rate=f'{profile.rate:+d}%',
        pitch=f'{profile.pitch:+d}Hz', volume=f'{profile.volume:+d}%'
    )

    async def collect():
        chunks = [part['data'] async for part in speech.stream() if part['type'] == 'audio']
        return b''.join(chunks)

    try:
        audio = await asyncio.wait_for(collect(), timeout=60)
    except Exception as error:
        raise HTTPException(502, f'微软语音暂时未返回，请稍后重试：{error}') from error
    if not audio:
        raise HTTPException(502, '未收到声音，请稍后重试')
    return Response(audio, media_type='audio/mpeg', headers={'Cache-Control': 'no-store'})


@app.get('/')
def page():
    return FileResponse(BASE / '微软语音调音台.html')


@app.get('/voices')
def voices():
    return json.loads(VOICES.read_text())


@app.get('/config')
def config():
    return settings()['edge_tts']


@app.post('/config')
def save_config(profile: Profile):
    if profile.voice not in {v['voice'] for v in voices()}:
        raise HTTPException(400, '请选择列表中的声音')
    data = settings()
    data['edge_tts'] = profile.model_dump()
    temporary = SETTINGS.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(SETTINGS)
    return profile


@app.post('/preview')
async def preview(request: PreviewRequest):
    result = await synthesize(request.text, request)
    samples, rate = soundfile.read(io.BytesIO(result.body))
    soundfile.write(PREVIEW, samples, rate, subtype='PCM_16')
    return {'url': '/preview.wav'}


@app.get('/preview.wav')
def preview_audio():
    if not PREVIEW.exists():
        raise HTTPException(404, '请先生成试听')
    return FileResponse(PREVIEW, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@app.post('/tts')
async def tts(request: TextRequest):
    return await synthesize(request.text, Profile(**settings()['edge_tts']))


@app.post('/tts.wav')
async def tts_wav(request: TextRequest):
    result = await tts(request)
    samples, rate = soundfile.read(io.BytesIO(result.body))
    audio = io.BytesIO()
    soundfile.write(audio, samples, rate, format='WAV', subtype='PCM_16')
    return Response(audio.getvalue(), media_type='audio/wav')


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=9981)

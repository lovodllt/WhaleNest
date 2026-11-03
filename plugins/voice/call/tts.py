"""Stream the existing Edge voice as PCM16 mono, without saving call audio."""
import asyncio
import json
from pathlib import Path
import sys

import edge_tts


async def main():
    request = json.loads(sys.stdin.readline())
    text = request['text']
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 180:
        raise ValueError('通话语音正文须为1–180字')
    profile = json.loads(Path(request['profile']).read_text())['edge_tts']
    speech = edge_tts.Communicate(text, profile['voice'], rate=f"{profile['rate']:+d}%",
        pitch=f"{profile['pitch']:+d}Hz", volume=f"{profile['volume']:+d}%", receive_timeout=15)
    decoder = await asyncio.create_subprocess_exec(request['ffmpeg'], '-v', 'error',
        '-probesize', '32', '-analyzeduration', '0', '-f', 'mp3', '-i', 'pipe:0',
        '-f', 's16le', '-ar', '24000', '-ac', '1', '-flush_packets', '1', 'pipe:1',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

    async def feed():
        try:
            async for part in speech.stream():
                if part['type'] == 'audio':
                    decoder.stdin.write(part['data'])
                    await decoder.stdin.drain()
        finally:
            decoder.stdin.close()

    async def output():
        while chunk := await decoder.stdout.read(2048):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()

    try:
        await asyncio.wait_for(asyncio.gather(feed(), output()), timeout=20)
        if await decoder.wait():
            raise RuntimeError('音频解码失败')
    finally:
        if decoder.returncode is None:
            decoder.terminate()
            await decoder.wait()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)

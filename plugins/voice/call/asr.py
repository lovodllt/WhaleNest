"""PCM16 stdin to speech-start/transcript events; CPU only, no raw-audio files."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import time
import wave

import numpy as np
import sherpa_onnx


def emit(value):
    value['at_real_ms'] = int(time.time() * 1000)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=Path)
    parser.add_argument('--models', type=Path, required=True)
    args = parser.parse_args()
    models = args.models
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(models/'model.int8.onnx'),
        tokens=str(models/'tokens.txt'), num_threads=2, use_itn=True, provider='cpu')

    def recognize(samples, sample_rate=16000):
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()

    if args.file:
        with wave.open(str(args.file)) as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).reshape(-1,wav.getnchannels()).mean(axis=1).astype(np.float32)/32768
            start = time.monotonic()
            emit({'text': recognize(samples,wav.getframerate()), 'recognition_seconds': time.monotonic()-start})
        return
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(models/'silero_vad.onnx')
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = 0.45
    config.silero_vad.min_speech_duration = 0.2
    config.silero_vad.max_speech_duration = 20
    config.sample_rate = 16000
    config.num_threads = 1
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    work = queue.Queue(maxsize=4)

    def decode():
        while True:
            item = work.get()
            if item is None:
                return
            ident, samples = item
            try:
                started = time.monotonic()
                text = recognize(samples)
                emit({'type':'transcript','utterance_id':ident,'text':text,
                      'recognition_ms':round((time.monotonic()-started)*1000)})
            except Exception as error:
                emit({'type':'error','error':type(error).__name__})
    threading.Thread(target=decode,daemon=True).start()
    emit({'type':'ready'})
    speech, ident = False, 0
    while True:
        chunk = sys.stdin.buffer.read(1024)
        if len(chunk) != 1024:
            break
        vad.accept_waveform(np.frombuffer(chunk,dtype=np.int16).astype(np.float32)/32768)
        detected = vad.is_speech_detected()
        if detected and not speech:
            ident += 1
            emit({'type':'speech_start','utterance_id':ident})
        if speech and not detected:
            emit({'type':'speech_end','utterance_id':ident})
        speech = detected
        while not vad.empty():
            samples = np.array(vad.front.samples,copy=True)
            vad.pop()
            try:
                work.put_nowait((ident,samples))
            except queue.Full:
                emit({'type':'error','error':'recognition_backlog'})


if __name__ == '__main__':
    main()

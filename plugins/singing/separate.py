from pathlib import Path
import sys
import numpy as np
import soundfile as sf
import torch
from demucs.pretrained import get_model
from demucs.apply import apply_model

root=Path(__file__).resolve().parent
torch.set_num_threads(4)
input_path=Path(sys.argv[1]) if len(sys.argv)>1 else root/'rain-love-preview.wav'
outdir=Path(sys.argv[2]) if len(sys.argv)>2 else root
outdir.mkdir(parents=True,exist_ok=True)
audio,rate=sf.read(input_path,always_2d=True,dtype='float32')
assert rate==44100
model=get_model('htdemucs').eval()
wav=torch.from_numpy(audio.T)
reference=wav.mean(0);mean=reference.mean();std=reference.std()
with torch.no_grad():
 stems=apply_model(model,((wav-mean)/std)[None],device='cpu',shifts=0,split=True,overlap=.25,progress=False)[0]*std+mean
vocal=stems[model.sources.index('vocals')]
sf.write(outdir/'vocals.wav',vocal.T.numpy(),rate)
sf.write(outdir/'accompaniment.wav',(wav-vocal).T.numpy(),rate)
print('Input vocals and accompaniment separated',flush=True)

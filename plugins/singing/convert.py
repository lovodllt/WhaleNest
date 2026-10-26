from pathlib import Path
from types import SimpleNamespace
import json,os,sys,threading,time
import numpy as np
import soundfile as sf
import torch,yaml,pynvml,psutil

root=Path(__file__).resolve().parent
input_path=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'rain-love-short-vocals.wav'
outdir=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else root/'converted'
outdir.mkdir(parents=True,exist_ok=True)
source=root/'seed-vc-main'
os.chdir(source);sys.path.insert(0,str(source))
torch.set_num_threads(4)
torch.set_num_interop_threads(1)
torch.cuda.set_per_process_memory_fraction(.70)
pynvml.nvmlInit();gpu=pynvml.nvmlDeviceGetHandleByIndex(0)
limit=6*1024**3
metrics={'gpu_limit_bytes':limit,'gpu_peak_bytes':0,'rss_peak_bytes':0}
def watch():
 while True:
  used=pynvml.nvmlDeviceGetMemoryInfo(gpu).used
  metrics.update(gpu_peak_bytes=max(metrics['gpu_peak_bytes'],used),
                 rss_peak_bytes=max(metrics['rss_peak_bytes'],psutil.Process().memory_info().rss))
  (outdir/'resource-metrics.json').write_text(json.dumps(metrics,indent=2))
  if used>limit:
   print('6 GiB GPU limit exceeded; trial stopped',flush=True);os._exit(75)
  time.sleep(.2)
threading.Thread(target=watch,daemon=True).start()
import inference

def local_model(repo,filename,config_filename=None):
 folder=root/'models'/repo.split('/')[-1]
 return (str(folder/filename),str(folder/config_filename)) if config_filename else str(folder/filename)
inference.load_custom_model_from_hf=local_model
config=yaml.safe_load((root/'singing-config.yml').read_text())
config['model_params']['vocoder']['name']=str(root/'models/bigvgan_v2_44khz_128band_512x')
config['model_params']['speech_tokenizer']['name']=str(root/'models/whisper-small')
(outdir/'local-config.yml').write_text(yaml.safe_dump(config))
# Short audition and reference need fewer cache frames than a complete song.
original_load=inference.load_models
captured=[]
def load(args):
 models=original_load(args);captured.extend(models);return models
inference.load_models=load
inference.torchaudio.save=lambda path,wave,rate:sf.write(path,wave.detach().cpu().numpy().T,rate)
args=SimpleNamespace(source=str(input_path),
 target=str(root/'reference.wav'),output=str(outdir),diffusion_steps=30,
 length_adjust=1.0,inference_cfg_rate=.7,f0_condition=True,auto_f0_adjust=False,
 semi_tone_shift=0,checkpoint=str(root/'models/Seed-VC/DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth'),
 config=str(outdir/'local-config.yml'),fp16=True)
started=time.monotonic()
inference.main(args)
out=next(outdir.glob('vc_*.wav'))
audio,rate=sf.read(out,dtype='float32')
assert len(audio)>rate and np.isfinite(audio).all() and np.max(np.abs(audio))>.01
metrics['elapsed_seconds']=round(time.monotonic()-started,2)
metrics['audio_seconds']=len(audio)/rate
metrics['result']=str(out)
f0=captured[2]
src,_=sf.read(input_path,dtype='float32',always_2d=True)
reference=torch.from_numpy(src.mean(1)).to('cuda')
generated=torch.from_numpy(audio).to('cuda')
src_f0=f0(inference.torchaudio.functional.resample(reference,rate,16000),thred=.03)
out_f0=f0(inference.torchaudio.functional.resample(generated,rate,16000),thred=.03)
n=min(len(src_f0),len(out_f0));mask=(src_f0[:n]>50)&(out_f0[:n]>50)
if mask.any():
 cents=1200*np.log2(out_f0[:n][mask]/src_f0[:n][mask])
 metrics.update(pitch_median_cents=float(np.median(cents)),pitch_median_absolute_cents=float(np.median(np.abs(cents))))
(outdir/'result.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
print(json.dumps(metrics,ensure_ascii=False),flush=True)

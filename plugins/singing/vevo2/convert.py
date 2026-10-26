from pathlib import Path
import gc,json,os,sys,threading,time
import numpy as np
import soundfile as sf
import torch,pynvml,psutil

root=Path(__file__).resolve().parent
source=root/'Amphion';sys.path.insert(0,str(source));os.chdir(source)
outdir=root/'converted';outdir.mkdir(exist_ok=True)
limit=6*1024**3
torch.set_num_threads(4);torch.set_num_interop_threads(1)
pynvml.nvmlInit();gpu=pynvml.nvmlDeviceGetHandleByIndex(0)
info=pynvml.nvmlDeviceGetMemoryInfo(gpu)
torch.cuda.set_per_process_memory_fraction((limit-info.used-256*1024**2)/info.total)
metrics={'gpu_limit_bytes':limit,'gpu_peak_bytes':0,'rss_peak_bytes':0,'stage':'loading'}
def watch():
 while True:
  used=pynvml.nvmlDeviceGetMemoryInfo(gpu).used
  metrics.update(gpu_peak_bytes=max(metrics['gpu_peak_bytes'],used),rss_peak_bytes=max(metrics['rss_peak_bytes'],psutil.Process().memory_info().rss))
  (outdir/'resource-metrics.json').write_text(json.dumps(metrics,indent=2))
  if used>limit:
   print('6 GiB GPU limit exceeded; stopped',flush=True);os._exit(75)
  time.sleep(.2)
threading.Thread(target=watch,daemon=True).start()
import models.svc.vevo2.vevo2_utils as vevo

# Keep the large feature extractor in RAM; use the GPU for voice generation.
def cpu_whisper(name,device):
 from transformers import WhisperConfig
 from transformers.models.whisper.modeling_whisper import WhisperEncoder
 from safetensors.torch import load_file
 folder=root.parent/'models/whisper-medium-encoder'
 model=WhisperEncoder(WhisperConfig.from_json_file(str(folder/'config.json'))).eval()
 model.load_state_dict(load_file(str(folder/'model.safetensors')),strict=True)
 model.embed_audio=lambda mel:model(mel.cpu(),return_dict=True).last_hidden_state.to(mel.device)
 return model
vevo.whisper.load_model=cpu_whisper
modeldir=root.parent/'models/Vevo2'
fm_dir=modeldir/'acoustic_modeling/fm_emilia101k_singnet7k_repa'
import json5
config=json5.loads((fm_dir/'config.json').read_text())
config['model']['coco']['whisper_stats_path']=str(fm_dir/'whisper_stats.pt')
config_path=outdir/'local-config.json'
config_path.write_text(json.dumps(config))
started=time.monotonic()
pipeline=vevo.Vevo2InferencePipeline(
 content_style_tokenizer_ckpt_path=str(modeldir/'tokenizer/contentstyle_fvq16384_12.5hz'),
 fmt_cfg_path=str(config_path),fmt_ckpt_path=str(fm_dir),
 vocoder_cfg_path=str(modeldir/'vocoder/config.json'),vocoder_ckpt_path=str(modeldir/'vocoder'),device=torch.device('cuda'))
metrics['load_seconds']=round(time.monotonic()-started,2)
metrics['stage']='converting'
print('Models loaded; converting the complete 30 second phrase',flush=True)
with torch.inference_mode():
 audio=pipeline.inference_fm(
  src_wav_path=str(Path(sys.argv[1]).resolve()),
  timbre_ref_wav_path=str(root.parent/'reference.wav'),
  use_pitch_shift=False,flow_matching_steps=32,display_audio=False)
audio=audio.detach().cpu().numpy().squeeze()
assert audio.ndim==1 and np.isfinite(audio).all() and np.max(np.abs(audio))>.01
output=outdir/'大肥鱼-追光者-Vevo2-清唱.wav'
sf.write(output,audio,24000,subtype='PCM_16')
metrics.update(stage='complete',elapsed_seconds=round(time.monotonic()-started,2),audio_seconds=len(audio)/24000,result=str(output),sample_rate=24000,source_chunks=1,steps=32)
(outdir/'result.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
print(json.dumps(metrics,ensure_ascii=False),flush=True)

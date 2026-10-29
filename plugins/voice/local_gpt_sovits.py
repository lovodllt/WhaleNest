"""Start an explicitly installed GPT-SoVITS checkout with user-supplied voice."""
import argparse
import json
from pathlib import Path
import os
import runpy
import sys
import yaml

root=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser()
p.add_argument('--source',required=True,type=Path)
p.add_argument('--reference',required=True,type=Path)
p.add_argument('--reference-text',required=True)
p.add_argument('--device',choices=['cpu','cuda'],default='cuda')
args=p.parse_args()
source=args.source.expanduser().resolve();reference=args.reference.expanduser().resolve()
if not (source/'api_v2.py').is_file() or not reference.is_file():raise SystemExit('请提供已安装依赖的 GPT-SoVITS 源码和本人可使用的参考音频')
models=root/'resources/models/gpt-sovits'
paths={'t2s_weights_path':models/'s1v3.ckpt','vits_weights_path':models/'v2Pro/s2Gv2ProPlus.pth',
    'bert_base_path':models/'chinese-roberta-wwm-ext-large','cnhuhbert_base_path':models/'chinese-hubert-base'}
if not all(path.exists() for path in paths.values()):raise SystemExit('请先从资源中心下载 GPT-SoVITS 模型')
config=root/'data/gpt-sovits.yaml';config.parent.mkdir(parents=True,exist_ok=True)
config.write_text(yaml.safe_dump({'custom':{'device':args.device,'is_half':args.device=='cuda','version':'v2ProPlus',**{k:str(v) for k,v in paths.items()}}}),encoding='utf-8')
# V2ProPlus resolves its speaker encoder relative to the upstream checkout.
speaker=source/'GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt';speaker.parent.mkdir(parents=True,exist_ok=True)
if not speaker.exists():speaker.symlink_to(models/'sv'/speaker.name)
voice_path=root/'config/voice.json';voice=json.loads(voice_path.read_text(encoding='utf-8'))
voice['gpt_sovits']={'reference_audio':str(reference),'reference_text':args.reference_text}
tmp=voice_path.with_suffix('.tmp');tmp.write_text(json.dumps(voice,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(voice_path)
if args.device=='cuda':
    import torch
    torch.cuda.set_per_process_memory_fraction(.4)
os.chdir(source);sys.path.insert(0,str(source))
sys.argv=['api_v2.py','-a','127.0.0.1','-p','9980','-c',str(config)]
runpy.run_path(str(source/'api_v2.py'),run_name='__main__')

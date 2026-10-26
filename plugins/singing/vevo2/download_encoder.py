from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests,json,struct,os,hashlib
root=Path(__file__).resolve().parent
folder=root.parent/'models/whisper-medium-encoder';folder.mkdir(exist_ok=True)
base='https://hf-mirror.com/openai/whisper-medium/resolve/main/'
r=requests.get(base+'config.json',timeout=30);r.raise_for_status();(folder/'config.json').write_bytes(r.content)
url=base+'model.safetensors'
r=requests.get(url+'?segment=header',headers={'Range':'bytes=0-524287'},timeout=(15,45));r.raise_for_status()
assert r.status_code==206
header_len=struct.unpack('<Q',r.content[:8])[0]
header=json.loads(r.content[8:8+header_len]);offset=8+header_len
weights={k:v for k,v in header.items() if k.startswith('model.encoder.')}
assert weights,'Official checkpoint has no encoder tensors'
first=min(v['data_offsets'][0] for v in weights.values());last=max(v['data_offsets'][1] for v in weights.values())
assert sum(v['data_offsets'][1]-v['data_offsets'][0] for v in weights.values())==last-first
newheader={k.removeprefix('model.encoder.'):{**v,'data_offsets':[x-first for x in v['data_offsets']]} for k,v in weights.items()}
b=json.dumps(newheader,separators=(',',':')).encode();b+=b' '*((-len(b))%8)
p=folder/'model.safetensors';tmp=p.with_suffix('.downloading')
if p.exists():print('Encoder checkpoint exists',flush=True);raise SystemExit
fd=os.open(tmp,os.O_CREAT|os.O_RDWR,0o644);prefix=8+len(b);os.ftruncate(fd,prefix+last-first);os.pwrite(fd,struct.pack('<Q',len(b))+b,0)
size=last-first
print('Official Whisper medium encoder MiB:',round(size/1024**2),flush=True)
def get(start):
 end=min(start+8*1024**2,size)-1
 for attempt in range(4):
  try:
   r=requests.get(url+'?encoder_segment='+str(start),headers={'Range':f'bytes={offset+first+start}-{offset+first+end}'},timeout=(15,45));r.raise_for_status()
   assert r.status_code==206 and len(r.content)==end-start+1
   os.pwrite(fd,r.content,prefix+start);return
  except (requests.RequestException,AssertionError):
   if attempt==3:raise
jobs=list(range(0,size,8*1024**2))
with ThreadPoolExecutor(max_workers=16) as pool:
 for i,f in enumerate(as_completed([pool.submit(get,s) for s in jobs]),1):
  f.result()
  if i%20==0:print('Encoder segments:',i,'/',len(jobs),flush=True)
os.close(fd);tmp.replace(p)
with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
(folder/'source.json').write_text(json.dumps({'source':'openai/whisper-medium/model.safetensors','tensor_prefix':'model.encoder.','tensors':len(weights),'sha256':sha},indent=2))
print('Encoder ready:',len(weights),'tensors',flush=True)

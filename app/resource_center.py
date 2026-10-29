"""Optional upstream resources; pinned files, no arbitrary URLs or automatic execution."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
import urllib.request
import base64
import io
import re

ROOT=Path(__file__).resolve().parents[1]

class Resources:
    def __init__(self,root=ROOT):
        self.root=Path(root)
        self.catalog=json.loads((self.root/'config/resources.json').read_text(encoding='utf-8'))
        self.path=self.root/'data/resource-jobs.json'
        self.jobs=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        for job in self.jobs.values():
            if job['status']=='downloading':job.update(status='interrupted',error='上次下载中断，可重新下载；已校验文件会复用')
        self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=1)

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.jobs,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)

    def state(self):
        with self.lock:
            return {'resources':[{**{k:v for k,v in item.items() if k!='files'},'bytes':sum(f['size'] for f in item['files']),
                'file_count':len(item['files']),'job':dict(self.jobs.get(item['id'],{'status':'not_installed','completed_bytes':0}))} for item in self.catalog],
                'persona_exists':(self.root/'resources/persona.md').is_file()}

    def start(self,ident):
        with self.lock:
            item=next((item for item in self.catalog if item['id']==ident),None)
            if not item:raise ValueError('没有此资源')
            if any(j['status']=='downloading' for j in self.jobs.values()):raise ValueError('已有资源正在下载，请稍后再试')
            self.jobs[ident]={'status':'downloading','completed_bytes':0,'error':'','started_at':int(time.time())};self._save()
            self.pool.submit(self._download,item)
        return self.state()

    def _target(self,name):
        target=(self.root/name).resolve()
        if not target.is_relative_to(self.root.resolve()) or name.startswith('/') or '..' in Path(name).parts:raise ValueError('资源目标路径无效')
        return target

    @staticmethod
    def verify(path,file):
        if path.stat().st_size!=file['size']:return False
        digest=hashlib.sha256() if file.get('sha256') else hashlib.sha1(b'blob '+str(file['size']).encode()+b'\0')
        with path.open('rb') as stream:
            while chunk:=stream.read(1024*1024):digest.update(chunk)
        return digest.hexdigest()==(file.get('sha256') or file['git_blob_sha1'])

    def _download(self,item):
        ident=item['id'];completed=0
        try:
            for file in item['files']:
                path=self._target(file['target']);path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    if not self.verify(path,file):raise ValueError('已有文件与所选版本不同，未覆盖：'+file['target'])
                else:
                    temporary=path.with_suffix(path.suffix+'.partial')
                    try:
                        request=urllib.request.Request(file['url'],headers={'User-Agent':'Dafeiyu-resource-manager/0.1.0'})
                        with urllib.request.urlopen(request,timeout=45) as response,temporary.open('wb') as output:
                            received=0
                            while chunk:=response.read(1024*1024):
                                received+=len(chunk)
                                if received>file['size']:raise ValueError('下载文件超过清单大小')
                                output.write(chunk)
                                with self.lock:self.jobs[ident]['completed_bytes']=completed+received
                        if not self.verify(temporary,file):raise ValueError('文件完整性校验失败：'+path.name)
                        temporary.replace(path)
                    finally:temporary.unlink(missing_ok=True)
                completed+=file['size']
                with self.lock:self.jobs[ident]['completed_bytes']=completed;self._save()
            if item.get('character'):
                char=item['character'];folder=self.root/'resources/characters'/char['name']
                path=folder/'设定.json'
                if not path.exists():path.write_text(json.dumps({**char,'appearance':'','reference_images':[]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            with self.lock:self.jobs[ident].update(status='ready',finished_at=int(time.time()));self._save()
        except Exception as error:
            with self.lock:self.jobs[ident].update(status='failed',error=str(error)[:300]);self._save()

    def activate_persona(self,ident):
        item=next((i for i in self.catalog if i['id']==ident and i['kind']=='persona'),None)
        if not item or self.jobs.get(ident,{}).get('status')!='ready':raise ValueError('请先下载人设')
        text='\n\n'.join(self._target(f['target']).read_text(encoding='utf-8') for f in item['files'] if '/dafeiyu/' in f['target'] and f['target'].endswith('.md'))
        path=self.root/'resources/persona.md'
        if path.exists():raise ValueError('已有自定义人设，未覆盖。可在资源页编辑，或先自行备份移走')
        path.write_text(text,encoding='utf-8')
        return self.state()

    def import_character(self,body):
        from PIL import Image
        name=body.get('name','')
        if not isinstance(name,str):raise ValueError('人物名须为文字')
        name=name.strip()
        if not re.fullmatch(r'[\w\u4e00-\u9fff -]{1,40}',name) or '..' in name:raise ValueError('请使用不含路径符号的角色名')
        raw=base64.b64decode(body.get('data',''),validate=True)
        if len(raw)>12*1024**2:raise ValueError('单张图片最多12MiB')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>40_000_000:raise ValueError('仅支持尺寸合理的 PNG、JPEG、WebP 图片')
            extension={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[image.format];image.verify()
        folder=self.root/'resources/characters'/name;images=folder/'images';images.mkdir(parents=True,exist_ok=True)
        prefix='设定集-' if '设定集' in str(body.get('filename','')) else '参考-'
        (images/(prefix+hashlib.sha256(raw).hexdigest()[:16]+'.'+extension)).write_bytes(raw)
        config=folder/'设定.json'
        if not config.exists():config.write_text(json.dumps({'id':'custom-'+hashlib.sha256(name.encode()).hexdigest()[:12],'name':name,'aliases':[name],'appearance':'','reference_images':[]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return {'saved':True,'name':name}

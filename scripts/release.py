"""Create clean source installers and verify initialization from the staged files."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
def included(path):
    rel=path.relative_to(ROOT)
    if not path.is_file() or path.is_symlink():return False
    if any(part in {'data','.venv','__pycache__','.git','node_modules','dist'} for part in rel.parts):return False
    if rel.parts[0]=='resources':return False
    if str(rel) in {'config/chat.json','config/voice.json','config/runtime.json','config/secrets.json'}:return False
    if any(str(rel).startswith(prefix) for prefix in ['plugins/singing/models/','plugins/singing/seed-vc-main/','plugins/singing/converted','plugins/singing/vevo2/models/','plugins/singing/vevo2/Amphion/']):return False
    if str(rel) in {'docs/assets/whalenest-hero.png','docs/assets/workspace-preview.png','web/assets/whale-workroom.png','web/assets/whale-clock.png','web/assets/whale-tokens.png','web/icons/icon-192.png','web/icons/icon-512.png','web/icons/apple-touch-icon.png'}:return True
    if str(rel.parent)=='vendor/webox/docker/helpers/ui_templates' and path.suffix=='.png':return True
    if path.suffix.lower() in {'.deb','.pyc','.partial','.pth','.ckpt','.safetensors','.bin','.db','.sqlite3','.wav','.mp3','.png','.jpg','.jpeg','.webp','.gif'}:return False
    if rel.name.startswith('.') and rel.name not in {'.gitignore','.gitattributes'}:return False
    return rel.name!='MANIFEST.sha256'

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT.parent/'release-artifacts');args=p.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    name='whalenest-'+VERSION
    with tempfile.TemporaryDirectory(prefix='whalenest-release-') as temp:
        stage=Path(temp)/name;stage.mkdir()
        for path in ROOT.rglob('*'):
            if not included(path):continue
            rel=path.relative_to(ROOT);dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
            if path.suffix in {'.py','.mjs','.js','.yml','.yaml','.json','.md','.sh','.ps1','.html','.go'}:
                text=path.read_text()
                if re.search(r'/home/[A-Za-z0-9_.-]+/|wxid_[a-z0-9]{12,}',text) or any(v and v in text for v in os.environ.get('DAFEIYU_PRIVATE_MARKERS','').split(';')):raise ValueError('本机专属信息未清除：'+str(rel))
        smoke=Path(temp)/'解压校验 有空格'/name;shutil.copytree(stage,smoke)
        subprocess.run([sys.executable,'scripts/manage.py','init'],cwd=smoke,check=True)
        settings=json.loads((smoke/'config/chat.json').read_text())
        assert settings['chats']=={} and settings['reply_paused'] and not (smoke/'resources/persona.md').exists()
        assert (smoke/'data/chat/bridge.sqlite3').is_file()
        checks={'clean_initialization':True,'path_with_spaces':True,'private_runtime_data_included':False,'bundled_models':False,'bundled_persona':False}
        (stage/'docs/ARCHIVE_CHECK.json').write_text(json.dumps(checks,indent=2)+'\n')
        files=sorted(path for path in stage.rglob('*') if path.is_file())
        hashes={str(path.relative_to(stage)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        (stage/'MANIFEST.sha256').write_text(''.join(f'{digest}  {rel}\n' for rel,digest in hashes.items()))
        files.append(stage/'MANIFEST.sha256')
        zipped=output/(name+'.zip');compressed=output/(name+'.tar.gz')
        with zipfile.ZipFile(zipped,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for path in files:archive.write(path,name+'/'+str(path.relative_to(stage)))
        with tarfile.open(compressed,'w:gz',compresslevel=9) as archive:archive.add(stage,arcname=name)
        with zipfile.ZipFile(zipped) as archive:
            assert archive.testzip() is None
            for rel,digest in hashes.items():assert hashlib.sha256(archive.read(name+'/'+rel)).hexdigest()==digest
        with tarfile.open(compressed) as archive:
            for rel,digest in hashes.items():assert hashlib.sha256(archive.extractfile(name+'/'+rel).read()).hexdigest()==digest
        (output/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in [zipped,compressed]))
        summary={**checks,'archive_integrity':True,'source_files':len(files),'archives':[{'file':path.name,'bytes':path.stat().st_size} for path in [zipped,compressed]]}
        (output/'打包校验.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()

"""Apply the retained 40-second context setting to the pinned Seed-VC source."""
from pathlib import Path
import re

path=Path(__file__).resolve().parent/'seed-vc-main/inference.py'
text=path.read_text()
text,n=re.subn(r'max_seq_length\s*=\s*(?:2048|8192)','max_seq_length=4096',text,count=1)
text,m=re.subn(r'max_context_window\s*=\s*sr\s*//\s*hop_length\s*\*\s*\d+','max_context_window = sr // hop_length * 40',text,count=1)
if n!=1 or m!=1:raise SystemExit('所选上游版本与补丁位置不符，未修改；请核对原文件')
path.write_text(text)
print('已设为40秒上下文和4096缓存帧，适合保留的30秒整段换声方案')

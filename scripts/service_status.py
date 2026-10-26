import json,os,sys
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'data/run/children.json'
d=json.loads(p.read_text()) if p.exists() else {}
pid=d.get(sys.argv[1])
try:
 if pid:os.kill(pid,0);print('active')
 else:print('inactive')
except ProcessLookupError:print('inactive')

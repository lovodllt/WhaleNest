import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from runtime_support import owned_process
p=Path(__file__).resolve().parents[1]/'data/run/children.json'
d=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
print('active' if owned_process(d.get(sys.argv[1])) is not None else 'inactive')

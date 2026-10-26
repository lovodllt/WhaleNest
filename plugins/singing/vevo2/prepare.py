from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
source=root/'Amphion'
if source.exists():raise SystemExit('Amphion 目录已存在，未覆盖')
source.mkdir()
for args in [['git','init',str(source)],['git','-C',str(source),'remote','add','origin','https://github.com/open-mmlab/Amphion.git'],['git','-C',str(source),'fetch','--depth=1','origin','26f6883110181f1dbfe95c70a7c7dbaf4de5f42a'],['git','-C',str(source),'checkout','FETCH_HEAD']]:subprocess.run(args,check=True)
print('实验源码已准备；模型权重请从资源中心单独下载，未运行推理')

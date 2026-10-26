"""Finish private mobile access after the owner signs in to Tailscale."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def main():
    bundled = []
    binary = os.environ.get('DAFEIYU_TAILSCALE_BIN') or shutil.which('tailscale') or (str(bundled[-1]) if bundled else '')
    if not binary:
        raise SystemExit('请先安装 Tailscale')
    socket = os.environ.get('DAFEIYU_TAILSCALE_SOCKET')
    command = [binary]+(['--socket='+socket] if socket else [])
    result = subprocess.run(command+['status','--json'],capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise SystemExit('无法读取 Tailscale 状态，请先启动电脑端连接服务')
    status = json.loads(result.stdout)
    if status.get('BackendState') != 'Running':
        print('电脑端尚未完成登录：'+str(status.get('BackendState')))
        if status.get('AuthURL'):print(status['AuthURL'])
        return 1
    own = status['Self']
    login = status.get('User',{}).get(str(own['UserID']),{}).get('LoginName')
    hostname = own.get('DNSName','').rstrip('.')
    if not login or not hostname.endswith('.ts.net'):
        raise SystemExit('尚未获得个人账号和私有 DNS 地址，暂不开放手机入口')
    origin = 'https://'+hostname
    try:
        result = subprocess.run(command+['serve','--bg','--https=443','--yes','http://127.0.0.1:8878'],
                                capture_output=True,text=True,timeout=45)
    except subprocess.TimeoutExpired as error:
        for value in (error.stdout,error.stderr):
            if value:print(value.decode() if isinstance(value,bytes) else value)
        print('私有 HTTPS 尚未配置完成；如上方提供授权链接，请完成后重试')
        return 1
    if result.returncode:
        print(result.stdout+result.stderr)
        return 1
    serving = subprocess.run(command+['serve','status','--json'],capture_output=True,text=True,check=True,timeout=10)
    config = json.loads(serving.stdout)
    handlers = config.get('Web',{}).get(urlsplit(origin).netloc+':443',{}).get('Handlers',{})
    if handlers.get('/',{}).get('Proxy') != 'http://127.0.0.1:8878' or any(config.get('AllowFunnel',{}).values()):
        raise SystemExit('未确认私有 HTTPS 入口，暂不保存手机地址')
    path = ROOT/'data/console-access.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'origin':origin,'allowed_login':login},ensure_ascii=False,indent=2)+'\n')
    temporary.chmod(0o600);temporary.replace(path)
    print('手机私有访问地址：'+origin)
    print('安卓手机连接同一账号的 Tailscale 后，用 Chrome 或 Edge 打开此地址')
    return 0


if __name__=='__main__':
    sys.exit(main())

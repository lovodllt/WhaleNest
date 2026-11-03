"""Explicit one-call entry point; no background auto-dial or auto-answer service."""
import argparse
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from manage import environment
os.environ.update(environment())
sys.path.insert(0,str(ROOT/'app'))
from runtime_support import ensure_utf8
ensure_utf8()
from voice_call import NativeCallAudio, emit, run, settings


def main():
    parser = argparse.ArgumentParser(description='微信单次主人语音通话（Linux / WSL2）')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--probe',action='store_true',help='只读检查通话控件，不接听、不拨号')
    mode.add_argument('--check',action='store_true',help='只检查配置和依赖，不连接微信')
    mode.add_argument('--wait',action='store_true',help='限时等待绑定主人来电，只接一次')
    mode.add_argument('--dial-owner',action='store_true',help='明确向主人拨一次，不自动重拨')
    parser.add_argument('--wait-seconds',type=int,default=180)
    parser.add_argument('--max-call-seconds',type=int,default=600)
    args = parser.parse_args()
    if not 1<=args.wait_seconds<=3600 or not 1<=args.max_call_seconds<=3600:
        parser.error('等待和通话时限必须在1–3600秒内')
    if os.name=='nt':
        parser.error('实时通话请在 WSL2 内运行，Windows原生暂不支持')
    def stop(_signum,_frame):
        raise KeyboardInterrupt('call worker stopped')
    signal.signal(signal.SIGTERM,stop)
    config = settings()
    if args.probe:
        frames = NativeCallAudio(config.get('container','dafeiyu-wechat'),'probe').controls()
        emit('probe',frames=frames)
    elif args.check:
        from voice_call import dependencies,validate
        from group_bridge import connect_db,get_meta
        with connect_db() as db:
            validate(config,get_meta(db,'binding'))
        dependencies(config)
        emit('dependencies_ready')
    else:
        run(config,dial=args.dial_owner,wait_seconds=args.wait_seconds,max_seconds=args.max_call_seconds)


if __name__=='__main__':
    main()

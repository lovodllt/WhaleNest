#!/usr/bin/env python3
"""Run inside Webox: select one voice bubble and request native text conversion."""
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from ui_accessible import connect, find_controls, header_matches, ACC, COMP, PROPS, VISIBLE, dbus
from ui_locator import message_point


def command(*args):
    return subprocess.check_output(args, text=True, timeout=4).strip()


def window(remark):
    try:
        windows = command('xdotool','search','--onlyvisible','--class','wechat').splitlines()
    except subprocess.CalledProcessError:
        return None
    return next((w for w in windows if re.fullmatch(re.escape(remark)+r'(?:\s*\(\d+\))?',
                         command('xdotool','getwindowname',w)) or header_matches(w,remark)), None)


def open_chat(remark):
    win = window(remark)
    if not win:
        windows = command('xdotool','search','--onlyvisible','--class','wechat').splitlines()
        main = next(w for w in windows if command('xdotool','getwindowname',w) in ('微信','WeChat'))
        command('xdotool','windowactivate',main)
        result = subprocess.run(['python3','/webox/state/weagent/ui_accessible.py','chat',remark], capture_output=True, timeout=6)
        if result.returncode:
            command('xdotool','key','--clearmodifiers','ctrl+f','ctrl+a','BackSpace')
            subprocess.run(['xclip','-selection','clipboard','-i'], input=remark.encode(), check=True, timeout=3)
            command('xdotool','key','--clearmodifiers','ctrl+v')
            time.sleep(.3)
            command('xdotool','key','Return')
            for _ in range(10):
                result = subprocess.run(['python3','/webox/state/weagent/ui_accessible.py','chat',remark], capture_output=True, timeout=6)
                if result.returncode == 0:
                    break
                time.sleep(.1)
        for _ in range(20):
            win = window(remark)
            if win:
                break
            time.sleep(.1)
    if not win:
        raise RuntimeError('Target voice conversation did not open')
    command('xdotool','windowactivate',win)
    return command('xdotool','getwindowname',win)


def voices(title):
    bus, roots = connect()
    queue = []
    for _, service, path in roots:
        app = bus.get_object(service,path,introspect=False)
        for service, path in app.GetChildren(dbus_interface=ACC,timeout=2):
            obj = bus.get_object(service,path,introspect=False)
            if str(obj.Get(ACC,'Name',dbus_interface=PROPS,timeout=2)) == title:
                queue.append((str(service),str(path)))
    seen, found = set(), []
    while queue and len(seen) < 1500:
        service, path = queue.pop(0)
        if (service,path) in seen:
            continue
        seen.add((service,path))
        obj = bus.get_object(service,path,introspect=False)
        name = str(obj.Get(ACC,'Name',dbus_interface=PROPS,timeout=2))
        match = re.match(r'^语音(\d+)"秒', name)
        if match and str(obj.GetRoleName(dbus_interface=ACC,timeout=2)) == 'list item':
            extent = [int(v) for v in obj.GetExtents(dbus.UInt32(0),dbus_interface=COMP,timeout=2)]
            state = int(obj.GetState(dbus_interface=ACC,timeout=2)[0])
            if state & VISIBLE == VISIBLE and extent[2] > 0 and extent[3] > 0:
                found.append((int(match[1]),extent))
        queue.extend((str(s),str(p)) for s,p in obj.GetChildren(dbus_interface=ACC,timeout=2))
    return sorted(found,key=lambda v:v[1][1])


def main():
    request = json.load(sys.stdin)
    with open('/webox/state/weagent/ui-send.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        title = open_chat(request['remark'])
        rows = voices(title)
        if request['offset'] >= len(rows):
            raise RuntimeError('Requested voice is not visible')
        seconds, bounds = rows[-1-request['offset']]
        if seconds != request['seconds']:
            raise RuntimeError('Voice duration does not match')
        win = window(request['remark'])
        x,y = message_point(int(win),bounds,request['outgoing'])
        command('xdotool','mousemove',str(x),str(y),'click','3')
        time.sleep(.1)
        choices = [c for c in find_controls('语音转文字') if c['Visible'] and c['Role']=='menu item']
        if len(choices) != 1:
            command('xdotool','key','Escape')
            raise RuntimeError('Voice conversion menu is unavailable')
        x,y,width,height = choices[0]['Extents']
        command('xdotool','mousemove',str(x+width//2),str(y+height//2),'click','1')
    print(json.dumps({'ret':0}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error':str(exc)}))
        sys.exit(1)

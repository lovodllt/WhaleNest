"""Bound native call controls to the observed owner/call window."""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, '/webox/state/weagent')
from ui_accessible import ACC, COMP, PROPS, VISIBLE, connect, dbus, find_controls

ACCEPT = {'接听', '接受', '接听语音通话', 'Accept', 'Answer'}
END = {'挂断', '结束通话', 'Hang Up', 'End Call'}
DIAL = {'语音通话'}


def snapshot():
    bus, roots = connect()
    frames = []
    for _, service, path in roots:
        app = bus.get_object(service, path, introspect=False)
        for srv, frame_path in app.GetChildren(dbus_interface=ACC, timeout=2):
            try:
                frame_obj = bus.get_object(str(srv), str(frame_path), introspect=False)
                title = str(frame_obj.Get(ACC, 'Name', dbus_interface=PROPS, timeout=2))
            except dbus.DBusException:
                continue
            queue = [(str(srv), str(frame_path), 0)]
            labels, buttons, seen = [], [], set()
            while queue and len(seen) < 1500:
                srv, path, depth = queue.pop(0)
                if (srv, path) in seen:
                    continue
                seen.add((srv, path))
                try:
                    obj = bus.get_object(srv, path, introspect=False)
                    name = str(obj.Get(ACC, 'Name', dbus_interface=PROPS, timeout=2))
                    state = int(obj.GetState(dbus_interface=ACC, timeout=2)[0])
                    visible = state & VISIBLE == VISIBLE
                    role = str(obj.GetRoleName(dbus_interface=ACC, timeout=2))
                    if visible and name and role in ('label', 'text', 'frame', 'dialog'):
                        labels.append(name)
                    allowed = ACCEPT | END | (DIAL if request.get('action') in ('dial', 'dial_probe') else set())
                    if visible and role == 'push button' and name in allowed:
                        box = [int(v) for v in obj.GetExtents(dbus.UInt32(0), dbus_interface=COMP, timeout=2)]
                        if box[2] > 0 and box[3] > 0:
                            buttons.append({'name': name, 'path': path, 'box': box})
                    if depth < 32:
                        queue.extend((str(s), str(p), depth + 1) for s, p in obj.GetChildren(dbus_interface=ACC, timeout=2))
                except dbus.DBusException:
                    continue
            if buttons:
                frames.append({'frame': str(frame_path), 'title': title, 'labels': labels[:30], 'buttons': buttons})
    return frames


request = json.loads(os.environ.get('WHALENEST_CALL_REQUEST', '{}'))
frames = snapshot()
if request.get('action', 'probe') not in ('probe', 'dial_probe'):
    frame = next((f for f in frames if f['frame'] == request['frame']), None)
    if not frame:
        raise RuntimeError('通话窗口已消失')
    names = ACCEPT if request['action'] == 'accept' else DIAL if request['action'] == 'dial' else END if request['action'] == 'hangup' else set()
    buttons = [b for b in frame['buttons'] if b['name'] in names]
    if len(buttons) != 1:
        raise RuntimeError('没有唯一的通话控制按钮')
    if request['action'] == 'accept' and not set(request['caller_names']) & set(frame['labels']):
        raise RuntimeError('来电姓名与指定联系人不匹配')
    if request['action'] == 'dial' and frame['title'] not in request['caller_names']:
        raise RuntimeError('拨号必须来自绑定本人的独立私聊窗口')
    windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name', '^' + re.escape(frame['title']) + '$'], text=True).split()
    if len(windows) != 1:
        raise RuntimeError('不能唯一定位通话窗口')
    subprocess.run(['xdotool', 'windowactivate', '--sync', windows[0]], check=True, timeout=3)
    if subprocess.check_output(['xdotool', 'getactivewindow'],text=True).strip() != windows[0]:
        raise RuntimeError('通话窗口尚未激活')
    x, y, w, h = buttons[0]['box']
    subprocess.run(['xdotool', 'mousemove', str(x+w//2), str(y+h//2), 'click', '1'], check=True, timeout=3)
    if request['action'] == 'dial':
        menu = []
        deadline = time.monotonic()+2
        while len(menu) != 1 and time.monotonic() < deadline:
            menu = [item for item in find_controls('语音通话') if item['Role'] == 'menu item' and item['Visible']]
            if len(menu) != 1:time.sleep(.1)
        if len(menu) != 1:
            raise RuntimeError('没有唯一的语音通话菜单')
        x, y, w, h = menu[0]['Extents']
        subprocess.run(['xdotool', 'mousemove', str(x+w//2), str(y+h//2), 'click', '1'], check=True, timeout=3)
print(json.dumps(frames, ensure_ascii=False))

#!/usr/bin/env python3
"""Select the named quote action and verify its preview in the current client."""
import base64
import subprocess
import sys
import time

from ui_accessible import find_controls, connect, ACC, PROPS


def click(control):
    x,y,width,height = control['Extents']
    subprocess.run(['xdotool','mousemove',str(x+width//2),str(y+height//2),'click','1'],check=True)


def named(name, role, title=None):
    return [c for c in find_controls(name,window_title=title) if c['Visible'] and c['Role']==role]


def cleanup_forward():
    if any(c['Visible'] for c in find_controls('发送给')):
        controls = named('取消','push button')
        if len(controls) != 1:
            raise RuntimeError('Cannot close the unexpected forwarding dialog')
        click(controls[0])
        if any(c['Visible'] for c in find_controls('发送给')):
            raise RuntimeError('Forwarding dialog did not close')


def cancel(title):
    controls = named('删除引用消息','push button',title)
    if len(controls)>1:
        raise RuntimeError('Ambiguous quote preview')
    if controls:
        click(controls[0])
    if named('删除引用消息','push button',title):
        raise RuntimeError('Quote preview did not close')


def preview_matches(title,text):
    bus, roots = connect()
    queue = []
    for _,service,path in roots:
        app = bus.get_object(service,path,introspect=False)
        for service,path in app.GetChildren(dbus_interface=ACC,timeout=2):
            obj = bus.get_object(service,path,introspect=False)
            if str(obj.Get(ACC,'Name',dbus_interface=PROPS,timeout=2))==title:
                queue.append((str(service),str(path)))
    seen = set()
    while queue and len(seen)<1500:
        service,path = queue.pop(0)
        if (service,path) in seen:
            continue
        seen.add((service,path))
        obj = bus.get_object(service,path,introspect=False)
        name = str(obj.Get(ACC,'Name',dbus_interface=PROPS,timeout=2))
        if name.startswith('引用 ') and name.partition(' : ')[2]==text:
            return True
        queue.extend((str(s),str(p)) for s,p in obj.GetChildren(dbus_interface=ACC,timeout=2))
    return False


def prepare(title,text):
    cancel(title)
    rows = named(text,'list item',title)
    if len(rows)!=1:
        raise RuntimeError('Original message is not uniquely visible; ordinary reply required')
    x,y,width,height = rows[0]['Extents']
    subprocess.run(['xdotool','mousemove',str(x+100),str(y+height-25),'click','3'],check=True)
    time.sleep(.1)
    choices = named('引用','menu item')
    if len(choices)!=1:
        editors = named('输入','text',title)
        if len(editors)==1:
            click(editors[0])
        raise RuntimeError('Named quote menu is unavailable')
    click(choices[0])
    if not named('删除引用消息','push button',title) or not preview_matches(title,text):
        cancel(title)
        raise RuntimeError('Quote preview does not match the requested message')


if __name__=='__main__':
    try:
        cleanup_forward()
        action = sys.argv[1]
        if action!='cleanup':
            title = subprocess.check_output(['xdotool','getwindowname',sys.argv[2]],text=True,timeout=3).strip()
            if action=='prepare':
                prepare(title,base64.b64decode(sys.argv[3]).decode())
            elif action=='cancel':
                cancel(title)
            else:
                raise ValueError('Unknown quote action')
    except Exception as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)

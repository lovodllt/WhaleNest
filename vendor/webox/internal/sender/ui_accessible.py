#!/usr/bin/env python3
"""Find exact WeChat control names, or click one visible named button."""
import json
import os
from pathlib import Path
import subprocess
import sys

import dbus

ACC = "org.a11y.atspi.Accessible"
COMP = "org.a11y.atspi.Component"
ACTION = "org.a11y.atspi.Action"
PROPS = "org.freedesktop.DBus.Properties"
ROOT = "/org/a11y/atspi/accessible/root"
VISIBLE = (1 << 25) | (1 << 30)  # AT-SPI SHOWING and VISIBLE.


def connect():
    for pid in Path("/proc").glob("[0-9]*"):
        try:
            if (pid / "cmdline").read_bytes().split(b"\0")[0] == b"/webox/wechat/opt/wechat/wechat":
                break
        except OSError:
            continue
    else:
        raise RuntimeError("WeChat process not found")
    address = next(v.split(b"=", 1)[1].decode() for v in (pid / "environ").read_bytes().split(b"\0")
                   if v.startswith(b"DBUS_SESSION_BUS_ADDRESS="))
    if os.geteuid() == 0:
        owner = pid.stat()
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)
    session = dbus.bus.BusConnection(address)
    launcher = session.get_object("org.a11y.Bus", "/org/a11y/bus", introspect=False)
    bus = dbus.bus.BusConnection(str(launcher.GetAddress(dbus_interface="org.a11y.Bus", timeout=3)))
    daemon = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus", introspect=False)
    registry = bus.get_object("org.a11y.atspi.Registry", ROOT, introspect=False)
    roots = [(0, str(s), str(p)) for s, p in registry.GetChildren(dbus_interface=ACC, timeout=2)
             if int(daemon.GetConnectionUnixProcessID(s, dbus_interface="org.freedesktop.DBus", timeout=2)) == int(pid.name)]
    return bus, roots


def find_controls(names, first_line=False, window_title=None):
    names = {names} if isinstance(names, str) else set(names)
    bus, queue = connect()
    if window_title is not None:
        frames = []
        for _, service, path in queue:
            app = bus.get_object(service, path, introspect=False)
            for child_service, child_path in app.GetChildren(dbus_interface=ACC, timeout=2):
                child = bus.get_object(child_service, child_path, introspect=False)
                if str(child.Get(ACC, 'Name', dbus_interface=PROPS, timeout=2)) == window_title:
                    frames.append((0, str(child_service), str(child_path)))
        queue = frames
    seen, matches = set(), []
    while queue and len(seen) < 3000:
        depth, service, path = queue.pop(0)
        if (service, path) in seen:
            continue
        seen.add((service, path))
        obj = bus.get_object(service, path, introspect=False)
        name = str(obj.Get(ACC, "Name", dbus_interface=PROPS, timeout=2))
        if (name.split('\n', 1)[0] if first_line else name) in names:
            role = str(obj.GetRoleName(dbus_interface=ACC, timeout=2))
            interfaces = obj.GetInterfaces(dbus_interface=ACC, timeout=2)
            extents = [int(v) for v in obj.GetExtents(dbus.UInt32(0), dbus_interface=COMP, timeout=2)] if COMP in interfaces else None
            actions = [[str(v) for v in a] for a in obj.GetActions(dbus_interface=ACTION, timeout=2)] if ACTION in interfaces else []
            state = int(obj.GetState(dbus_interface=ACC, timeout=2)[0])
            visible = state & VISIBLE == VISIBLE and extents is not None and extents[2] > 0 and extents[3] > 0
            data = dict(Name=name, Role=role, Path=path, Extents=extents, Actions=actions, Visible=visible)
            matches.append(data)
        if depth < 32:
            queue.extend((depth + 1, str(s), str(p)) for s, p in obj.GetChildren(dbus_interface=ACC, timeout=2))
    return matches


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"button", "find", "chat"}:
        raise RuntimeError("usage: ui_accessible.py button|find|chat NAME")
    mode, expected = sys.argv[1:]
    matches = find_controls(expected, first_line=mode == 'chat')
    if mode == "find":
        for match in matches:
            print(json.dumps(match, ensure_ascii=False))
        return 0 if matches else 1
    role = 'list item' if mode == 'chat' else 'push button'
    matches = [match for match in matches if match['Role'] == role and match['Visible']]
    if len(matches) != 1:
        raise RuntimeError(f"expected one visible {role} {expected!r}, found {len(matches)}")
    x, y, width, height = matches[0]["Extents"]
    os.environ.setdefault("DISPLAY", ":1")
    if mode == 'chat':
        subprocess.run(['xdotool', 'mousemove', str(x+width//2), str(y+height//2), 'click', '3'], check=True)
        menu = [m for m in find_controls('独立窗口显示') if m['Role'] == 'menu item' and m['Visible']]
        if len(menu) != 1:
            raise RuntimeError('independent chat menu is unavailable')
        x, y, width, height = menu[0]['Extents']
    subprocess.run(["xdotool", "mousemove", str(x + width // 2), str(y + height // 2), 'click', '1'], check=True)
    print(json.dumps(matches[0], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, dbus.DBusException, StopIteration) as error:
        print(f"AT-SPI: {error}", file=sys.stderr)
        sys.exit(1)

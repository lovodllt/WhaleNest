#!/usr/bin/env python3
"""Find or click a configured control inside one window."""
import argparse
import json
import os
from pathlib import Path
import subprocess

LAYOUT = Path('/webox/state/weagent/ui_layout.json')

def merge_layout(defaults, current):
    merged = defaults | current
    for key in defaults.keys() & current.keys():
        if isinstance(defaults[key], dict) and isinstance(current[key], dict):
            merged[key] = merge_layout(defaults[key], current[key])
    return merged


def window_geometry(window):
    output = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', str(window)], text=True, timeout=3)
    values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    return tuple(int(values[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))


def capture_window(window):
    return subprocess.check_output([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
        '-draw_mouse', '0', '-window_id', str(window), '-i', os.environ.get('DISPLAY', ':1'),
        '-frames:v', '1', '-threads', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'], timeout=8)


def find_control(window, layout_path, key, roi=None):
    layout_path = Path(layout_path)
    layout = json.loads(layout_path.read_text())
    result = {'matched': False, 'window': window, 'control': key, 'method': None, 'bbox': None}
    control = layout.get('controls', {}).get(key)
    if not control:
        return result | {'reason': 'control_not_configured'}
    names = control.get('names', [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError('Control names must be a list of exact strings')
    wx, wy, width, height = window_geometry(window)
    if names:
        try:
            from ui_accessible import dbus, find_controls
        except ImportError as error:
            result['accessibility_error'] = str(error)
        else:
            try:
                title = subprocess.check_output(['xdotool', 'getwindowname', str(window)], text=True, timeout=3).rstrip('\n')
                matches = find_controls(names, window_title=title)
            except (OSError, RuntimeError, StopIteration, dbus.DBusException) as error:
                result['accessibility_error'] = str(error)
            else:
                visible = []
                for match in matches:
                    if not match['Visible'] or control.get('role') and match['Role'] != control['role']:
                        continue
                    x, y, w, h = match['Extents']
                    if wx <= x and wy <= y and x+w <= wx+width and y+h <= wy+height:
                        visible.append(match)
                if len(visible) > 1:
                    return result | {'method': 'accessible', 'reason': 'ambiguous_controls', 'count': len(visible)}
                if visible:
                    x, y, w, h = visible[0]['Extents']
                    return result | {'matched': True, 'method': 'accessible', 'bbox': [x-wx, y-wy, w, h], 'reason': 'matched'}
    filename = control.get('template')
    if roi is None:
        roi = control.get('roi')
        if roi is None and 'region' in control:
            left, top, right, bottom = control['region']
            if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
                raise ValueError('Template region must use normalized window bounds')
            x, y = round(left*width), round(top*height)
            roi = [x, y, round(right*width)-x, round(bottom*height)-y]
    if not filename:
        return result | {'reason': 'no_control_or_template_configured'}
    if Path(filename).name != filename:
        raise ValueError('Template must name a file inside template_dir')
    import cv2
    import numpy as np
    from ui_template import locate
    template_path = layout_path.parent / layout.get('template_dir', 'ui_templates') / filename
    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ValueError('Configured template could not be read')
    image = cv2.imdecode(np.frombuffer(capture_window(window), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError('Window screenshot could not be decoded')
    match = locate(image, template, roi, control.get('threshold', layout.get('threshold', 0.9)),
                   control.get('scales', layout.get('scales', [1.0])))
    return result | match | {'method': 'template'}


def message_point(window, extents, outgoing=False, layout_path=LAYOUT):
    wx, wy, width, height = window_geometry(window)
    x, y, w, h = extents
    left, top = max(0, x-wx), max(0, y-wy)
    right, bottom = min(width, x+w-wx), min(height, y+h-wy)
    if right <= left or bottom <= top:
        raise RuntimeError('Message is not visible')
    key = 'bubble_outgoing' if outgoing else 'bubble_incoming'
    result = find_control(window, layout_path, key, [left, top, right-left, bottom-top])
    if not result['matched']:
        raise RuntimeError('Message bubble template did not uniquely match the intended row')
    bx, by, bw, bh = result['bbox']
    return wx+bx+round(bw*(0.2 if outgoing else 0.8)), wy+by+bh//2


def click_control(window, key, layout_path=LAYOUT):
    result = find_control(window, layout_path, key)
    if not result['matched']:
        raise RuntimeError('Control did not uniquely match: '+key)
    x, y, width, height = result['bbox']
    subprocess.run(['xdotool', 'mousemove', '--window', str(window), str(x+width//2),
                    str(y+height//2), 'click', '1'], check=True, timeout=3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--layout', required=True)
    parser.add_argument('action', choices=['find', 'click'])
    parser.add_argument('key')
    args = parser.parse_args()
    try:
        result = (click_control(args.window, args.key, args.layout) if args.action == 'click'
                  else find_control(args.window, args.layout, args.key))
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as error:
        print(json.dumps({'matched': False, 'window': args.window, 'bbox': None, 'error': str(error)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Find or click a configured control inside one window."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def window_geometry(window):
    output = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', str(window)], text=True, timeout=3)
    values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    return tuple(int(values[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))


def capture_window(window):
    return subprocess.check_output([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
        '-draw_mouse', '0', '-window_id', str(window), '-i', os.environ.get('DISPLAY', ':1'),
        '-frames:v', '1', '-threads', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'], timeout=8)


def find_control(window, layout_path, key):
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
    filename, roi = control.get('template'), control.get('roi')
    if not filename or roi is None:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--layout', required=True)
    parser.add_argument('action', choices=['find', 'click'])
    parser.add_argument('key')
    args = parser.parse_args()
    try:
        result = find_control(args.window, args.layout, args.key)
        if result['matched'] and args.action == 'click':
            x, y, width, height = result['bbox']
            subprocess.run(['xdotool', 'mousemove', '--window', str(args.window),
                            str(x+width//2), str(y+height//2), 'click', '1'], check=True, timeout=3)
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as error:
        print(json.dumps({'matched': False, 'window': args.window, 'bbox': None, 'error': str(error)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

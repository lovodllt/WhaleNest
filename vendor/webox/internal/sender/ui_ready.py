#!/usr/bin/env python3
"""Read the visible ASCII chat remark before opening or sending."""
import ctypes as c
import os
import re
import subprocess
import sys
import time


def main():
    window, expected, region, wait = sys.argv[1:]
    x11 = c.CDLL('libX11.so.6')
    x11.XOpenDisplay.restype = c.c_void_p
    display = x11.XOpenDisplay(os.environ.get('DISPLAY', ':1').encode())
    if not display:
        return 1
    x11.XGetImage.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_ulong, c.c_int]
    x11.XGetImage.restype = c.c_void_p
    x11.XDefaultRootWindow.argtypes = [c.c_void_p]
    x11.XDefaultRootWindow.restype = c.c_ulong
    x11.XTranslateCoordinates.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_int, c.c_int,
                                         c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_ulong)]
    x11.XGetPixel.argtypes = [c.c_void_p, c.c_int, c.c_int]
    x11.XGetPixel.restype = c.c_ulong
    x11.XDestroyImage.argtypes = [c.c_void_p]
    x11.XCloseDisplay.argtypes = [c.c_void_p]
    left, top, width, height = (280, 12, 490, 46) if region == 'header' else (125, 90, 225, 55)
    root = x11.XDefaultRootWindow(display)
    origin_x, origin_y, child = c.c_int(), c.c_int(), c.c_ulong()
    x11.XTranslateCoordinates(display, int(window), root, 0, 0, c.byref(origin_x), c.byref(origin_y), c.byref(child))
    pattern = re.compile(re.escape(expected.casefold()) + (r'(?:\(\d+\))?$' if region == 'header' else r'(?![a-z0-9_.])'))
    deadline = time.monotonic() + float(wait)
    try:
        while True:
            picture = x11.XGetImage(display, root, origin_x.value+left, origin_y.value+top, width, height, c.c_ulong(-1).value, 2)
            if not picture:
                return 1
            try:
                rows = []
                for y in range(height):
                    row = bytearray()
                    for x in range(width):
                        pixel = x11.XGetPixel(picture, x, y)
                        shade = 255 if ((pixel >> 16 & 255) + (pixel >> 8 & 255) + (pixel & 255)) > 450 else 0
                        row.extend(bytes([shade]) * 3)
                    rows.extend([bytes(row)] * 3)
                bitmap = f'P5\n{width*3} {height*3}\n255\n'.encode() + b''.join(rows)
            finally:
                x11.XDestroyImage(picture)
            result = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '6'],
                                    input=bitmap, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
                                    env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            lines = [''.join(line.casefold().split()) for line in result.stdout.decode(errors='replace').splitlines()]
            if region == 'header':
                lines = lines[:1]
            if os.environ.get('WEBOX_UI_PROBE_DEBUG') == '1':
                print(region, repr(lines), file=sys.stderr)
            if any(pattern.fullmatch(line) if region == 'header' else pattern.search(line) for line in lines):
                return 0
            if time.monotonic() >= deadline:
                return 1
            time.sleep(0.05)
    finally:
        x11.XCloseDisplay(display)


if __name__ == '__main__':
    sys.exit(main())

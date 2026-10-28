#!/usr/bin/env python3
"""Locate a screenshot template without interacting with the desktop."""
import argparse
import json
import math

import cv2


def locate(image, template, roi=None, threshold=0.9, scales=(1.0,)):
    height, width = image.shape[:2]
    x, y, w, h = roi if roi is not None else (0, 0, width, height)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > width or y+h > height:
        raise ValueError('ROI must lie within the screenshot')
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Threshold must be between 0 and 1')
    if not scales or any(not math.isfinite(s) or s <= 0 for s in scales):
        raise ValueError('Scales must be positive finite numbers')
    if template.std() < 1e-6:
        raise ValueError('A template must contain visible detail')
    area = image[y:y+h, x:x+w]
    best = None
    for scale in scales:
        th, tw = (round(size*scale) for size in template.shape[:2])
        if tw < 1 or th < 1 or tw > w or th > h:
            continue
        sample = template if scale == 1 else cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        if sample.std() < 1e-6:
            continue
        scores = cv2.matchTemplate(area, sample, cv2.TM_CCOEFF_NORMED)
        _, score, _, position = cv2.minMaxLoc(scores)
        if best is None or score > best['score']:
            best = {'score': float(score), 'scale': scale,
                    'bbox': [x+position[0], y+position[1], tw, th]}
    if best is None:
        return {'matched': False, 'bbox': None, 'score': None, 'reason': 'no_usable_scale_in_roi'}
    matched = best['score'] >= threshold
    if matched:
        bx, by, bw, bh = best['bbox']
        sample = cv2.resize(template, (bw, bh), interpolation=cv2.INTER_AREA if best['scale'] < 1 else cv2.INTER_CUBIC)
        scores = cv2.matchTemplate(area, sample, cv2.TM_CCOEFF_NORMED)
        px, py = bx-x, by-y
        scores[max(0, py-bh):py+bh, max(0, px-bw):px+bw] = -1
        if cv2.minMaxLoc(scores)[1] >= threshold:
            return {'matched': False, 'bbox': None, 'score': round(best['score'], 6), 'reason': 'ambiguous_matches'}
    return {'matched': matched, 'bbox': best['bbox'] if matched else None,
            'score': round(best['score'], 6), 'scale': best['scale'],
            'reason': 'matched' if matched else 'below_threshold'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('screenshot')
    parser.add_argument('template')
    parser.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'))
    parser.add_argument('--threshold', type=float, default=0.9)
    parser.add_argument('--scales', type=float, nargs='+', default=[1.0])
    args = parser.parse_args()
    try:
        image = cv2.imread(args.screenshot, cv2.IMREAD_GRAYSCALE)
        template = cv2.imread(args.template, cv2.IMREAD_GRAYSCALE)
        if image is None or template is None:
            raise ValueError('Screenshot or template could not be read')
        result = locate(image, template, args.roi, args.threshold, args.scales)
    except (ValueError, cv2.error) as error:
        print(json.dumps({'matched': False, 'bbox': None, 'error': str(error)}))
        return 2
    print(json.dumps(result))
    return 0 if result['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

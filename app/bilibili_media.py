"""Bilibili CDN acquisition and bounded frame sampling, adapted from Dworld."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image, ImageOps


CDNS = ('hdslb.com', 'bilivideo.com', 'bilivideo.cn')


def allowed_url(url):
    parsed = urlparse(url)
    return parsed.scheme == 'https' and not parsed.username and not parsed.password and parsed.port in (None,443) and any(parsed.hostname == host or
        (parsed.hostname or '').endswith('.' + host) for host in CDNS)


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if newurl.startswith('http://'):
            newurl = 'https://' + newurl[7:]
        if not allowed_url(newurl):
            raise ValueError('图片或视频重定向离开已允许的媒体域名')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(url, target, maximum):
    if url.startswith('//'):
        url = 'https:' + url
    if url.startswith('http://'):
        url = 'https://' + url[7:]
    if not allowed_url(url):
        raise ValueError('媒体地址不属于已配置的视频或图片CDN')
    request = Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'})
    temporary = target.with_suffix('.part')
    deadline = time.monotonic() + 90
    try:
        with build_opener(ProxyHandler({}), MediaRedirect()).open(request, timeout=30) as response, temporary.open('wb') as output:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > maximum or time.monotonic() > deadline:
                    raise ValueError('媒体超过单次读取大小限制')
                output.write(block)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def images(data, directory, label, max_side=1600, max_pieces=6):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('图片超过20MiB')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = []
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 25_000_000:
            raise ValueError('图片像素过大')
        count = getattr(original, 'n_frames', 1)
        indexes = sorted({0, count // 2, count - 1}) if count > 1 else [0]
        for frame_index in indexes:
            original.seek(frame_index)
            image = ImageOps.exif_transpose(original).convert('RGBA')
            background = Image.new('RGBA', image.size, 'white')
            background.alpha_composite(image)
            image = background.convert('RGB')
            width, height = image.size
            pieces = min(max_pieces, (max(width, height) + 1599) // 1600) if max(width, height) > 2 * min(width, height) else 1
            for index in range(pieces):
                length = max(width, height)
                lo, hi = max(0, index * length // pieces - 32), min(length, (index + 1) * length // pieces + 32)
                tile = image.crop((0, lo, width, hi) if height >= width else (lo, 0, hi, height)) if pieces > 1 else image.copy()
                tile.thumbnail((max_side, max_side))
                stream = io.BytesIO(); tile.save(stream, format='JPEG', quality=90)
                pixel = stream.getvalue(); sha = hashlib.sha256(pixel).hexdigest()
                path = directory / (sha + '.jpg')
                if not path.exists():
                    path.write_bytes(pixel); path.chmod(0o600)
                result.append({'path':str(path),'sha256':sha,'label':label +
                    (f' 动画采样{frame_index}' if count > 1 else '') + (f' 分段{index+1}/{pieces}，相邻略重叠' if pieces > 1 else '')})
    return result


def video_frames(client, resource, directory, settings):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = client({'operation':'visual_source','resource_id':resource['resource_id'],
                          'cover_only':bool(resource.get('subtitles'))})
    assets, failures = [], []
    if source.get('access') != 'available':
        return assets, {'status':source.get('access','unavailable'),'error_type':source.get('error_type')}
    cover = source.get('cover_url')
    if cover:
        try:
            path = directory / 'cover.source'
            if not path.exists():
                download(cover, path, 20 * 1024 * 1024)
            assets.extend(images(path.read_bytes(), directory, '视频封面，不等于正片内容', 960))
        except (OSError, ValueError) as error:
            failures.append('cover:' + type(error).__name__)
    scope = {'status':'available','mode':'subtitles_and_cover' if resource.get('subtitles') else 'sampled_frames',
             'frame_interval_seconds':None,'visual_from_ms':None,'visual_to_ms':None,'frames':0}
    if resource.get('subtitles'):
        return assets, dict(scope, status='available' if assets else 'unavailable', failures=failures)
    interval, seconds = settings.get('frame_interval_seconds', 2), min(resource['duration_ms']/1000, settings.get('max_video_seconds',600))
    stream = source.get('stream_url')
    if not stream:
        return assets, dict(scope, status='partial' if assets else 'unavailable', failures=failures+['video_unavailable'])
    video, frames = directory/'source.mp4', directory/'frames'
    frames.mkdir(exist_ok=True, mode=0o700)
    marker = frames/'complete'
    try:
        if not marker.exists():
            for stale in frames.glob('*.jpg'):
                stale.unlink()
            download(stream, video, settings.get('max_video_bytes', 256*1024*1024))
            ffmpeg = Path(settings.get('ffmpeg','ffmpeg'))
            subprocess.run([str(ffmpeg),'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(video),'-t',str(seconds),
                '-vf',f"fps=1/{interval}:start_time=0:round=up,scale=w='min(960,iw)':h='min(960,ih)':force_original_aspect_ratio=decrease",
                '-frames:v',str(settings.get('max_frames',300)),'-an','-sn','-threads','2','-q:v','3',
                '-start_number','0',str(frames/'%04d.jpg')], capture_output=True, check=True, timeout=90,
                env=dict(os.environ, LD_LIBRARY_PATH=str(ffmpeg.parent.parent/'lib') if ffmpeg.is_absolute() else os.environ.get('LD_LIBRARY_PATH','')))
            marker.write_text('complete')
        for index, path in enumerate(sorted(frames.glob('*.jpg'))):
            assets.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                           'label':f'正片约{index*interval:g}秒','timestamp_ms':index*interval*1000})
        count = sum('timestamp_ms' in a for a in assets)
        scope.update(frame_interval_seconds=interval, visual_from_ms=0,
                     visual_to_ms=min(round(seconds*1000), count*interval*1000), frames=count)
        if not count:
            failures.append('empty_frames')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        failures.append('video:' + type(error).__name__)
    finally:
        video.unlink(missing_ok=True)
    return assets, dict(scope, status='partial' if failures else 'available', failures=failures)

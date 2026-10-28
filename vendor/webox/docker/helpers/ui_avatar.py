"""Cache a contact thumbnail by stable account identity and match its message row."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np

from ui_locator import capture_window, window_geometry
from ui_template import locate

CACHE = Path('/webox/state/weagent/avatar_templates')


def avatar_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or
            parsed.port not in (None, 80, 443) or
            not any(host == domain or host.endswith('.'+domain) for domain in ('qlogo.cn', 'qpic.cn', 'qq.com'))):
        raise ValueError('Avatar URL is not a recognized WeChat image address')
    return urllib.parse.urlunsplit(parsed._replace(scheme='https'))


class AvatarRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return super().redirect_request(request, fp, code, message, headers, avatar_url(url))


def contact_avatar(username):
    result = subprocess.run(['/webox/state/weagent/native-media'], input=json.dumps(
        {'action':'contact_avatar','username':username}), capture_output=True,text=True,timeout=15,check=True)
    profile = json.loads(result.stdout)
    if profile['username'] != username or not profile.get('avatar_url'):
        raise RuntimeError('Contact avatar is not available')
    url = avatar_url(profile['avatar_url'])
    key = hashlib.sha256((profile['account']+'\0'+username).encode()).hexdigest()
    CACHE.mkdir(mode=0o700,parents=True,exist_ok=True)
    path, metadata = CACHE/(key+'.png'), CACHE/(key+'.json')
    saved = json.loads(metadata.read_text()) if metadata.exists() else {}
    if saved.get('url') == url and time.time()-saved.get('fetched',0) < 21600 and path.is_file():
        return path
    opener = urllib.request.build_opener(AvatarRedirect())
    with opener.open(url,timeout=10) as response:
        data = response.read(1_048_577)
    if len(data)>1_048_576:
        raise ValueError('Contact thumbnail is too large')
    picture = cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if picture is None:
        raise ValueError('Contact thumbnail could not be decoded')
    cv2.imwrite(str(path),picture)
    metadata.write_text(json.dumps({'username':username,'url':url,'fetched':time.time()},ensure_ascii=False))
    return path


def avatar_point(window, extents, username):
    picture = cv2.imread(str(contact_avatar(username)),cv2.IMREAD_GRAYSCALE)
    if picture is None:
        raise ValueError('Cached contact thumbnail could not be decoded')
    template = cv2.resize(picture,(36,36),interpolation=cv2.INTER_AREA)[3:-3,3:-3]
    wx, wy, width, height = window_geometry(window)
    x, y, w, h = extents
    left, top = max(0,x-wx),max(0,y-wy)
    right,bottom = min(width,x+w-wx),min(height,y+h-wy)
    if right<=left or bottom<=top:
        raise RuntimeError('Target message is not visible')
    image = cv2.imdecode(np.frombuffer(capture_window(window),np.uint8),cv2.IMREAD_GRAYSCALE)
    result = locate(image,template,[left,top,right-left,bottom-top],threshold=.9,
                    scales=(.75,.85,.9,1,1.1,1.2,1.35,1.5,2))
    if not result['matched']:
        raise RuntimeError('Contact thumbnail did not uniquely match the intended message')
    bx,by,bw,bh = result['bbox']
    return wx+bx+bw//2,wy+by+bh//2

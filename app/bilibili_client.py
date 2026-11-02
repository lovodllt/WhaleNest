"""Bilibili notification and write protocols; credentials never enter model input."""
import json
import re
import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from runtime_support import file_lock


class BilibiliSocialClient:
    def __init__(self, project_root, transport=None):
        self.root = Path(project_root)
        self.credential_file = Path(project_root) / 'data/bilibili/provider/node_modules/dsh-bilibili/.sessdata.json'
        self.transport = transport or self._transport

    def credential_status(self):
        try:
            value = json.loads(self.credential_file.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            value = {}
        return {'read_ready': bool(value.get('sessdata')), 'write_ready': bool(value.get('sessdata') and value.get('bili_jct'))}

    def _transport(self, host, path, params, *, post=False):
        credentials = json.loads(self.credential_file.read_text(encoding='utf-8'))
        if not credentials.get('sessdata') or post and not credentials.get('bili_jct'):
            return {'code': -101}
        cookie = 'SESSDATA=' + credentials['sessdata']
        if credentials.get('bili_jct'):
            cookie += '; bili_jct=' + credentials['bili_jct']
        params = dict(params)
        if post:
            params['csrf'] = credentials['bili_jct']
        encoded = urllib.parse.urlencode(params).encode()
        request = urllib.request.Request('https://' + host + path + ('' if post else '?' + encoded.decode()),
            data=encoded if post else None, headers={'Cookie': cookie, 'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://www.bilibili.com/', 'Content-Type': 'application/x-www-form-urlencoded'})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            return json.load(response)

    def call(self, request):
        if request['operation'] in ('reply','direct_share'):
            folder=self.root/'data/bilibili';folder.mkdir(parents=True,exist_ok=True)
            with file_lock(folder/'config.lock'):
                return self._call(request)
        return self._call(request)

    def _call(self, request):
        operation = request['operation']
        post = operation in ('reply', 'direct_share')
        write_started = False
        try:
            if post and not self.credential_status()['write_ready']:
                return {'access': 'login_required'}
            nav = self.transport('api.bilibili.com', '/x/web-interface/nav', {})
            if nav.get('code') != 0:
                return self._failure(nav)
            if nav.get('data', {}).get('isLogin') is not True:
                return {'access': 'login_required'}
            uid = str(nav['data']['mid'])
            if operation == 'status':
                return {'access': 'available', 'account_uid': uid, **self.credential_status()}
            if request.get('account_uid') and request['account_uid'] != uid:
                return {'access': 'unavailable', 'error_type': 'AccountChanged'}
            if post:
                from chat_bilibili import settings
                cfg = settings(self.root)
                if not cfg['enabled'] or operation == 'direct_share' and request['recipient_uid'] not in cfg['share_recipient_uids']:
                    return {'access': 'unavailable', 'error_type': 'PermissionChanged'}
            if operation == 'mentions':
                raw = self.transport('api.bilibili.com', '/x/msgfeed/at', request.get('cursor') or {})
                if raw.get('code') != 0:
                    return self._failure(raw)
                data = raw.get('data') or {}
                items = []
                for value in data.get('items', []):
                    item, author = value.get('item', {}), value.get('user', {})
                    if item.get('business_id') != 1 or not item.get('source_id') or not item.get('subject_id'):
                        continue
                    items.append({'id': str(value['id']), 'aid': str(item['subject_id']),
                        'rpid': str(item['source_id']), 'root': str(item.get('root_id') or ''),
                        'sender_uid': str(author.get('mid', '')), 'sender_name': author.get('nickname', ''),
                        'text': item.get('source_content', '')[:2000], 'at_seconds': int(value.get('at_time') or 0)})
                return {'access': 'available', 'account_uid': uid, 'items': items, 'cursor': data.get('cursor') or {}}
            if operation == 'video_id':
                raw = self.transport('api.bilibili.com', '/x/web-interface/view', {'aid': request['aid']})
                return {'access': 'available', 'resource_id': 'bilibili:' + raw['data']['bvid']} if raw.get('code') == 0 else self._failure(raw)
            if operation == 'reply':
                if request.get('root') in (None,'','0'):
                    original=self.transport('api.bilibili.com','/x/v2/reply/info',
                        {'type':'1','oid':request['aid'],'rpid':request['rpid']})
                    reply=(original.get('data') or {}).get('reply') or {}
                    if (original.get('code')!=0 or str(reply.get('rpid_str') or reply.get('rpid'))!=request['rpid']
                            or str(reply.get('oid'))!=request['aid']):
                        return {'access':'unavailable','error_type':'ReplyTargetUnavailable'}
                    request=dict(request,root=str(reply.get('root_str') or reply.get('root') or request['rpid']))
                if any(not re.fullmatch(r'[1-9][0-9]{0,19}',request.get(key,'')) for key in ('aid','root','rpid')):
                    raise ValueError('回复通知的位置不完整')
                params = {'type': '1', 'oid': request['aid'], 'root': request['root'], 'parent': request['rpid'],
                          'message': request['text'], 'plat': '1'}
                write_started = True
                raw = self.transport('api.bilibili.com', '/x/v2/reply/add', params, post=True)
                receipt = (raw.get('data') or {}).get('rpid_str') or (raw.get('data') or {}).get('rpid')
            elif operation == 'direct_share':
                params = {'msg[sender_uid]': uid, 'msg[receiver_id]': request['recipient_uid'],
                    'msg[receiver_type]': '1', 'msg[msg_type]': '1', 'msg[msg_status]': '0',
                    'msg[timestamp]': str(int(time.time())), 'msg[content]': json.dumps({'content': request['text']}, ensure_ascii=False),
                    'msg[dev_id]': hashlib.sha256((str(self.credential_file.parent) + uid).encode()).hexdigest()[:32]}
                write_started = True
                raw = self.transport('api.vc.bilibili.com', '/web_im/v1/web_im/send_msg', params, post=True)
                receipt = (raw.get('data') or {}).get('msg_key')
            else:
                raise ValueError('未知B站社交操作')
            if raw.get('code') != 0:
                return self._failure(raw)
            return {'access': 'available' if receipt else 'uncertain', 'receipt_id': str(receipt) if receipt else None,
                    'evidence': 'provider_receipt', 'account_uid': uid}
        except (OSError, ValueError, KeyError) as error:
            return {'access': 'uncertain' if write_started else 'unavailable', 'error_type': type(error).__name__}

    @staticmethod
    def _failure(raw):
        code = raw.get('code')
        return {'access': 'login_required' if code in (-101, -111) else 'rate_limited' if code in (-412, -352, 412, 429) else 'unavailable',
                'provider_code': code}

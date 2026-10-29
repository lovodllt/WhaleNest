"""Read the exact WeChat voice transcript, requesting native conversion if needed."""
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from dsh_chat import ROOT


def fields(data):
    def number(offset):
        value = shift = 0
        while offset < len(data):
            byte = data[offset]; offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value, offset
            shift += 7
        raise ValueError('Incomplete voice metadata')
    offset = 0
    while offset < len(data):
        tag, offset = number(offset)
        wire = tag & 7
        if wire == 0:
            value, offset = number(offset)
        elif wire == 2:
            size, offset = number(offset)
            value = data[offset:offset+size]; offset += size
        elif wire in (1, 5):
            offset += 8 if wire == 1 else 4
            continue
        else:
            raise ValueError('Unsupported voice metadata')
        yield tag >> 3, value


def transcript(packed):
    for tag, value in fields(packed or b''):
        if tag == 5 and isinstance(value, bytes):
            for field, text in fields(value):
                if field == 2 and isinstance(text, bytes):
                    return text.decode('utf-8').strip()
    return ''


def message_xml(content, kind):
    raw = content.encode() if isinstance(content, str) else content
    if kind == 4:
        z = ctypes.CDLL(ctypes.util.find_library('zstd'))
        z.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        z.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        size = z.ZSTD_getFrameContentSize(raw, len(raw))
        if size > 1_000_000:
            raise ValueError('Invalid voice metadata size')
        output = ctypes.create_string_buffer(size)
        z.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        z.ZSTD_decompress.restype = ctypes.c_size_t
        count = z.ZSTD_decompress(output, size, raw, len(raw))
        if count > size:
            raise ValueError('Invalid compressed voice metadata')
        raw = output.raw[:count]
    return raw.decode('utf-8')


def transcribe(room, msgid, contact):
    try:
        from sqlcipher3 import dbapi2 as sql
    except ImportError as error:
        raise RuntimeError('当前环境缺少语音读取所需的 SQLCipher，请使用 WSL2 部署') from error
    state = Path(os.environ['WEBOX_STATE_DIR'])
    material = json.loads((state/'weagent/wechat.key').read_text(encoding='utf-8'))
    directory = state/material['dbDir'].removeprefix('/webox/state/')
    table = 'Msg_'+hashlib.md5(room.encode()).hexdigest()
    for relative, key in material['keys'].items():
        if not re.fullmatch(r'message/message_\d+\.db', relative):
            continue
        db = sql.connect(f'file:{directory/relative}?mode=ro', uri=True)
        try:
            db.execute('PRAGMA key="x\''+key+'\'"')
            db.execute('PRAGMA cipher_page_size=4096')
            if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                continue
            row = db.execute(f'SELECT packed_info_data,message_content,WCDB_CT_message_content,local_id,origin_source '
                             f'FROM [{table}] WHERE server_id=? AND local_type % 4294967296=34', (int(msgid),)).fetchone()
            if not row:
                continue
            text = transcript(row[0])
            if text:
                return text
            millis = re.search(r'voicelength="(\d+)"', message_xml(row[1], row[2]))
            if not millis:
                raise ValueError('Voice duration is unavailable')
            offset = db.execute(f'SELECT count(*) FROM [{table}] WHERE local_type % 4294967296=34 AND local_id>?', (row[3],)).fetchone()[0]
            remark = contact.get('remark') or contact.get('nickname')
            if not remark:
                raise ValueError('Voice conversation is unavailable')
            request = {'remark': remark, 'seconds': max(1, (int(millis[1])+500)//1000),
                       'offset': offset, 'outgoing': row[4] == 1}
            result = subprocess.run(['docker','exec','-i','-u','webox','-e','HOME=/webox/state/home',
                                     '-e','DISPLAY=:1','dafeiyu-wechat',
                                     'python3','/webox/state/weagent/ui_voice_text.py'],
                                    input=json.dumps(request), capture_output=True, text=True, timeout=25)
            if result.returncode:
                raise RuntimeError('Native voice conversion is unavailable')
            for _ in range(60):
                packed = db.execute(f'SELECT packed_info_data FROM [{table}] WHERE server_id=?', (int(msgid),)).fetchone()[0]
                text = transcript(packed)
                if text:
                    return text
                time.sleep(.2)
            raise RuntimeError('Native voice conversion timed out')
        except sql.Error as exc:
            raise RuntimeError('Voice metadata could not be read') from exc
        finally:
            db.close()
    raise ValueError('Voice message was not found in this conversation')

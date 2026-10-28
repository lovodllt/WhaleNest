"""Owner-private requests to send a short message to an existing contact."""
import json
import re
import time

import chat_style
import chat_singing


def capabilities(binding, settings, enabled, last_song=None):
    if not enabled:
        return {'允许群发安排': False,
                '说明':'仅本轮不受理新群发动作，不代表功能关闭或接口不可用。历史安排以后台回执为准；回应图片或表情时不要重复承诺、拒绝历史请求，也不要编造发送失败。'}
    groups = [{'id': room, '群名': contact.get('nickname', ''), '备注': contact.get('remark', '')}
              for room, contact in binding['rooms'].items() if room.endswith('@chatroom')]
    default = settings.get('owner_control', {}).get('default_group', '')
    return {'允许群发安排': True, '允许群发语音': settings.get('voice_reply',{}).get('enabled',False),
            '允许群发唱歌':settings.get('singing',{}).get('enabled',False),
            '可点歌曲':list(settings.get('singing',{}).get('songs',{})), '最近发送歌曲':last_song,
            '可选群聊': groups, '默认群': default,
            '规则': '主人在本私聊明确要求你去某群发消息时，直接安排，不要求命令或转找Codex。'
            '结合当前发言、明确引用和主人前文理解要发的内容；只说去群里时使用默认群。'
            '指定群名或测试群时匹配可选群聊，目标不明、重名或内容不清先问清，不能擅自换群。'
            '输出<GROUP_MESSAGE>{"room":"所选群id","text":"实际要说的话","voice":false,"song":null}</GROUP_MESSAGE>。'
            '已收录的歌曲可以发到群里，并非私聊限定。主人要求去群里唱歌、把刚才的歌也发群里时，'
            'song填写可点歌曲中的完整歌名，voice为false，text可以留空；后台直接发送真实歌声音频，不念歌词。'
            '主人说同一段、一样的、刚才那首时，结合最近发送歌曲和前文确定歌名；不清楚时先问清。'
            '未收录歌曲先说明需要音源，不能改成念歌词或普通语音，也不能声称群里不能唱歌。'
            '主人明确要求去群里用语音说话、用语音打招呼时，允许群发语音为true就设置voice为true，text写实际要念的短句；'
            '不要说无法发语音，也不要擅自改成文字或在私聊直接念群招呼。未要求语音时voice为false。'
            '只发送主人此次授权的内容，不自动带入私聊背景、私人事实或内部配置。'
            '主人已给出要转达的原话时逐字保留，不擅自补充自己的告别或解释；'
            '只有要求你自行组织措辞时才按人设写短消息，每句尽量20字最多25字，最多三句。'
            '不附其他控制标记，不声称已经发送；后台发送后会私聊回报。'
            '能力询问、否定、讨论或引用他人的要求不执行。一次只安排一条群消息；'
            '与生图或朋友圈投稿一次只选一个动作。生图请求使用生图能力，不能拿群发代替。'}


def take_request(answer):
    matches = re.findall(r'<GROUP_MESSAGE>(.*?)</GROUP_MESSAGE>', answer, re.S)
    answer = re.sub(r'<GROUP_MESSAGE>.*?(?:</GROUP_MESSAGE>|$)', '', answer, flags=re.S).strip()
    if not matches:
        return answer, None
    if len(matches) != 1:
        raise ValueError('一次先安排一条群消息吧🐟')
    try:
        request = json.loads(matches[0])
    except ValueError:
        raise ValueError('没理清要发的话，主人再说一下吧🐟')
    return answer, request


def prepare(request, binding, settings, allow_private=False):
    if not isinstance(request, dict) or not isinstance(request.get('text', ''), str):
        raise ValueError('没理清要发的话，主人再说一下吧🐟')
    room = request.get('room')
    if not isinstance(room, str) or room not in binding['rooms'] or not allow_private and not room.endswith('@chatroom'):
        raise ValueError('这个联系人还没认准，再查一下吧🐟')
    song = request.get('song')
    if song is not None:
        if not isinstance(song, str) or song not in settings.get('singing',{}).get('songs',{}):
            raise ValueError('这首还没备好音源，先把音频给本鱼吧🐟')
        recording = chat_singing.resolve(song, settings)
        if recording['path'] is None:
            raise ValueError(recording['reply'])
        return {'room':room, 'text':recording['reply'], 'voice':False, 'song':song}
    text = request.get('text', '').strip()
    parts = chat_style.short_messages(text)
    if not parts or re.search(r'\[\[|</?[A-Z_]+>', text):
        raise ValueError('要发的话太长或格式不对，简短点吧🐟')
    voice = request.get('voice', False)
    if not isinstance(voice,bool):
        raise ValueError('没理清要用哪种方式，主人再说一下吧🐟')
    if voice and not settings.get('voice_reply',{}).get('enabled',False):
        raise ValueError('语音暂时休息，先发文字好不好🐟')
    return {'room': room, 'text': '\n'.join(parts), 'voice': voice}


def enqueue(db, event_id, request, owner):
    now = int(time.time()*1000)
    current = {'_room': request['room'], '会话类型': '群聊' if request['room'].endswith('@chatroom') else '私聊', '点名': True, '主人': False,
               '消息时间': now, '发言': request['text'],
               '_owner_send': {'origin': event_id, 'owner': owner, 'room': request['room'], 'voice': request.get('voice',False), 'song':request.get('song')},
               '_source': {'type': 'owner_control'}}
    db.execute('INSERT OR IGNORE INTO inbox(id,prompt,time) VALUES(?,?,?)',
               ('owner-send-'+event_id, json.dumps(current, ensure_ascii=False), now))


def finish(db, request, outcome):
    now = int(time.time()*1000)
    group = request.get('room', '@chatroom').endswith('@chatroom')
    prefix = '群' if group else '私聊'
    text = {'sent': ('群里的' if group else '')+'歌声送到啦🐟' if request.get('song') else prefix+'语音发好啦🐟' if request.get('voice') else prefix+'消息发好啦🐟',
            'text': '语音没发成，已改发文字啦🐟', 'failed': '没发出去，消息还没送达🐟',
            'unknown': '消息没确认，先不重复发啦🐟'}[outcome]
    if request.get('song') and outcome != 'sent':
        text = ('群里的' if group else '')+'歌声没确认，先不重复发啦🐟' if outcome == 'unknown' else '歌声没发出去，等会儿再试🐟'
    current = {'_room': request['owner'], '会话类型': '私聊', '点名': True, '主人': True,
               '消息时间': now, '发言': text, '_owner_receipt': True,
               '_source': {'type': 'owner_control'}}
    db.execute('INSERT OR IGNORE INTO inbox(id,prompt,time) VALUES(?,?,?)',
               ('owner-result-'+request['origin'], json.dumps(current, ensure_ascii=False), now))

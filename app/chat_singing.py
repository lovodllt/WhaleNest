"""Route song requests to prepared singing audio, never spoken lyrics."""
import re
from pathlib import Path

from dsh_chat import ROOT


def request(text, settings):
    rule = settings.get('singing', {})
    songs = rule.get('songs', {})
    names = [name for title, song in songs.items() for name in [title, *song.get('aliases', [])]]
    pattern = (r'(?:清唱|翻唱|唱|哼)(?:一|两|几|\d+)?(?:首|段|句|下|歌)'
               r'|(?:来|放|整)(?:一)?首'
               r'|(?:用语音|给我|帮我|为我|请).{0,4}(?:清唱|翻唱|唱|哼)'
               r'|(?:清唱|翻唱|唱|哼)(?=\s*(?:[《「“"]' +
               ('|' + '|'.join(map(re.escape, names)) if names else '') + r'))')
    matches = list(re.finditer(pattern, text))
    if not matches:
        return None
    match = matches[-1]
    if re.search(r'别|不要|不用|停止|不想|不会|不许|不准', text[max(0, match.start()-6):match.start()]):
        return None
    tail = text[match.end():].strip()
    if re.match(r'(?:的)?(?:接口|功能|模型|链路|流程|原理|有问题|出错|失败|怎么|如何)', tail):
        return None
    title = next((title for title, song in songs.items()
                  if any(name.casefold() in tail.casefold() for name in [title, *song.get('aliases', [])])), None)
    if title is None and (not tail or re.fullmatch(r'[歌吧呀啊啦哦呢嘛好吗给我听一下听听来点随便都行你选的最喜欢！!？?\s~～]*', tail)):
        title = rule.get('default_song')
    return resolve(title, settings)


def resolve(title, settings):
    rule = settings.get('singing', {})
    songs = rule.get('songs', {})
    if not rule.get('enabled', False):
        return {'song': title, 'path': None, 'reply': '本鱼的唱歌功能还没开启🐟'}
    if title not in songs:
        return {'song': None, 'path': None, 'reply': '这首还没备好音源，先把音频给本鱼吧🐟'}
    path = ROOT / Path(songs[title]['path'])
    if not path.is_file():
        return {'song': title, 'path': None, 'reply': '这首歌的音源暂时找不到啦🐟'}
    return {'song': title, 'path': path, 'reply': '给你唱一段《' + title + '》🐟'}

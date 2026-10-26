"""Short conversational messages, preserving emoji and kaomoji."""
import re

_BASE = r'[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF]'
_EMOJI = (r'(?:[\U0001F1E6-\U0001F1FF]{2}|[0-9#*]\uFE0F?\u20E3|'+_BASE+
          r'[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]*(?:\u200D'+_BASE+r'[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]*)*)')
_FACE = (r'[╰╯ヽヾづつ༼]{0,3}[（(](?=[^()（）\n]{0,40}[ω∀▽△Д益皿εヮ•・･ﾟ^_´╹◡ಠಥ๑ง])'
         r'[^()（）\n\u4E00-\u9FFF]{1,40}[)）][づつっノヮงو╯╰︵┻━┳✧☆]{0,12}'
         r'|(?<![A-Za-z])(?:QAQ|TAT|T_T|>_<|\^_\^|orz|Orz)(?![A-Za-z])')
_TOKENS = re.compile(r'(?P<face>'+_FACE+r')|(?P<emoji>'+_EMOJI+r')|(?P<char>[\s\S])')


def text_length(text):
    return sum(m.lastgroup=='char' and not m[0].isspace() for m in _TOKENS.finditer(text))


def short_messages(text, limit=25, max_sentences=3):
    parts = []
    buffer = ''
    for match in _TOKENS.finditer(text):
        token = match[0]
        if token=='\n':
            if buffer.strip():
                parts.append(buffer.strip())
            buffer = ''
            continue
        if not buffer and parts and (match.lastgroup!='char' or token in '。！？!?；;.…”」』'):
            parts[-1] += token
            continue
        if not buffer and token.isspace():
            continue
        buffer += token
        if token in '。！？!?；;.':
            if buffer.strip():
                parts.append(buffer.strip())
            buffer = ''
    if buffer.strip():
        parts.append(buffer.strip())
    parts = [part.rstrip('。.') for part in parts if part.rstrip('。.')]
    if len(parts)>max_sentences or any(text_length(part)>limit for part in parts):
        return None
    return parts

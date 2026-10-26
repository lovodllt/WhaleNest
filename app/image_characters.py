"""Shared character references and drawing rules for DSH and Codex."""
import json
import datetime
from pathlib import Path
import re
import threading

ROOT = Path(__file__).resolve().parents[1] / 'resources/characters'
VIEW_LOCK = threading.Lock()


def rules():
    return json.loads((ROOT.parents[1]/'config/image-rules.json').read_text())


def catalog():
    result = {}
    for path in sorted(ROOT.glob('*/设定.json')):
        item = json.loads(path.read_text())
        item['notes'] = '\n'.join(p.read_text() for p in sorted(path.parent.glob('*.md')) if p.name != 'D老师视角.md')
        view = path.parent/'D老师视角.json'
        item['ds_view'] = json.loads(view.read_text()) if view.exists() else {}
        item['folder'] = path.parent
        result[item['id']] = item
    return result


def mentioned(text, items):
    found = []
    for ident, item in items.items():
        if any(re.search(r'(?<![a-zA-Z])'+re.escape(alias)+r'(?![a-zA-Z])', text, re.I)
               if alias.isascii() else alias in text for alias in item['aliases']):
            found.append(ident)
    if re.search(r'画(?:一张|一幅|个)?你|你(?:自己|和|与|在|的(?:日常|表情|样子))|本鱼', text) and 'deepseek' not in found:
        found.append('deepseek')
    return found


def details(item):
    return {k: item[k] for k in ('id', 'name', 'appearance', 'notes', 'ds_view')}


def context(text):
    items = catalog()
    ids = mentioned(text, items)
    if re.search(r'AI朋友|AI娘|朋友们', text, re.I):
        ids = list(dict.fromkeys(ids+[key for key in items if key != 'deepseek']))
    return {'索引': [{'id': key, '名称': item['name'], '别名': item['aliases']} for key, item in items.items()],
            '本次涉及角色': [details(items[key]) for key in ids],
            '规则': '用户设定优先；ds_view是D老师可更新的虚构友谊记录和主观印象，不是现实经历，也不覆盖固定设定、聊天人格或聊天对象记忆'}


def references(ids, style, description=''):
    items = catalog()
    selected = [items[key] for key in dict.fromkeys(ids)]
    images = []
    for item in selected:
        registered = {}
        for ref in item['reference_images']:
            path = (item['folder']/ref['file']).resolve()
            if not path.is_relative_to(item['folder'].resolve()) or not path.is_file():
                raise ValueError('Character reference is missing or outside its folder')
            registered[path] = ref['role']
        paths = set(registered)
        paths.update(path.resolve() for path in item['folder'].rglob('*')
                     if path.is_file() and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')
                     and '资料归档' not in path.relative_to(item['folder']).parts
                     and path.resolve().is_relative_to(item['folder'].resolve()))
        for path in sorted(paths, key=lambda path: ('设定集' not in path.stem, path.name)):
            primary = '设定集' in path.stem
            purpose = ('优先的设定集图片，角色外观与身份的主要依据' if primary else
                       '辅助固定形象细节、扩展画风；不能覆盖设定集图片的身份特征')
            images.append({'path': str(path), 'role': item['name']+'：'+purpose+'；'+registered.get(path, ''),
                           'priority': 'primary' if primary else 'supplement'})
    group = ROOT/'群体图/群体图.png'
    if group.is_file() and (len(selected) > 1 or re.search(r'群体图|合照|全员|所有AI|AI朋友们', description, re.I)):
        images.append({'path': str(group), 'priority': 'group',
                       'role': '群体同框与共同画风补充，左到右为GPT、Gemini、Z、DeepSeek、Claude、Qwen、Grok；仅画本次要求的人物，不自动添加其他角色，不替代单人设定集'})
    if style == 'meme' and (ROOT/'画风参考/可爱梗图参考.jpg').is_file():
        images.append({'path': str(ROOT/'画风参考/可爱梗图参考.jpg'),
                       'role': '仅参考圆润Q版比例、线条、表情和简洁梗图画风；不复制原文字、动作或把画风参考当成其他角色的身份'})
    return [details(item) for item in selected], images


def take_view_updates(answer):
    match = re.search(r'<AI_FRIEND_UPDATES>(.*?)</AI_FRIEND_UPDATES>', answer, re.S)
    updates = []
    if match:
        try:
            updates = json.loads(match[1])
        except ValueError:
            pass
    return re.sub(r'<AI_FRIEND_UPDATES>.*?(?:</AI_FRIEND_UPDATES>|$)', '', answer, flags=re.S).strip(), updates


def view_instructions(allowed):
    return {'允许更新角色': [key for key in allowed if key != 'deepseek'],
            '规则': '可自发维护你对这些AI角色的主观印象、亲疏感与虚构日常，不需用户逐次命令。只在有值得记录的新理解或AI小剧场时更新，普通闲聊不硬记。'
            '固定性格与用户指定的关系优先，不能被记录覆盖。事件必须明确是虚构AI日常；计划生成的图尚未成功时不记为已发生。'
            '不记录真人、主人、群友、私聊或其他群的事，不摘录聊天原话，不含账号、链接、工作测试内容或内部配置。'
            '如需更新，在正文后输出<AI_FRIEND_UPDATES>[{"id":"gpt等允许的id","impression":"可选，第一人称简要印象","relationship":"可选，主观关系感受","event":"可选，仅AI角色的虚构日常摘要"}]</AI_FRIEND_UPDATES>。'
            '没有新内容不输出标记。只写本轮允许的角色；标记不展示给聊天对象。'}


def update_views(updates, allowed, source):
    if not isinstance(updates, list) or len(updates) > 5:
        return 0
    changed = 0
    with VIEW_LOCK:
        items = catalog()
        for update in updates:
            if not isinstance(update, dict):
                continue
            key = update.get('id')
            if not isinstance(key, str) or key == 'deepseek' or key not in allowed or key not in items:
                continue
            fields = {name: update.get(name, '') for name in ('impression', 'relationship', 'event')}
            if any(not isinstance(text, str) or len(text) > 240 for text in fields.values()):
                continue
            if not any(text.strip() for text in fields.values()):
                continue
            combined = ' '.join(fields.values())
            if re.search(r'wxid_|@chatroom|https?://|\b1[3-9]\d{9}\b|\S+@\S+|主人|群友|本群|私聊|验证码|密钥|内部配置|工作|测试|调试', combined, re.I):
                continue
            item = items[key]
            view = dict(item['ds_view'])
            for name in ('impression', 'relationship'):
                if fields[name].strip():
                    view[name] = fields[name].strip().replace('\n', ' ')
            events = list(view.get('events', []))
            event = fields['event'].strip().replace('\n', ' ')
            now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            if event and event not in [entry['text'] for entry in events]:
                events.append({'time': now, 'kind': source, 'text': event})
            view['events'] = events[-20:]
            if view == item['ds_view']:
                continue
            view.update(scope='虚构AI朋友日常与D老师的主观印象，非现实经历', updated_at=now)
            path = item['folder']/'D老师视角.json'
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(view, ensure_ascii=False, indent=2)+'\n')
            temporary.replace(path)
            text = '# D老师眼里的'+item['name']+'\n\n'+view['scope']+'\n\n我的印象：'+view.get('impression', '还在慢慢了解')+'\n\n我们的关系：'+view.get('relationship', 'AI朋友')+'\n\n## 虚构日常记录\n\n'
            text += '\n'.join('- '+entry['time'][:10]+'｜'+entry['kind']+'｜'+entry['text'] for entry in view['events']) or '暂时还没有小故事记录'
            (item['folder']/'D老师视角.md').write_text(text+'\n')
            changed += 1
        if changed:
            render_views()
    return changed


def render_views():
    text = '# D老师的AI朋友\n\n这里是虚构AI朋友的主观印象和小故事，与真人聊天记忆、D老师自身人格、用户固定人物设定分开保存\n'
    for key, item in catalog().items():
        if key == 'deepseek':
            continue
        view = item['ds_view']
        text += '\n## '+item['name']+'\n\n'+view.get('impression', '还在慢慢了解')+'\n\n关系：'+view.get('relationship', 'AI朋友')+'\n'
        text += ''.join('\n- '+entry['time'][:10]+'｜'+entry['text'] for entry in view.get('events', [])[-3:])+'\n'
    (ROOT/'D老师的AI朋友.md').write_text(text)

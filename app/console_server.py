"""Local operator console for the running Dafeiyu bridge."""
import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parent))
from runtime_support import ensure_utf8,watch_stop
ensure_utf8()

import chat_tasks
import person_memory
from resource_center import Resources
from dsh_chat import ROOT, NODE, DSH



class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def at_path(data, path, default=None):
    for key in path:
        if isinstance(data, dict):
            data = data.get(key, default)
        elif isinstance(data, list) and isinstance(key, int) and key < len(data):
            data = data[key]
        else:
            return default
    return data


def set_path(data, path, value):
    for key in path[:-1]:
        if isinstance(data, dict):
            data = data.setdefault(key, {})
        else:
            data = data[key]
    data[path[-1]] = value


class ConsoleBackend:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.resources = Resources(self.root)
        self.settings_path = self.root / 'config/chat.json'
        self.voice_path = self.root / 'config/voice.json'
        self.db_path = self.root / 'data/chat/bridge.sqlite3'
        self.access_config_path = self.root / 'data/console-access.json'
        self.webox_state = Path(os.environ.get('WEBOX_STATE_DIR', self.root / 'data/wechat'))
        self.lock = threading.RLock()
        self.csrf_token = secrets.token_urlsafe(32)
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def access_config(self):
        config = read_json(self.access_config_path, {})
        origin = config.get('origin', '')
        url = urlsplit(origin)
        if (url.scheme != 'https' or not (url.hostname or '').endswith('.ts.net') or
                url.netloc != url.hostname or url.path or url.query or url.fragment or
                not config.get('allowed_login')):
            return {}
        return config

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        if not self.settings_path.is_file():
            raise APIError(503, '没有找到当前机器人的配置文件')
        return read_json(self.settings_path), read_json(self.voice_path, {})

    def revision(self):
        return hashlib.sha256(self.settings_path.read_bytes() + (self.voice_path.read_bytes() if self.voice_path.exists() else b'')).hexdigest()[:24]

    def meta(self, db, key, default=None):
        row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def target_id(room):
        return hashlib.sha256(('console-target:' + room).encode()).hexdigest()[:20]

    def target_map(self, db, settings, contacts=()):
        binding = self.meta(db, 'binding', {})
        known = binding.get('known_chats', {})
        contacts = contacts or binding.get('rooms', {}).values()
        rooms = {c['roomid']: (c.get('remark') if not (c.get('remark') or '').startswith('webox.') else '') or c.get('nickname') or '未命名会话'
                 for c in contacts if c.get('roomid') not in (*binding.get('self_ids', []), 'filehelper', 'weixin', 'newsapp', 'fmessage', 'medianote', 'floatbottle', 'notifymessage')
                 and not c.get('roomid', '').startswith('gh_')}
        if not contacts:
            for room in known.values():
                rooms.setdefault(room, '已绑定群聊' if room.endswith('@chatroom') else '已绑定私聊')
        keys = {room:key for key,room in known.items()}
        return {self.target_id(room): {'room':room, 'label':label, 'kind':'group' if room.endswith('@chatroom') else 'private',
                                     'configured':keys.get(room,room) in settings.get('chats',{})}
                for room, label in rooms.items()}

    def schema(self, settings, voice, targets):
        fields, paths = [], {}

        def add(key, label, kind, path, section, doc='settings', default=None, **options):
            fields.append({'key':key, 'label':label, 'type':kind, 'section':section, **options})
            paths[key] = (doc, tuple(path), default)

        add('plugins.web','启用联网','boolean',['plugins','web'],'联网与生图',default=False)
        add('plugins.image','启用 Codex 生图','boolean',['plugins','image'],'联网与生图',default=False)
        add('reply_paused', '暂停所有回复', 'boolean', ['reply_paused'], '基础回复', default=False,
            description='开启后停止微信回复；关闭后按各会话规则恢复')
        add('owner_agent.enabled','主人私聊生活工具','boolean',['owner_agent','enabled'],'基础回复',default=False,
            description='仅主人私聊可调用素材整理、提醒、公开查询和日常表达设置工具')
        add('memory.enabled','启用私聊长期记忆','boolean',['memory','enabled'],'记忆管理',default=True,
            description='关闭后停止新增和召回人物记忆；保留已经保存的性格偏好')
        add('memory.impression_days','暂定印象保留天数','number',['memory','impression_days'],'记忆管理',default=90,min=7,max=365)
        add('memory.log_days','本地模型记录保留天数','number',['memory','log_days'],'记忆管理',default=7,min=1,max=90)
        add('memory.queue_days','整理队列原文最长保留天数','number',['memory','queue_days'],'记忆管理',default=7,min=1,max=30)
        for name, label, default in [('private_reply','私聊默认回复',True), ('group_mention_reply','群聊唤醒后回复',True), ('natural_reply','新会话默认自然参与',False)]:
            add('defaults.'+name, label, 'boolean', ['defaults',name], '基础回复', default=default)
        add('prefer_quote','群聊优先引用消息','boolean',['prefer_quote'],'基础回复',default=True)
        add('outgoing_mentions','允许尝试 @，失败改发普通消息','boolean',['outgoing_mentions'],'基础回复',default=True)
        add('defaults.auto_stickers','默认允许配表情包','boolean',['defaults','auto_stickers'],'表情包',default=True)
        add('defaults.sticker_interval_seconds','默认表情间隔（秒）','number',['defaults','sticker_interval_seconds'],'表情包',default=120,min=0,max=86400)
        for key, label, default in [('enabled','开启语音回复',True),('spontaneous','偶尔自然使用语音',False)]:
            add('voice_reply.'+key,label,'boolean',['voice_reply',key],'语音回复',default=default)
        add('voice_reply.provider','语音引擎','select',['voice_reply','provider'],'语音回复',default='edge',options=[{'value':'edge','label':'微软在线语音'},{'value':'gpt-sovits','label':'本地 GPT-SoVITS（需单独部署）'}])
        add('voice_reply.spontaneous_interval_minutes','自然语音最小间隔（分钟）','number',['voice_reply','spontaneous_interval_minutes'],'语音回复',default=30,min=1,max=10080)
        add('singing.enabled','开启已收录歌曲点唱','boolean',['singing','enabled'],'唱歌',default=False,
            description='发送已准备的清唱音频；不启动新模型或自动下载歌曲')
        if voice.get('edge_tts'):
            voices = read_json(self.root / 'data/tts/voices.json', [])
            choices = [{'value':v['voice'],'label':v.get('label') or v.get('name') or v['voice']}
                       for v in voices if v.get('voice','').startswith('zh-')]
            current = voice['edge_tts'].get('voice', 'zh-CN-XiaoyiNeural')
            if not any(v['value']==current for v in choices):
                choices.insert(0, {'value':current,'label':current})
            add('tts.voice','微软音色','select',['edge_tts','voice'],'微软音色','voice',default=current,options=choices)
            for key, label, lo, hi in [('pitch','音高偏移（Hz）',-30,30),('rate','语速偏移（%）',-50,100),('volume','音量偏移（%）',-50,100)]:
                add('tts.'+key,label,'number',['edge_tts',key],'微软音色','voice',default=0,min=lo,max=hi)
        by_room = {v['room']:v for v in targets.values()}
        known = {}
        with self.db() as db:
            known = self.meta(db,'binding',{}).get('known_chats',{})
        for config_key, rule in settings.get('chats', {}).items():
            room = known.get(config_key,config_key)
            if room not in by_room:
                continue
            token = self.target_id(room)
            section = '会话 · ' + by_room[room]['label']
            if room.endswith('@chatroom'):
                add(f'chat.{token}.natural_reply','允许自然参与','boolean',['chats',config_key,'natural_reply'],section,default=settings['defaults'].get('natural_reply',False),
                    description='仅最近10分钟出现唤醒词时，判断是否值得接话；不会句句回应')
                hours = rule.get('natural_hours', ['00:00','24:00'])
                add(f'chat.{token}.natural_start','自然参与开始时间','text',['chats',config_key,'natural_hours',0],section,default=hours[0],clock=True)
                add(f'chat.{token}.natural_end','自然参与结束时间','text',['chats',config_key,'natural_hours',1],section,default=hours[1],clock=True,end=True,description='HH:MM；24:00 表示当天结束')
                add(f'chat.{token}.natural_mute_hours','退订后安静时长（小时）','number',['chats',config_key,'natural_mute_hours'],section,default=3,min=1,max=72)
                add(f'chat.{token}.auto_label_stickers','自动收集并描述群内表情包','boolean',['chats',config_key,'auto_label_stickers'],section,default=False)
            proactive = rule.get('proactive', {})
            add(f'chat.{token}.proactive.enabled','允许主动发起聊天','boolean',['chats',config_key,'proactive','enabled'],section,default=False,
                description='此开关就是该会话的主动消息白名单；时段和频率独立')
            hours = proactive.get('hours',['09:00','23:00'])
            for index, label in [(0,'主动消息开始时间'),(1,'主动消息结束时间')]:
                add(f'chat.{token}.proactive.'+('start' if index==0 else 'end'),label,'text',['chats',config_key,'proactive','hours',index],section,default=hours[index],clock=True,end=index==1)
            for key, label, default, lo, hi in [('interval_minutes','主动检查间隔（分钟）',180,5,10080),('idle_minutes','聊天空闲多久才主动（分钟）',60,1,10080),('max_per_day','每日最多主动消息',3,1,100)]:
                add(f'chat.{token}.proactive.{key}',label,'number',['chats',config_key,'proactive',key],section,default=default,min=lo,max=hi)
        values = {f['key']:at_path(voice if paths[f['key']][0]=='voice' else settings, paths[f['key']][1], paths[f['key']][2]) for f in fields}
        return fields, paths, values

    def http_json(self, url, headers=None):
        with self.http.open(urllib.request.Request(url,headers=headers or {}), timeout=2) as response:
            return json.load(response)

    def probe(self):
        service_names = {'bridge':('dafeiyu-wechat-group.service','微信消息桥接'), 'tts':('microsoft-tts.service','微软语音'), 'clone':('gpt-sovits-local.service','本地音色克隆')}
        services = []
        env = dict(os.environ)
        if hasattr(os,'getuid'):
            env.update(XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}',DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.getuid()}/bus')
        for key, (unit,label) in service_names.items():
            try:
                result = subprocess.run([sys.executable,str(self.root/'scripts/service_status.py'),key],capture_output=True,text=True,timeout=2,env=env)
                state = result.stdout.strip() or 'unknown'
            except (OSError,subprocess.TimeoutExpired):
                state = 'unknown'
            services.append({'id':key,'name':label,'state':state,'detail':'运行中' if state=='active' else '未运行' if state in ('inactive','failed') else '状态不可读取'})
        try:
            with self.http.open('http://127.0.0.1:9980/docs',timeout=.5) as response:clone_active=response.status==200
        except (OSError,ValueError):clone_active=False
        for entry in services:
            if entry['id']=='clone':entry.update(state='active' if clone_active else 'inactive',detail='运行中' if clone_active else '未运行')
        wechat = {'connected':False,'service_available':False,'detail':'微信服务暂时不可访问','nickname':'','login_url':'http://127.0.0.1:6860/vnc.html?autoconnect=1&resize=scale'}
        contacts = []
        try:
            health = self.http_json('http://127.0.0.1:48080/healthz')
            wechat['service_available'] = bool(health.get('ok'))
            wechat['detail'] = '微信登录会话不可用，请在登录页面确认' if not health.get('ready') else '等待核对登录账号'
            if health.get('ready'):
                token = (self.webox_state/'weagent/api-token').read_text(encoding='utf-8').strip()
                headers = {'AuthorizationType':'ilink_bot_token','Authorization':'Bearer '+token,'X-WECHAT-UIN':'dafeiyu'}
                info = self.http_json('http://127.0.0.1:48080/ilink/bot/userinfo',headers)
                wechat['connected'] = info.get('ret')==0
                if wechat['connected']:
                    wechat.update(detail='微信已登录',nickname=info.get('nickname',''))
                    listing = self.http_json('http://127.0.0.1:48080/ilink/bot/contacts',headers)
                    contacts = listing.get('contacts',[]) if listing.get('ret')==0 else []
        except (OSError,ValueError,TypeError):
            pass
        home = Path(os.environ.get('DSH_HOME',Path.home()/'.dsh'))
        installed = []
        for profile, packages in [('dafeiyu-runtime',['@liustack/modsearch','dsh-mnemon','dsh-mnemon-source-runtime']),('dafeiyu-direct',['dsh-kaomoji']),('dafeiyu-group',['dsh-kaomoji'])]:
            for package in packages:
                meta = read_json(home/'profiles'/profile/'node_modules'/package/'package.json', {})
                installed.append({'id':package,'name':package,'available':bool(meta.get('version')),'version':meta.get('version',''),'profile':profile})
        executable = Path(DSH)
        available = executable.is_file() and Path(NODE).is_file()
        version = ''
        if available:
            for parent in executable.resolve().parents:
                pkg = read_json(parent/'package.json', {})
                if pkg.get('name')=='@deepseek-ai/dsh':
                    version = pkg.get('version','');break
        dsh = {'available':available,'version':version,'detail':'本机 stdio 会话；模型配置由 DSH 管理，不依赖网页窗口','plugins':installed}
        return {'updated_at':dt.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'services':services,'dsh':dsh,'wechat':wechat}, contacts

    def plugin_state(self, settings, voice, status, fields):
        mods = self.root/'app'
        dsh_ok = status['dsh']['available']
        engine=settings.get('voice_reply',{}).get('provider','edge')
        tts_ok = any(s['id']==('clone' if engine=='gpt-sovits' else 'tts') and s['state']=='active' for s in status['services'])
        clone_ok = any(s['id']=='clone' and s['state']=='active' for s in status['services'])
        packages = {p['id']:p['available'] for p in status['dsh']['plugins']}
        songs = settings.get('singing',{}).get('songs',{})
        clips = bool(songs) and all((self.root/Path(s['path'])).is_file() for s in songs.values())
        definitions = [
            ('daily_agent','主人私聊行动',settings.get('owner_agent',{}).get('enabled',False),dsh_ok,['owner_agent.enabled'], '生活类原生工具；只认已绑定主人，不开放任意文件或终端命令','daily_agent.py'),
            ('memory','长期记忆',settings.get('memory',{}).get('enabled',True),True,['memory.enabled','memory.impression_days','memory.log_days','memory.queue_days'], '记忆手账中查看、纠正、置顶或忘记；性格仍只从主人私聊学习','person_memory.py'),
            ('web','联网聊天',settings.get('plugins',{}).get('web',False),packages.get('@liustack/modsearch',False),['plugins.web'], '通过本机 DSH 的 ModSearch 按需查询；缺依赖时在终端运行 plugins','chat_web.py'),
            ('vision','识图',None,dsh_ok,[], '使用当前 DSH 视觉配置，暂不提供独立 API 切换','chat_media.py'),
            ('image','图片生成',settings.get('plugins',{}).get('image',False),bool(shutil.which('codex')),['plugins.image'], 'DSH 整理需求，再调用本机 Codex 生图；需自行安装登录 Codex','codex_images.py'),
            ('stickers','表情包',settings['defaults'].get('auto_stickers',True),True,['defaults.auto_stickers','defaults.sticker_interval_seconds'], '各群自动收集选项在对应会话规则中','chat_media.py'),
            ('asr','接收语音',None,True,[], '复用微信转文字；需要微信登录，暂无独立 Whisper/API 配置','voice_inbox.py'),
            ('tts','语音回复',settings.get('voice_reply',{}).get('enabled',False),tts_ok,['voice_reply.enabled','voice_reply.provider','voice_reply.spontaneous','voice_reply.spontaneous_interval_minutes','tts.voice','tts.rate','tts.pitch','tts.volume'], '当前语音引擎：'+engine+'；通过微信原生语音发送，不播放电脑扬声器','chat_voice.py'),
            ('clone','音色克隆',engine=='gpt-sovits' and settings.get('voice_reply',{}).get('enabled',False),clone_ok,['voice_reply.provider','voice_reply.enabled'], '需单独部署 GPT-SoVITS 并提供自己的参考声音；可在语音引擎中切换',None),
            ('singing','翻唱',settings.get('singing',{}).get('enabled',False),clips,['singing.enabled'], '当前发送已准备的清唱：'+('、'.join(songs) or '暂无歌曲')+'；新歌曲需先准备音源','chat_singing.py'),
            ('monitor','重置预告监测',None,True,[], '内置任务中的 Codex 重置监测，每小时检查；任意 URL 监测未接入','reset_watch.py'),
        ]
        keys = {f['key'] for f in fields}
        return [{'id':ident,'name':name,'enabled':enabled,'available':bool(ok and (not file or (mods/file).is_file())),
                 'configurable':bool(config_keys),'detail':detail,'config_keys':[k for k in config_keys if k in keys],
                 'dependencies':[{'name':file or name,'available':bool(ok and (not file or (mods/file).is_file())), 'detail':'当前适配模块与依赖检查'}]}
                for ident,name,enabled,ok,config_keys,detail,file in definitions]

    def state(self):
        with self.lock:
            settings, voice = self.settings()
            revision = self.revision()
        status, contacts = self.probe()
        access = self.access_config()
        status['access'] = {'mode':'tailscale' if access else 'local', 'remote':False,
                            'origin':'', 'mobile_url':access.get('origin','')}
        with self.db() as db:
            targets = self.target_map(db,settings,contacts)
            fields, _, values = self.schema(settings,voice,targets)
            by_room = {v['room']:v for v in targets.values()}
            tasks = []
            for row in db.execute("SELECT * FROM tasks WHERE status!='cancelled' ORDER BY CASE WHEN status IN ('active','queued','failed') THEN 0 ELSE 1 END,due LIMIT 150"):
                tasks.append({'id':row['id'],'name':row['body'],'content':row['body'],
                              'time':dt.datetime.fromtimestamp(row['due']/1000,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
                              'repeat':row['repeat'],'status':row['status'],'last_status':row['last_status'],
                              'target_label':by_room.get(row['room'],{}).get('label','已记录会话'),
                              'cancellable':row['status'] in ('active','queued','failed')})
            status['stats'] = {'active_tasks':db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('active','queued')").fetchone()[0],
                               'pending_messages':db.execute("SELECT COUNT(*) FROM inbox WHERE status IN ('pending','generating','sending')").fetchone()[0]}
        return {'status':status,'config':{'revision':revision,'fields':fields,'values':values,
                'notes':['保存后由运行中的机器人即时读取，无需重启微信','具体会话规则覆盖默认规则；主动发消息白名单和时段逐会话设置','定时任务按北京时间执行；取消使用可恢复的取消状态','记忆内容仅在记忆手账页按需读取；不展示密钥或原始聊天正文']},
                'plugins':self.plugin_state(settings,voice,status,fields),'tasks':tasks,
                'targets':[{'id':key,**{k:v[k] for k in ('label','kind','configured')}} for key,v in targets.items()],
                'csrf_token':self.csrf_token}

    def memories(self, selected='personality'):
        with self.db() as db:
            person_memory.create_table(db)
            binding=self.meta(db,'binding',{})
            scopes=db.execute("SELECT * FROM memory_scopes WHERE room NOT LIKE '%@chatroom' ORDER BY updated DESC").fetchall()
            preferences=self.meta(db,'owner_personality_memory',[])
            queue={row['status']:row['n'] for row in db.execute('SELECT status,COUNT(*) n FROM person_memory_queue GROUP BY status')}
        labels={}
        try:
            token=(self.webox_state/'weagent/api-token').read_text(encoding='utf-8').strip()
            contacts=self.http_json('http://127.0.0.1:48080/ilink/bot/contacts',{'AuthorizationType':'ilink_bot_token','Authorization':'Bearer '+token,'X-WECHAT-UIN':'dafeiyu'})
            labels={c['roomid']:c.get('remark') or c.get('nickname') for c in contacts.get('contacts',[])}
        except (OSError,ValueError):pass
        listing=[{'id':row['id'],'label':'主人私聊' if row['room']==binding.get('known_chats',{}).get('webox.owner') else labels.get(row['room']) or '已保存的私聊 '+str(i+1)} for i,row in enumerate(scopes)]
        if selected=='personality':
            entries=[{'id':hashlib.sha256(text.encode()).hexdigest()[:24],'kind':'personality','text':text,'pinned':True,'archived':False} for text in preferences]
            revision=hashlib.sha256(json.dumps(preferences,ensure_ascii=False).encode()).hexdigest()
            usage={}
        else:
            row=next((row for row in scopes if row['id']==selected),None)
            if row is None:raise APIError(404,'没有找到这个私聊的记忆')
            item=person_memory.scope(row['room'],row['actor'])
            snapshot=person_memory.store([item],root=self.root/'data/chat/person-memory')
            entries=snapshot[item['key']];revision=snapshot['_revisions'][item['key']];usage=snapshot['_usage'][item['key']]
            usage={name:{k:value[k] for k in ('used','limit')} for name,value in usage.items()}
        return {'scope':selected,'scopes':listing,'entries':entries,'revision':revision,'usage':usage,'queue':queue,
                'policy':person_memory.policy(self.settings()[0])}

    def save_memory(self,body):
        selected=body.get('scope','personality');action=body.get('action')
        if action not in ('add','edit','remove','clear','retry'):raise APIError(400,'不支持的记忆操作')
        with self.lock:
            current=self.memories(selected)
            if body.get('revision')!=current['revision']:raise APIError(409,'记忆已更新，请刷新后再修改')
            if action=='retry':
                with self.db() as db:db.execute("UPDATE person_memory_queue SET status='pending',attempts=0,next_at=0 WHERE status='failed' AND room NOT LIKE '%@chatroom'")
                return {'memory':self.memories(selected),'message':'已重新安排失败的私聊记忆整理'}
            entry=next((e for e in current['entries'] if e['id']==body.get('id')),None)
            if action in ('edit','remove') and entry is None:raise APIError(404,'这条记忆已不存在')
            text=body.get('text','').strip() if isinstance(body.get('text',''),str) else ''
            if action in ('add','edit') and (not text or len(text)>(120 if selected=='personality' else 180) or '§' in text):raise APIError(400,'请填写长度合适的完整记忆')
            if selected=='personality':
                values=[e['text'] for e in current['entries']]
                if action=='clear':values=[]
                elif action=='add':values.append(text)
                elif action=='edit':values[values.index(entry['text'])]=text
                else:values.remove(entry['text'])
                if len(values)>8:raise APIError(400,'性格偏好最多8条，请先合并或删除')
                with self.db() as db:db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('owner_personality_memory',json.dumps(values,ensure_ascii=False)))
                person_memory.purge_text_logs([e['text'] for e in current['entries'] if e['text'] not in values],state=self.root/'data/chat')
            else:
                with self.db() as db:row=db.execute('SELECT room,actor FROM memory_scopes WHERE id=?',(selected,)).fetchone()
                if action=='clear':changes=[{'kind':e['kind'],'action':'remove','old':e['text']} for e in current['entries']]
                else:
                    kind=entry['kind'] if entry else body.get('kind','fact')
                    if kind not in ('fact','impression') or type(body.get('pinned',False)) is not bool:raise APIError(400,'记忆分类或置顶设置不正确')
                    changes=[{'kind':kind,'action':{'edit':'replace','remove':'remove','add':'add'}[action],
                              'old':entry['text'] if entry else '', 'text':text,'pinned':body.get('pinned',entry.get('pinned',False) if entry else False)}]
                    if entry and entry.get('expires_at') and action!='remove':changes[0]['expires_at']=entry['expires_at']
                item={**person_memory.scope(row['room'],row['actor']),'expected_revision':current['revision'],'changes':changes}
                try:person_memory.store([item],root=self.root/'data/chat/person-memory')
                except ValueError as error:raise APIError(409 if '已更新' in str(error) else 400,str(error)) from error
                if action in ('remove','clear','edit'):
                    with self.db() as db:person_memory.purge_history(db,row['room'],row['actor'],state=self.root/'data/chat')
            return {'memory':self.memories(selected),'message':'记忆已保存' if action=='add' else '记忆已更新，并清理相关本地模型记录'}

    def write_json(self, path, data):
        backup = self.root/'data/config-backups'
        backup.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.exists():
            dest = backup/(str(time.time_ns())+'-'+path.name)
            shutil.copy2(path,dest);dest.chmod(0o600)
        temporary = path.with_name(path.name+'.console.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(path)

    def save_config(self, body):
        values = body.get('values')
        if not isinstance(values,dict) or not values:
            raise APIError(400,'没有要保存的配置')
        with self.lock:
            if body.get('revision')!=self.revision():
                raise APIError(409,'配置已被更新，请刷新后重新修改')
            settings, voice = self.settings()
            contacts = self.probe()[1] if any(key.startswith('chat.') for key in values) else ()
            with self.db() as db:
                targets = self.target_map(db,settings,contacts)
            fields, paths, _ = self.schema(settings,voice,targets)
            definitions = {f['key']:f for f in fields}
            for key,value in values.items():
                f = definitions.get(key)
                if f is None:
                    raise APIError(400,'不支持修改这项配置：'+str(key))
                kind = f['type']
                if (kind=='boolean' and type(value) is not bool or
                    kind=='number' and (type(value) is not int or not f['min']<=value<=f['max']) or
                    kind in ('text','time','select') and (not isinstance(value,str) or len(value)>100)):
                    raise APIError(400,f['label']+'的值不正确')
                if kind=='select' and value not in [v['value'] for v in f['options']]:
                    raise APIError(400,'请选择已有的'+f['label'])
                if f.get('clock'):
                    try:
                        hour,minute=map(int,value.split(':'))
                        valid=len(value)==5 and 0<=hour<24 and 0<=minute<60 or value=='24:00' and f.get('end')
                    except (ValueError,TypeError):
                        valid=False
                    if not valid:
                        raise APIError(400,f['label']+'请用 HH:MM 格式')
            changed = set()
            for key,value in values.items():
                doc,path,_ = paths[key]
                data = voice if doc=='voice' else settings
                if len(path)>2 and path[-2] in ('hours','natural_hours'):
                    parent = data
                    for part in path[:-2]:
                        parent=parent.setdefault(part,{})
                    parent.setdefault(path[-2],['00:00','24:00'])
                set_path(data,path,value);changed.add(doc)
            for rule in settings.get('chats',{}).values():
                proactive=rule.get('proactive',{})
                if proactive.get('enabled'):
                    for key,value in {'hours':['09:00','23:00'],'interval_minutes':180,'idle_minutes':60,'max_per_day':3}.items():
                        proactive.setdefault(key,value)
            if 'settings' in changed:self.write_json(self.settings_path,settings)
            if 'voice' in changed:self.write_json(self.voice_path,voice)
        return self.state()

    def configure_chat(self, body):
        _, contacts = self.probe()
        with self.lock, self.db() as db:
            if body.get('revision') != self.revision():
                raise APIError(409,'配置已被更新，请刷新后重新选择')
            settings,_ = self.settings()
            target = self.target_map(db,settings,contacts).get(body.get('target_id'))
            if target is None:
                raise APIError(400,'请从当前微信联系人中选择聊天')
            known = self.meta(db,'binding',{}).get('known_chats',{})
            key = next((key for key,room in known.items() if room == target['room']),target['room'])
            settings.setdefault('chats',{}).setdefault(key,{})
            self.write_json(self.settings_path,settings)
        return self.state()

    def create_task(self, body):
        text = body.get('text')
        if not isinstance(text,str) or not 1<=len(text.strip())<=600:
            raise APIError(400,'请输入时间和提醒内容，最多600字')
        _,contacts = self.probe()
        with self.lock, self.db() as db:
            settings,_=self.settings();targets=self.target_map(db,settings,contacts)
            target=targets.get(body.get('target_id'))
            if target is None:
                raise APIError(400,'请选择已经绑定的聊天目标')
            owner=self.meta(db,'binding',{}).get('known_chats',{}).get('webox.owner')
            if not owner:raise APIError(409,'尚未绑定主人，暂时不能安排任务')
            try:due,repeat,content=chat_tasks.parse(text,int(time.time()*1000))
            except ValueError as exc:raise APIError(400,str(exc)) from exc
            ident='T'+secrets.token_hex(4)
            db.execute('INSERT INTO tasks(id,room,creator,source,body,due,repeat) VALUES(?,?,?,?,?,?,?)',
                       (ident,target['room'],owner,'',content,due,repeat))
        result=self.state();result['task_id']=ident;result['message']='任务已写入当前机器人的调度列表'
        return result

    def cancel_task(self, body):
        ident=body.get('id')
        if not isinstance(ident,str):raise APIError(400,'任务编号不正确')
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            task=db.execute('SELECT status FROM tasks WHERE id=?',(ident,)).fetchone()
            if not task:raise APIError(404,'没有找到这项任务')
            for row in db.execute("SELECT prompt FROM inbox WHERE status IN ('generating','sending')"):
                if row['prompt'] and json.loads(row['prompt']).get('_task_id')==ident:
                    raise APIError(409,'任务已开始执行，暂时不能取消本次发送')
            if task['status'] not in ('active','queued','failed','cancelled'):
                raise APIError(409,'这项任务已经完成')
            db.execute("UPDATE tasks SET status='cancelled' WHERE id=?",(ident,))
            db.execute("UPDATE inbox SET status='quiet',prompt='' WHERE status IN ('pending','waiting_wechat','waiting_model') AND json_extract(NULLIF(prompt,''),'$._task_id')=?",(ident,))
        result=self.state();result['message']='任务已取消，不会执行尚未发出的提醒'
        return result


def save_persona(root,body):
    text=body.get('text')
    if not isinstance(text,str) or len(text)>32768:raise APIError(400,'人设须为文字，最多32768字')
    path=root/'resources/persona.md'
    if path.exists():
        backup=root/'data/persona-backups';backup.mkdir(parents=True,exist_ok=True)
        shutil.copy(path,backup/(str(time.time_ns())+'.md'))
    temporary=path.with_suffix('.tmp');temporary.write_text(text,encoding='utf-8');temporary.replace(path)
    return {'saved':True}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args,directory=str(args[2].backend.root/'web'),**kwargs)

    def allowed_host(self):
        host = self.headers.get('Host')
        if not self.server.remote_only:
            return host in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        access = self.server.backend.access_config()
        return bool(access and host == urlsplit(access['origin']).netloc and
                    secrets.compare_digest(self.headers.get('Tailscale-User-Login',''), access['allowed_login']))

    def request_origin(self):
        host = self.headers.get('Host','')
        access = self.server.backend.access_config()
        return access['origin'] if access and host == urlsplit(access['origin']).netloc else 'http://' + host

    def json_response(self, status, value):
        data=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)

    def do_GET(self):
        if not self.allowed_host():return self.json_response(403,{'error':'只允许本机控制台访问'})
        path=urlsplit(self.path).path
        if path=='/api/resources':return self.api_call(self.server.backend.resources.state)
        if path=='/api/persona':return self.json_response(200,{'text':(self.server.backend.root/'resources/persona.md').read_text(encoding='utf-8') if (self.server.backend.root/'resources/persona.md').exists() else ''})
        if path=='/api/state':return self.api_call(self.server.backend.state)
        if path=='/api/memory':return self.api_call(lambda:self.server.backend.memories(parse_qs(urlsplit(self.path).query).get('scope',['personality'])[0]))
        if path=='/api/mobile-qr.svg':
            access = self.server.backend.access_config()
            if not access:return self.json_response(404,{'error':'手机连接地址尚未配置'})
            import qrcode
            import qrcode.image.svg
            output = io.BytesIO()
            qrcode.make(access['origin'],image_factory=qrcode.image.svg.SvgPathImage).save(output)
            data = output.getvalue()
            self.send_response(200);self.send_header('Content-Type','image/svg+xml')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(data)
            return
        if path.startswith('/api/'):return self.json_response(404,{'error':'没有这个接口'})
        if path not in ('/','/index.html','/live.js','/resources.js','/resources.css','/manifest.webmanifest','/favicon.ico') and not path.startswith(('/assets/','/icons/')):
            return self.send_error(404)
        if '..' in path:return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        origins = (self.request_origin(),) if self.server.remote_only else (None,self.request_origin())
        if (not self.allowed_host() or self.headers.get('Origin') not in origins or
                not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),self.server.backend.csrf_token)):
            return self.json_response(403,{'error':'控制台验证已过期，请刷新页面'})
        routes={'/api/resources/download':lambda body:self.server.backend.resources.start(body.get('id')),
                '/api/resources/import-character':lambda body:self.server.backend.resources.import_character(body),
                '/api/resources/activate-persona':lambda body:self.server.backend.resources.activate_persona(body.get('id')),
                '/api/persona':lambda body:save_persona(self.server.backend.root,body),
                '/api/config':self.server.backend.save_config,'/api/chats/configure':self.server.backend.configure_chat,'/api/tasks':self.server.backend.create_task,
                '/api/tasks/cancel':self.server.backend.cancel_task,'/api/memory':self.server.backend.save_memory,'/api/check':lambda body:self.server.backend.state()}
        action=routes.get(urlsplit(self.path).path)
        if action is None:return self.json_response(404,{'error':'没有这个接口'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            limit=18*1024**2 if urlsplit(self.path).path=='/api/resources/import-character' else 131072
            if not 0<length<=limit:raise ValueError()
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError()
        except (ValueError,TypeError):return self.json_response(400,{'error':'请求内容不正确'})
        return self.api_call(lambda:action(body))

    def api_call(self, action):
        try:
            result = action()
            if 'status' in result:
                result['status']['access'].update(origin=self.request_origin(), remote=self.request_origin().startswith('https://'))
            return self.json_response(200,result)
        except APIError as exc:return self.json_response(exc.status,{'error':exc.message})
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,RuntimeError) as exc:
            print('Console request failed:',type(exc).__name__,flush=True)
            return self.json_response(503,{'error':'当前服务或配置暂时不可读取，请稍后刷新'})

    def list_directory(self, path):
        self.send_error(404)

    def end_headers(self):
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        super().end_headers()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8877)
    parser.add_argument('--mobile-port',type=int,default=8878)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.backend=ConsoleBackend();server.remote_only=False
    mobile=ThreadingHTTPServer(('127.0.0.1',args.mobile_port),Handler)
    mobile.backend=server.backend;mobile.remote_only=True
    threading.Thread(target=mobile.serve_forever,daemon=True).start()
    watch_stop(server.backend.root/'data/run/stop.flag',server.shutdown)
    print(f'WhaleNest live console: http://127.0.0.1:{args.port}/',flush=True)
    try:
        server.serve_forever()
    finally:
        mobile.shutdown();mobile.server_close();server.server_close()


if __name__=='__main__':main()

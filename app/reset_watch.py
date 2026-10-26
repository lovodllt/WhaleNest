"""Watch the site's reset alerts and queue facts for DSH to phrase."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import urllib.request
from zoneinfo import ZoneInfo

URL = 'https://codex-reset.com/api/forecast?tz=Asia%2FShanghai'
INTERVAL = 3600_000


def timestamp(value):
    return int(dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)


def fetch():
    request = urllib.request.Request(URL,headers={'User-Agent':'Dafeiyu-Reset-Watch/1.0','Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response:
        data = json.load(response)
    if not isinstance(data,dict) or 'updated_at' not in data:
        raise ValueError('Unexpected reset forecast response')
    return data


def alert(data,now_ms):
    if abs(now_ms-timestamp(data['updated_at']))>3600_000:
        raise ValueError('Stale reset forecast')
    item = data.get('latest_alert') or {}
    kind,state = item.get('kind'),item.get('state')
    window = item.get('window') or {}
    deadline = window.get('target_at') or window.get('end_at')
    if kind=='watch':
        if state!='active' or ((item.get('score') or 0)<83 and not deadline):
            return None
    elif kind!='reset' or state!='confirmed':
        return None
    at = timestamp(item['source_at'])
    if not 0<=now_ms-at<=86400_000:
        return None
    if kind=='watch' and deadline and timestamp(deadline)<=now_ms:
        return None
    if kind=='watch':
        text = 'Codex有重置预告啦🐟'
        if deadline:
            local = dt.datetime.fromtimestamp(timestamp(deadline)/1000,ZoneInfo('Asia/Shanghai'))
            text += '\n预计北京时间'+local.strftime('%m月%d日%H:%M')+'前'
        text += '\n这是预告，到账还要等确认'
    elif item.get('confirmation_source')=='operator_observed':
        text = '站点检测到Codex重置啦🐟\n还在等官方进一步确认'
    else:
        text = '站点确认Codex重置啦🐟\n可以看看额度有没有回来啦'
    return {'id':str(item['id'])+':'+kind,'at':at,'text':text}


def accept(db,task,data,now_ms,owner):
    task_id,room,creator,source = task
    if not db.execute("SELECT 1 FROM tasks WHERE id=? AND status='active'",(task_id,)).fetchone():
        return
    key = 'reset_watch:'+task_id
    row = db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    state = json.loads(row[0]) if row else {'started_at':now_ms,'seen':[]}
    item = alert(data,now_ms)
    with db:
        if item and item['id'] not in state['seen']:
            if row and item['at']>=state['started_at']:
                event_id = 'reset-watch-'+hashlib.sha256((task_id+'\0'+item['id']).encode()).hexdigest()
                current = {'_room':room,'_task_id':task_id,'_task_target':creator,'_task_ref':source,
                           '_notice':item['text'],'会话类型':'群聊' if room.endswith('@chatroom') else '私聊',
                           '发言':item['text'],'消息时间':now_ms,'点名':True,'主人':creator==owner}
                db.execute('INSERT OR IGNORE INTO inbox(id,prompt,time) VALUES(?,?,?)',
                           (event_id,json.dumps(current,ensure_ascii=False),now_ms))
            state['seen'] = (state['seen']+[item['id']])[-100:]
        state.update(last_checked=now_ms,error=None)
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(state)))


class Worker:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.task = None

    def tick(self,db,now_ms,owner):
        with db:
            db.execute("UPDATE inbox SET status='pending' WHERE status IN ('waiting_wechat','waiting_model') AND time<=?",(now_ms,))
        if self.future is not None:
            if not self.future.done():
                return
            try:
                accept(db,self.task,self.future.result(),now_ms,owner)
            except Exception as error:
                key = 'reset_watch:'+self.task[0]
                row = db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
                state = json.loads(row[0]) if row else {'started_at':now_ms,'seen':[]}
                state.update(last_checked=now_ms,error=type(error).__name__)
                with db:
                    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(state)))
            self.future = None
        self.task = db.execute("SELECT id,room,creator,source FROM tasks WHERE repeat='reset_watch' AND status='active' AND due<=? ORDER BY due LIMIT 1",(now_ms,)).fetchone()
        if self.task:
            with db:
                db.execute('UPDATE tasks SET due=? WHERE id=?',(now_ms+INTERVAL,self.task[0]))
            self.future = self.pool.submit(fetch)

    def close(self):
        self.pool.shutdown()

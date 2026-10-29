"""Chat-scoped reminders and fixed slash commands."""
import datetime as dt
import json
from pathlib import Path
import re
import reset_watch
from zoneinfo import ZoneInfo
from chat_web import strip_name

ZONE=ZoneInfo('Asia/Shanghai')
HELP=Path(__file__).with_name('帮助待审核.txt')
TIME_HINT=r'\d+\s*(?:秒|分钟|小时|天)|今天|明天|后天|每天|每周|[一二三四五六七八九十两\d]+点|\d{1,2}[:：]\d{2}'


def command(text,name):
    text=strip_name(text,name)
    match=re.match(r'^/(task|list_task|help)(?=\s|$|[\u4e00-\u9fff])\s*(.*)',text,re.S|re.I)
    if match:return match[1].lower(),match[2].strip()
    if re.search(r'提醒我|叫我|定时发|安排任务',text) and re.search(TIME_HINT,text):return 'task',text
    return None


def create_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,room TEXT NOT NULL,creator TEXT NOT NULL,source TEXT NOT NULL,
        body TEXT NOT NULL,due INTEGER NOT NULL,repeat TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',last_status TEXT NOT NULL DEFAULT '')''')


def number(text):
    if text.isdecimal():return int(text)
    digits={c:i for i,c in enumerate('零一二三四五六七八九')};digits['两']=2
    if '十' in text:
        left,right=text.split('十');return digits.get(left,1)*10+digits.get(right,0)
    if text in digits:return digits[text]
    raise ValueError('请用数字写清时间，例如10分钟后或明天09:00')


def parse(text,now_ms):
    now=dt.datetime.fromtimestamp(now_ms/1000,ZONE)
    relative=re.search(r'([\d零一二两三四五六七八九十]+)\s*(秒|分钟|小时|天)(?:以后|之后|后)',text)
    repeat='once'
    if relative:
        if re.search(r'[零一二两三四五六七八九十\d]+\s*(?:小时|分钟|秒|天)',text[:relative.start()]):raise ValueError('请把间隔写成一种单位，例如90分钟后')
        amount=number(relative[1]);seconds=amount*{'秒':1,'分钟':60,'小时':3600,'天':86400}[relative[2]]
        if seconds<=0:raise ValueError('请安排一个未来的时间')
        when=now+dt.timedelta(seconds=seconds);body=text[:relative.start()]+text[relative.end():]
    else:
        clock=re.search(r'(凌晨|早上|上午|中午|下午|晚上|晚间)?\s*((?:\d{1,2}|[零一二两三四五六七八九十]+))(?:[:：](\d{1,2})|点(半|[\d零一二三四五六七八九十]+分?)?)',re.sub(r'每周[一二三四五六日天]',lambda m:' '*len(m[0]),text))
        if not clock:raise ValueError('请写清时间，例如/task 10分钟后 喝水，或/task 每天09:00 喝水')
        hour=number(clock[2]);minute=number(clock[3]) if clock[3] else (30 if clock[4]=='半' else number(clock[4].rstrip('分')) if clock[4] else 0)
        if clock[1] in ('中午','下午','晚上','晚间') and hour<12:hour+=12
        if not 0<=hour<24 or not 0<=minute<60:raise ValueError('时间不正确，请用00:00到23:59')
        when=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
        weekly=re.search(r'每周([一二三四五六日天])',text)
        dated=re.search(r'\d{4}-\d{2}-\d{2}',text)
        if weekly:
            day='一二三四五六日'.find(weekly[1].replace('天','日'));when+=dt.timedelta(days=(day-now.weekday())%7);repeat='weekly'
        elif '每天' in text:repeat='daily'
        elif dated:when=when.replace(**dict(zip(('year','month','day'),map(int,dated[0].split('-')))))
        elif '后天' in text:when+=dt.timedelta(days=2)
        elif '明天' in text:when+=dt.timedelta(days=1)
        if when<=now:
            if repeat!='once' or not re.search(r'今天|明天|后天|\d{4}-\d{2}-\d{2}',text):when+=dt.timedelta(days=7 if repeat=='weekly' else 1)
            else:raise ValueError('这个时间已经过去了，请换个未来时间')
        body=text[:clock.start()]+text[clock.end():]
        body=re.sub(r'每周[一二三四五六日天]|每天|今天|明天|后天|\d{4}-\d{2}-\d{2}','',body)
    body=re.sub(r'^(?:(?:请|帮我|麻烦|提醒我|提醒|叫我|安排任务|定时发)\s*)+','',body).strip(' ，,:：')
    if not body:raise ValueError('还缺提醒内容，例如/task 10分钟后 喝水')
    if len(body)>500:raise ValueError('任务内容请简短一些，最多500字')
    return int(when.timestamp()*1000),repeat,body


def handle(db,room,source,text,name,event_id,now_ms,settings):
    cmd=command(text,name)
    if not cmd:return None
    kind,arg=cmd
    if kind=='help':
        return HELP.read_text(encoding='utf-8').strip() if settings.get('help_approved',False) else '帮助菜单还在整理，暂时可以用/task安排提醒、/list_task查看任务'
    if kind=='list_task':
        rows=db.execute("SELECT id,due,repeat,body,status,last_status FROM tasks WHERE room=? AND status IN ('active','queued','failed') ORDER BY due",(room,)).fetchall()
        if not rows:return '当前聊天没有待执行任务'
        return '当前聊天的任务（北京时间）\n'+'\n'.join(f'{i}｜{dt.datetime.fromtimestamp(t/1000,ZONE):%m-%d %H:%M:%S}｜'+{'once':'一次','daily':'每天','weekly':'每周','reset_watch':'监测·每小时'}[r]+f'｜{b[:120]}'+('｜发送失败' if s=='failed' or last=='failed' else '') for i,t,r,b,s,last in rows[:15])+('\n仅显示最早的15项' if len(rows)>15 else '')
    cancel=re.fullmatch(r'(?:取消|删除|cancel)\s*(T[0-9a-f]{8})',arg,re.I)
    if cancel:
        task_id=cancel[1].upper()[:1]+cancel[1][1:].lower()
        with db:
            changed=db.execute("UPDATE tasks SET status='cancelled' WHERE id=? AND room=? AND creator=? AND status IN ('active','queued','failed')",(task_id,room,source['from'])).rowcount
            if changed:db.execute("UPDATE inbox SET status='quiet',prompt='' WHERE status IN ('pending','waiting_wechat','waiting_model') AND json_extract(NULLIF(prompt,''),'$._task_id')=?",(task_id,))
        return '已取消任务 '+task_id if changed else '没找到你在当前聊天中创建的这项任务'
    if room.endswith('@chatroom') and (source.get('type')!='text' or '\n' in text or len(text)>120):return '群聊任务请用不超过120字的单行文字发送'
    if re.search(r'codex-reset\.com|(?:监控|关注).*Codex.*重置',arg,re.I):
        task_id='T'+event_id[:8]
        with db:
            db.execute('INSERT OR IGNORE INTO tasks(id,room,creator,source,body,due,repeat) VALUES(?,?,?,?,?,?,?)',
                       (task_id,room,source['from'],source['msgid'],'监控Codex重置预告 · codex-reset.com',now_ms,'reset_watch'))
        return f'已安排 {task_id}｜每小时检查Codex重置预告\n只通知新预告和确认重置，不提醒概率变化\n群聊会尝试@发起人，无法@时发普通消息'
    try:due,repeat,body=parse(arg,now_ms)
    except ValueError as exc:return str(exc)
    task_id='T'+event_id[:8]
    with db:db.execute('INSERT OR IGNORE INTO tasks(id,room,creator,source,body,due,repeat) VALUES(?,?,?,?,?,?,?)',(task_id,room,source['from'],source['msgid'],body,due,repeat))
    label={'once':'一次','daily':'每天','weekly':'每周'}[repeat]
    return f'已安排 {task_id}｜{label}\n北京时间 {dt.datetime.fromtimestamp(due/1000,ZONE):%Y-%m-%d %H:%M:%S}\n{body}\n'+(('到时在本群@发起人' if settings.get('outgoing_mentions',True) else '到时在本群发普通消息提醒，暂不@') if room.endswith('@chatroom') else '到时发到这个私聊')


def enqueue_due(db,now_ms,owner):
    rows=db.execute("SELECT id,room,creator,source,body,due,repeat FROM tasks WHERE status='active' AND repeat!='reset_watch' AND due<=? ORDER BY due",(now_ms,)).fetchall()
    with db:
        for task_id,room,creator,source,body,due,repeat in rows:
            event_id='task-'+task_id+'-'+str(due)
            current={'_room':room,'_task_id':task_id,'_task_target':creator,'_task_ref':source,'会话类型':'群聊' if room.endswith('@chatroom') else '私聊','发言':body,'消息时间':now_ms,'点名':True,'主人':creator==owner}
            db.execute('INSERT OR IGNORE INTO inbox(id,prompt,time) VALUES(?,?,?)',(event_id,json.dumps(current,ensure_ascii=False),now_ms))
            if repeat=='once':db.execute("UPDATE tasks SET status='queued',last_status='queued' WHERE id=?",(task_id,))
            else:
                step=dt.timedelta(days=1 if repeat=='daily' else 7)
                future=dt.datetime.fromtimestamp(due/1000,ZONE)
                while future.timestamp()*1000<=now_ms:future+=step
                db.execute("UPDATE tasks SET due=?,last_status='queued' WHERE id=?",(int(future.timestamp()*1000),task_id))


def finished(db,task_id,status):
    db.execute("UPDATE tasks SET last_status=?,status=CASE WHEN repeat='once' THEN ? ELSE status END WHERE id=?",(status,status,task_id))

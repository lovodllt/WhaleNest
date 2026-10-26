import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

SETTINGS = Path(__file__).resolve().parents[1]/'config/chat.json'


def load_settings():
    return json.loads(SETTINGS.read_text())


def for_chat(settings, binding, room):
    key = next((key for key, target in binding.get('known_chats', {}).items() if target == room), room)
    return {**settings['defaults'], **settings['chats'].get(key, {})}


def within_hours(hours, now):
    start, end = [int(h.split(':')[0])*60 + int(h.split(':')[1]) for h in hours]
    minute = now.hour*60 + now.minute
    return start <= minute < end if start <= end else minute >= start or minute < end


def natural_allowed(rule, now_ms, timezone, last_wake, muted_until=0):
    now = datetime.datetime.fromtimestamp(now_ms/1000, ZoneInfo(timezone))
    return (rule['natural_reply'] and 0 <= now_ms-last_wake <= 600_000 and now_ms >= muted_until
            and within_hours(rule.get('natural_hours', ['00:00','24:00']), now))


def proactive_due(config, state, now_ms, last_incoming, timezone):
    if not config.get('enabled', False):
        return False
    now = datetime.datetime.fromtimestamp(now_ms/1000, ZoneInfo(timezone))
    return (now_ms >= state['next_at']
            and now_ms-last_incoming >= config['idle_minutes']*60_000
            and (state.get('day') != now.date().isoformat() or state.get('count', 0) < config['max_per_day'])
            and within_hours(config['hours'], now))

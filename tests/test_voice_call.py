from contextlib import closing
import io
import json
from pathlib import Path
import queue
import runpy
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import call_audio
import dsh_chat
import group_bridge
import voice_call as call
from runtime_support import file_lock


class VoiceCallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        with closing(sqlite3.connect(self.state/'bridge.sqlite3')) as db, db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT INTO meta VALUES(?,?)',('binding',json.dumps({'known_chats':{'webox.owner':'owner-private'}})))
        for target in (call,group_bridge):
            context = patch.object(target,'STATE',self.state)
            context.start();self.addCleanup(context.stop)
        for context in (patch.object(call,'settings',return_value={'enabled':True}),
                        patch('chat_rules.load_settings',return_value={'reply_paused':False,'memory':{'enabled':False}})):
            context.start();self.addCleanup(context.stop)

    def session(self, chat=None):
        return call.CallSession({},'owner-private',Mock(),chat or Mock(),queue.Queue())

    @staticmethod
    def say(session, ident, text):
        session.event({'type':'speech_start','utterance_id':ident})
        session.event({'type':'speech_end','utterance_id':ident})
        session.event({'type':'transcript','utterance_id':ident,'text':text})

    def test_only_bound_owner_and_unique_matching_call(self):
        config={'enabled':True,'caller_names':['本机备注']}
        self.assertEqual(call.validate(config,{'known_chats':{'webox.owner':'owner-private'}}),'owner-private')
        for invalid in ({}, {'known_chats':{'webox.owner':'group@chatroom'}}):
            with self.assertRaises(ValueError):call.validate(config,invalid)
        frame={'frame':'observed','title':'微信','labels':['本机备注'],'buttons':[{'name':'接听'}]}
        self.assertEqual(call.choose_frame([frame],config['caller_names']),frame)
        self.assertIsNone(call.choose_frame([frame,dict(frame,frame='ambiguous')],config['caller_names']))
        self.assertIsNone(call.choose_frame([frame],['其他人']))
        dial=dict(frame,title='本机备注',buttons=[{'name':'语音通话'}])
        self.assertEqual(call.choose_frame([dial],config['caller_names'],True),dial)
        self.assertIsNone(call.choose_frame([dict(dial,title='群')],config['caller_names'],True))

    def test_short_plain_text_fallback_but_not_broken_json(self):
        self.assertEqual(call.parse_reply('主人，我在呢'),{'utterances':['主人，我在呢'],'hang_up':False})
        self.assertEqual(call.parse_reply('```json\n{"utterances":[],"hang_up":false}\n```')['utterances'],[])
        for invalid in ('','{"utterances":','["不对"]','```json\n{"broken":','a'*81,
                        '{"utterances":["一句"],"hang_up":"false"}'):
            with self.assertRaises(ValueError):call.parse_reply(invalid)

    def test_barge_in_discards_old_model_and_keeps_latest_context(self):
        entered, release = threading.Event(),threading.Event()
        contexts=[]
        def reply(_session,prompt,**kwargs):
            contexts.append(json.loads(prompt[len(call.RULES):]))
            if len(contexts)==1:
                entered.set();release.wait(timeout=5)
                return '{"utterances":["过时的回答"],"hang_up":false}'
            return '{"utterances":["跟上新话题啦"],"hang_up":false}'
        session=self.session(Mock(reply=reply))
        session.play=Mock(return_value=True)
        self.say(session,1,'先聊旧话题')
        session.tick();self.assertTrue(entered.wait(timeout=3))
        self.say(session,2,'等等，换一个话题')
        release.set();session.worker.join(timeout=3)
        session.play.assert_not_called()
        session.tick();session.worker.join(timeout=3)
        session.play.assert_called_once_with('跟上新话题啦',2)
        self.assertEqual([m['text'] for m in contexts[-1]['当前通话']],['先聊旧话题','等等，换一个话题'])
        self.assertEqual(session.history[-1]['delivery'],'verified')

    def test_interrupted_audio_is_not_recorded_as_said(self):
        session=self.session(Mock(reply=Mock(return_value='{"utterances":["未播放完整"],"hang_up":false}')))
        def interrupted(_text,_generation):
            session.event({'type':'speech_start','utterance_id':2})
            return False
        session.play=interrupted
        self.say(session,1,'说句话')
        session.tick();session.worker.join(timeout=3)
        self.assertFalse(any(m['role']=='assistant' for m in session.history))
        self.assertEqual(session.events.get_nowait(),{'type':'playback','status':'uncertain'})
        with closing(sqlite3.connect(self.state/'bridge.sqlite3')) as db, db:
            recent=json.loads(db.execute("SELECT value FROM meta WHERE key LIKE 'recent:%'").fetchone()[0])
        self.assertEqual([m['发言'] for m in recent],['说句话'])

    def test_forgetting_memory_invalidates_pending_call_and_does_not_restore_it(self):
        session=self.session()
        self.assertTrue(session.current(0))
        key=group_bridge.room_key('owner-private')
        with closing(sqlite3.connect(self.state/'bridge.sqlite3')) as db, db:
            db.execute('INSERT INTO meta VALUES(?,?)',('memory_privacy_generation:'+key,'1'))
        self.assertFalse(session.current(0))
        self.assertFalse(session.record('不应写回的旧内容'))
        with closing(sqlite3.connect(self.state/'bridge.sqlite3')) as db, db:
            self.assertIsNone(db.execute("SELECT value FROM meta WHERE key LIKE 'recent:%'").fetchone())
        log=self.state/'call-sessions/2026'/(session.session_prefix+'1-1')/'session.v4.jsonl'
        log.parent.mkdir(parents=True);log.write_text('late model log',encoding='utf-8')
        session.purge_if_forgotten()
        self.assertFalse(log.exists())

    def test_memory_purge_removes_only_this_contacts_call_logs(self):
        import person_memory
        short=group_bridge.room_key('owner-private')
        logs=[]
        for name in ('webox-call-'+short+'-one-1','webox-call-another-contact-one-1'):
            path=self.state/'call-sessions/2026'/name/'session.v4.jsonl'
            path.parent.mkdir(parents=True);path.write_text('test transcript',encoding='utf-8');logs.append(path)
        with closing(sqlite3.connect(self.state/'bridge.sqlite3')) as db, db:
            db.execute('CREATE TABLE inbox(id TEXT,prompt TEXT,time INTEGER,status TEXT)')
            person_memory.create_table(db)
            person_memory.purge_history(db,'owner-private','owner-private',state=self.state)
        self.assertFalse(logs[0].exists())
        self.assertTrue(logs[1].exists())

    def test_ordinary_inbox_is_not_consumed_during_call(self):
        with file_lock(self.state/'conversation.lock'),patch.object(group_bridge,'_process_one') as process:
            self.assertFalse(group_bridge.process_one(None,None,None))
            process.assert_not_called()
        with patch.object(group_bridge,'_process_one',return_value=True) as process:
            self.assertTrue(group_bridge.process_one(None,None,None))
            process.assert_called_once()

    def test_failed_preparation_never_answers_or_hangs_up_unowned_call(self):
        native=Mock(close=Mock(return_value=[]))
        process=Mock(stdout=io.BytesIO(b'{"type":"error","error":"missing_model"}\n'),stdin=io.BytesIO())
        process.poll.return_value=0
        with patch.object(call.subprocess,'Popen',return_value=process),patch.object(call,'DshChat') as model:
            with self.assertRaisesRegex(RuntimeError,'未准备好'):
                call.connected({'caller_names':['本机备注']},'owner-private',native,'observed',1)
        model.assert_not_called()
        native.controls.assert_not_called()
        native.close.assert_called_once()

    def test_audio_commands_use_container_virtual_devices_and_shared_lock(self):
        native=call_audio.NativeCallAudio('test-container','call-unique')
        capture=Mock()
        with patch.object(call_audio.subprocess,'Popen',return_value=capture) as popen:
            native.capture()
            command=popen.call_args.args[0]
            self.assertEqual(command[:3],['docker','exec','-i'])
            self.assertIn('--device=whalenest_call_rx.monitor',command)
            self.assertIn('--stream-name=call-unique',command)
        with patch.object(call_audio.subprocess,'Popen',return_value=Mock()) as popen, \
                patch.object(call_audio,'ready',return_value=True):
            native.playback(24000,1)
            self.assertIn("'--device=voice_bus'",popen.call_args.args[0][-1])
        native.run=Mock(side_effect=['voice_bus','1','',
                    '[{"name":"whalenest_call_rx","index":2}]','[{"name":"dafeiyu_mic","index":3}]'])
        native.route=Mock()
        with patch.object(call_audio.subprocess,'Popen',return_value=Mock()) as popen, \
                patch.object(call_audio,'ready',return_value=True):
            native.acquire()
            self.assertIn('/webox/state/weagent/ui-send.lock',popen.call_args.args[0][-1])

    def test_streaming_pcm_reaches_only_call_player_with_current_voice_profile(self):
        class Capture(io.BytesIO):
            def close(self):
                self.saved=self.getvalue()
                super().close()
        session=self.session()
        samples=b'\x00\x01'*1200
        tts=Mock(stdin=Capture(),stdout=io.BytesIO(samples))
        player=Mock(stdin=Capture(),stdout=io.BytesIO(),returncode=0)
        for process in (tts,player):
            process.poll.return_value=0;process.wait.return_value=0
        session.native.playback.return_value=player
        with patch.object(call.subprocess,'Popen',return_value=tts):
            self.assertTrue(session.play('主人，我在呢',0))
        self.assertEqual(player.stdin.saved,samples)
        self.assertEqual(json.loads(tts.stdin.saved)['profile'],str(ROOT/'config/voice.json'))
        session.native.playback.assert_called_once_with(24000,1)
        session.native.stop_streams.assert_not_called()

    def test_dsh_call_uses_persona_but_never_attaches_action_tools(self):
        process=Mock(stdout=iter(()))
        with patch.object(dsh_chat,'STATE',self.state),patch.object(dsh_chat.subprocess,'Popen',return_value=process) as popen, \
                patch.object(dsh_chat.DshChat,'rpc') as rpc,patch.object(dsh_chat.subprocess,'check_output') as resolve:
            chat=dsh_chat.DshChat('dafeiyu-call',max_tokens=768)
            self.assertTrue(chat.use_persona)
            self.assertFalse(chat.interactive)
            self.assertNotIn('--patch',popen.call_args.args[0])
            self.assertEqual(rpc.call_args.args[1]['maxTokens'],768)
            resolve.assert_not_called()
            chat.close()

    def test_fast_mode_only_changes_call_profile(self):
        namespace=runpy.run_path(str(ROOT/'scripts/manage.py'))
        root=self.state/'package';(root/'app').mkdir(parents=True);(root/'config').mkdir()
        (root/'app/person_memory.py').write_text("INSTRUCTION='''test memory instruction'''",encoding='utf-8')
        (root/'config/voice-call.json').write_text('{"fast_mode":true}',encoding='utf-8')
        env={'DSH_HOME':str(self.state/'dsh'),'DAFEIYU_MODEL':'deepseek-chat'}
        profiles=namespace['profiles']
        with patch.dict(profiles.__globals__,ROOT=root,DATA=root/'data',environment=lambda:env):
            profiles()
        import yaml
        providers={}
        for name in ('direct','call'):
            doc=yaml.safe_load((self.state/'dsh/profiles'/('dafeiyu-'+name)/'cordis.patch.yml').read_text(encoding='utf-8'))
            providers[name]=doc[-1]['insert'][-1]['config']['providers']['configured']
            if name=='call':
                prompt=next(e for e in doc if e.get('id')=='system-prompt')['config']['personaPrefix']
                self.assertNotIn('[[SILENT]]',prompt)
        self.assertNotIn('reasoning',providers['direct'])
        self.assertEqual(providers['call']['reasoning'],'off')
        self.assertEqual(providers['call']['models'][0]['id'],providers['direct']['models'][0]['id'])


if __name__=='__main__':unittest.main()

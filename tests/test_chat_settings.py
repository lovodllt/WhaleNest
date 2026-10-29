import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from console_server import APIError,ConsoleBackend
from chat_rules import for_chat


class ChatSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        (self.root/'config').mkdir();(self.root/'config/resources.json').write_text('[]')
        self.backend=ConsoleBackend(self.root)
        self.settings=json.loads((ROOT/'config/chat.example.json').read_text())
        self.backend.write_json(self.backend.settings_path,self.settings)
        self.backend.db_path.parent.mkdir(parents=True)
        self.binding={'self_ids':['bot'],'rooms':{
            'friend':{'roomid':'friend','remark':'好友'},
            'current@chatroom':{'roomid':'current@chatroom','nickname':'当前的群'}},
            'known_chats':{'webox.owner':'friend'}}
        with self.backend.db() as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO meta VALUES(?,?)',('binding',json.dumps(self.binding)))
        for target in (patch.object(self.backend,'probe',return_value=({},list(self.binding['rooms'].values()))),
                       patch.object(self.backend,'state',return_value={'ok':True})):
            target.start();self.addCleanup(target.stop)

    def targets(self):
        with self.backend.db() as db:
            return self.backend.target_map(db,self.settings)

    def test_new_install_selects_its_own_chat_and_saves_independent_rule(self):
        token=self.backend.target_id('current@chatroom')
        self.assertFalse(self.targets()[token]['configured'])
        fields,_,_=self.backend.schema(self.settings,{},self.targets())
        self.assertFalse(any(f['key'].startswith('chat.') for f in fields))
        self.backend.configure_chat({'target_id':token,'revision':self.backend.revision()})
        self.backend.save_config({'revision':self.backend.revision(),'values':{f'chat.{token}.natural_reply':True}})
        saved=self.backend.settings()[0]
        self.assertEqual(saved['chats'],{'current@chatroom':{'natural_reply':True}})
        self.assertTrue(for_chat(saved,self.binding,'current@chatroom')['natural_reply'])
        self.assertFalse(for_chat(saved,self.binding,'friend')['natural_reply'])
        self.assertFalse(saved['chats']['current@chatroom'].get('proactive',{}).get('enabled',False))

    def test_unbound_old_rules_are_hidden_and_unselectable(self):
        self.settings['chats']={'webox.test':{'label':'旧测试群','natural_reply':True},
                                'other-device@chatroom':{'label':'旧真实群'}}
        self.backend.write_json(self.backend.settings_path,self.settings)
        targets=self.targets()
        self.assertEqual({t['label'] for t in targets.values()},{'好友','当前的群'})
        fields,_,_=self.backend.schema(self.settings,{},targets)
        self.assertFalse(any(f['key'].startswith('chat.') for f in fields))
        before=self.backend.settings_path.read_bytes()
        with self.assertRaises(APIError):
            self.backend.configure_chat({'target_id':self.backend.target_id('other-device@chatroom'),
                                         'revision':self.backend.revision()})
        self.assertEqual(self.backend.settings_path.read_bytes(),before)

    def test_existing_alias_keeps_rules_and_uses_current_wechat_name(self):
        self.binding['known_chats']['webox.test']='current@chatroom'
        self.binding['rooms']['current@chatroom']['remark']='webox.test'
        with self.backend.db() as db:db.execute('UPDATE meta SET value=? WHERE key=?',(json.dumps(self.binding),'binding'))
        self.settings['chats']={'webox.test':{'label':'旧测试群','natural_reply':True}}
        self.backend.write_json(self.backend.settings_path,self.settings)
        token=self.backend.target_id('current@chatroom')
        fields,_,values=self.backend.schema(self.settings,{},self.targets())
        self.assertTrue(values[f'chat.{token}.natural_reply'])
        self.assertTrue(all(f['section']=='会话 · 当前的群' for f in fields if f['key'].startswith('chat.')))
        self.backend.configure_chat({'target_id':token,'revision':self.backend.revision()})
        self.assertEqual(self.backend.settings()[0]['chats'],self.settings['chats'])

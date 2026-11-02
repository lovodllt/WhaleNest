import copy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import runpy
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import chat_bilibili as bili
from bilibili_client import BilibiliSocialClient
from console_server import ConsoleBackend,Handler

RESOURCE='bilibili:BV1234567890'
VIDEO={'resource_id':RESOURCE,'title':'测试视频','uploader':'测试UP','duration_ms':120000,
       'description':'简介不是字幕','subtitles':[{'start_ms':0,'end_ms':1000,'text':'开头'},
        {'start_ms':110000,'end_ms':120000,'text':'最后的字幕也必须读到'}]}
MENTION={'id':'100000000000000001','aid':'123456789012345678','rpid':'234567890123456789',
         'root':'345678901234567890','text':'原评论，不应被用作回复正文','sender_uid':'321',
         'sender_name':'测试用户','at_seconds':20}


class BilibiliTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='鲸栖 B站 ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/'config/resources.json').write_text('[]',encoding='utf-8')
        self.cfg=dict(bili.DEFAULTS,enabled=True,account_uid='900',share_recipient_uids=['123'],
                      activation='fixture',enabled_at_ms=10000)
        self.calls=[]
        self.client=SimpleNamespace(credential_status=lambda:{'read_ready':True,'write_ready':True},call=self.client_call)
        self.service=bili.Bilibili(self.root,self.client,self.content)
        self.service.write_config(self.cfg)

    def client_call(self, request):
        self.calls.append(copy.deepcopy(request))
        operation=request['operation']
        if operation=='mentions':return {'access':'available','account_uid':'900','cursor':{},'items':[MENTION]}
        if operation=='video_id':return {'access':'available','resource_id':RESOURCE}
        return {'access':'available','account_uid':'900','receipt_id':'987654321098765432'}

    def content(self, request):
        if request['operation']=='search':
            return {'access':'available','items':[dict(VIDEO,url='https://wrong.invalid/'),{'resource_id':'bad-id'}]}
        return {'access':'available','resource':copy.deepcopy(VIDEO)}

    def bridge(self):
        db=sqlite3.connect(':memory:')
        db.execute("CREATE TABLE inbox(id TEXT PRIMARY KEY,prompt TEXT,time INTEGER,status TEXT DEFAULT 'pending')")
        self.addCleanup(db.close)
        return db

    def row(self, table):
        with bili.database(self.root) as db:return dict(db.execute('SELECT * FROM '+table).fetchone())

    def test_search_is_bounded_metadata_only_and_has_real_canonical_urls(self):
        tool=bili.Tools(self.service,'fixture-room','event')
        result=tool('bilibili_search',{'keyword':' 猫咪 ','max_results':1,'page':2})
        self.assertEqual('search_metadata_only',result['evidence'])
        self.assertEqual(bili.video_url(RESOURCE),result['items'][0]['url'])
        self.assertNotIn('subtitles',result['items'][0])
        for args in ({'keyword':' '},{'keyword':'猫','page':11},{'keyword':'猫','page':True},{'keyword':'猫','max_results':9}):
            with self.assertRaises(ValueError):tool('bilibili_search',args)
        self.assertEqual(['这个挺有意思',bili.video_url(RESOURCE)],tool.reply_parts('这个挺有意思\n'+bili.video_url(RESOURCE)))
        self.assertIsNone(tool.reply_parts('https://www.bilibili.com/video/BV0987654321'))
        with bili.database(self.root) as db:self.assertEqual(0,db.execute('SELECT COUNT(*) FROM videos').fetchone()[0])

    def test_complete_subtitles_are_returned_without_playback_wait_and_only_one_summary_is_kept(self):
        tool=bili.Tools(self.service,'room-a','event')
        video=tool('bilibili_read',{'resource_id':RESOURCE})
        self.assertEqual(VIDEO['subtitles'],video['subtitles'])
        self.assertEqual('subtitle',video['evidence'])
        for text in ('第一份摘要','替换后的简短摘要'):
            tool('bilibili_remember',{'resource_id':RESOURCE,'summary':text,'feedback':'挺有趣'})
        tool.commit()
        with bili.database(self.root) as db:
            self.assertEqual(1,db.execute('SELECT COUNT(*) FROM videos').fetchone()[0])
            self.assertEqual('替换后的简短摘要',db.execute('SELECT summary FROM videos').fetchone()[0])
        self.assertEqual('替换后的简短摘要',tool('bilibili_read',{'resource_id':RESOURCE})['previous_summary'])
        other=bili.Tools(self.service,'room-b','another')
        self.assertNotIn('previous_summary',other('bilibili_read',{'resource_id':RESOURCE}))

    def test_missing_and_overlong_subtitles_do_not_become_read_or_shareable(self):
        for video in (dict(VIDEO,subtitles=[]),dict(VIDEO,subtitles=[{'text':'长'*100001}])):
            self.service.content=lambda _,v=video:{'access':'available','resource':v}
            tool=bili.Tools(self.service,'room','event')
            self.assertFalse(tool('bilibili_read',{'resource_id':RESOURCE})['readable'])
            with self.assertRaises(ValueError):
                tool('bilibili_share',{'resource_id':RESOURCE,'channel':'wechat','recipient_uid':'','text':'看看这个'})

    def test_mention_cutoff_exact_reply_and_provider_receipt(self):
        old=dict(MENTION,rpid='111',at_seconds=1)
        self.client.call=lambda request:({'access':'available','account_uid':'900','items':[old,MENTION],'cursor':{}}
                                        if request['operation']=='mentions' else self.client_call(request))
        self.service.poll(25000);self.service.poll(400000)
        with bili.database(self.root) as db:self.assertEqual(1,db.execute('SELECT COUNT(*) FROM mentions').fetchone()[0])
        received=[]
        class Chat:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def reply(self,session,prompt,**kwargs):
                received.append(json.loads(prompt))
                return json.dumps({'summary':'简单方法','feedback':'想试试','reply':'这个办法挺有意思'})
        self.service.review_mention(lambda _:Chat())
        self.assertEqual(VIDEO['subtitles'],received[0]['视频']['subtitles'])
        self.assertEqual('reply_queued',self.row('mentions')['status'])
        self.service.dispatch(self.bridge(),None,500000)
        sent=self.calls[-1]
        self.assertEqual({k:MENTION[k] for k in ('aid','root','rpid')},{k:sent[k] for k in ('aid','root','rpid')})
        self.assertEqual('这个办法挺有意思',sent['text'])
        self.assertEqual('sent_provider',self.row('actions')['status'])
        self.assertEqual('987654321098765432',json.loads(self.row('actions')['receipt'])['receipt_id'])
        self.service.dispatch(self.bridge(),None,600000)
        self.assertEqual(1,sum(x['operation']=='reply' for x in self.calls))

    def test_unreadable_mention_never_calls_model_or_queues_reply(self):
        self.service.poll(25000)
        self.service.content=lambda _:{'access':'available','resource':dict(VIDEO,subtitles=[])}
        model=Mock()
        self.service.review_mention(model)
        model.assert_not_called();self.assertEqual('unreadable',self.row('mentions')['status'])
        with bili.database(self.root) as db:self.assertEqual(0,db.execute('SELECT COUNT(*) FROM actions').fetchone()[0])

    def test_prepared_shares_deduplicate_and_recheck_recipient_account_and_switch(self):
        tool=bili.Tools(self.service,'room','event')
        tool('bilibili_read',{'resource_id':RESOURCE})
        args={'resource_id':RESOURCE,'channel':'bilibili_dm','recipient_uid':'123','text':'这个好有趣'}
        tool('bilibili_share',args)
        with bili.database(self.root) as db:self.assertEqual(0,db.execute('SELECT COUNT(*) FROM actions').fetchone()[0])
        tool.commit();tool.commit()
        with bili.database(self.root) as db:self.assertEqual(1,db.execute('SELECT COUNT(*) FROM actions').fetchone()[0])
        self.service.write_config(dict(self.cfg,share_recipient_uids=[]))
        self.service.dispatch(self.bridge(),None,500000)
        self.assertEqual('cancelled',self.row('actions')['status']);self.assertEqual([],self.calls)
        self.service.write_config(dict(self.cfg,account_uid='901'))
        with self.assertRaises(ValueError):tool.commit()
        self.service.write_config(dict(self.cfg,enabled=False))
        with self.assertRaises(ValueError):tool('bilibili_search',{'keyword':'猫'})
        bili.Tools(self.service,'room','no-action').commit()

    def test_unknown_send_and_interrupted_send_are_never_blindly_retried(self):
        self.service.enqueue('dm','direct_share',RESOURCE,'有趣\n'+bili.video_url(RESOURCE),'123')
        self.client.call=lambda _:{'access':'uncertain'}
        self.service.dispatch(self.bridge(),None,500000)
        self.assertEqual('uncertain',self.row('actions')['status'])
        self.client.call=Mock()
        self.service.recover();self.service.dispatch(self.bridge(),None,600000)
        self.client.call.assert_not_called()
        with bili.database(self.root) as db:db.execute("UPDATE actions SET status='sending'")
        self.service.recover();self.assertEqual('uncertain',self.row('actions')['status'])

    def test_wechat_uses_existing_queue_bubbles_receipt_and_disable_cancels_pending(self):
        bridge=self.bridge();url=bili.video_url(RESOURCE)
        self.service.enqueue('wx','wechat_share',RESOURCE,'这个挺有趣\n想到你啦\n'+url,'fixture-room')
        self.service.dispatch(bridge,None,500000)
        event,raw=bridge.execute('SELECT id,prompt FROM inbox').fetchone();current=json.loads(raw)
        api=Mock();api.call.return_value={'ret':0,'client_msg_id':'fixture-receipt'}
        with patch.object(bili,'Bilibili',return_value=self.service),patch('chat_rules.load_settings',return_value={'reply_paused':False}):
            bili.deliver_wechat(bridge,api,{'rooms':{'fixture-room':{}}},event,current,lambda *_:None,self.root)
            parts=api.call.call_args.args[1]['msgs']
            self.assertEqual(['这个挺有趣','想到你啦',url],[p['text']['content'] for p in parts])
            self.assertEqual('sent_wechat',self.row('actions')['status'])
            bili.deliver_wechat(bridge,api,{'rooms':{}},event,current,lambda *_:None,self.root)
            self.assertEqual(1,api.call.call_count)
        self.service.enqueue('wx2','wechat_share',RESOURCE,'看看\n'+url,'fixture-room')
        self.service.dispatch(bridge,None,600000)
        row=bridge.execute("SELECT id,prompt FROM inbox WHERE status='pending'").fetchone()
        self.service.save({'revision':self.service.revision(),'enabled':False,'share_recipient_uids':['123']})
        with patch.object(bili,'Bilibili',return_value=self.service):
            bili.deliver_wechat(bridge,api,{'rooms':{}},row[0],json.loads(row[1]),lambda *_:None,self.root)
        self.assertEqual(1,api.call.call_count)

    def test_protocol_preserves_big_ids_checks_account_and_requires_actual_receipt(self):
        credential=self.root/'data/bilibili/provider/node_modules/dsh-bilibili/.sessdata.json'
        credential.parent.mkdir(parents=True);credential.write_text(json.dumps({'sessdata':'fixture','bili_jct':'fixture-csrf'}))
        posts=[]
        def transport(host,path,params,post=False):
            if path.endswith('/nav'):return {'code':0,'data':{'isLogin':True,'mid':900}}
            posts.append((path,params,post));return {'code':0,'data':{'rpid_str':'999999999999999999'}}
        client=BilibiliSocialClient(self.root,transport)
        result=client.call({'operation':'reply','account_uid':'900',**MENTION,'text':'人物真实回复'})
        self.assertEqual('999999999999999999',result['receipt_id'])
        self.assertEqual((MENTION['aid'],MENTION['root'],MENTION['rpid']),tuple(posts[0][1][k] for k in ('oid','root','parent')))
        result=client.call({'operation':'direct_share','account_uid':'901','recipient_uid':'123','text':'内容'})
        self.assertEqual('AccountChanged',result['error_type']);self.assertEqual(1,len(posts))
        client.transport=lambda host,path,params,**kwargs:transport(host,path,params,**kwargs) if path.endswith('/nav') else {'code':0,'data':{}}
        self.assertEqual('uncertain',client.call({'operation':'direct_share','account_uid':'900','recipient_uid':'123','text':'内容'})['access'])
        def missing_root(host,path,params,**kwargs):
            if path.endswith('/reply/info'):
                return {'code':0,'data':{'reply':{'rpid_str':MENTION['rpid'],'oid':MENTION['aid'],'root_str':MENTION['root']}}}
            return transport(host,path,params,**kwargs)
        client.transport=missing_root
        result=client.call({'operation':'reply','account_uid':'900',**dict(MENTION,root=''),'text':'精确接原评论'})
        self.assertEqual('available',result['access'])
        self.assertEqual(MENTION['root'],posts[-1][1]['root'])

    def test_optional_provider_reinstall_preserves_its_own_login(self):
        source=runpy.run_path(str(ROOT/'scripts/manage.py'))['bilibili_plugins']
        shutil.copy(ROOT/'config/bilibili-provider.package.json',self.root/'config/bilibili-provider.package.json')
        (self.root/'config/npm-locks').mkdir()
        shutil.copy(ROOT/'config/npm-locks/bilibili.json',self.root/'config/npm-locks/bilibili.json')
        folder=self.root/'data/bilibili/provider/node_modules/dsh-bilibili'
        folder.mkdir(parents=True);credential=folder/'.sessdata.json'
        credential.write_text('{"sessdata":"fixture-only"}',encoding='utf-8')
        def install(_):
            shutil.rmtree(folder.parent);folder.mkdir(parents=True)
        with patch.dict(source.__globals__,ROOT=self.root,DATA=self.root/'data',initialize=lambda:None,
                        environment=lambda:{},shell=install):source()
        self.assertEqual({'sessdata':'fixture-only'},json.loads(credential.read_text(encoding='utf-8')))
        self.assertFalse((self.root/'data/bilibili/provider-credentials.backup').exists())

    def test_console_config_is_independent_versioned_and_csrf_protected(self):
        backend=ConsoleBackend(self.root);backend.bilibili=self.service
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.backend=backend;server.remote_only=False
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,headers=None):
            req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {})
            return json.load(urllib.request.urlopen(req,timeout=3))
        state=request('/api/bilibili/state')
        self.assertNotIn('sessdata',json.dumps(state))
        body={'revision':state['revision'],'enabled':True,'share_recipient_uids':['456']}
        with self.assertRaises(urllib.error.HTTPError) as error:request('/api/bilibili/config',body)
        self.assertEqual(403,error.exception.code)
        headers={'X-CSRF-Token':backend.csrf_token,'Content-Type':'application/json','Origin':url}
        result=request('/api/bilibili/config',body,headers)
        self.assertEqual(['456'],result['config']['share_recipient_uids'])
        with self.assertRaises(urllib.error.HTTPError):request('/api/bilibili/config',body,headers)
        self.assertEqual('900',bili.settings(self.root)['account_uid'])
        self.assertFalse((self.root/'config/chat.json').exists())

    @unittest.skipUnless(shutil.which('node'),'Node is required for the DSH tool bridge')
    def test_dsh_tools_are_registered_and_bound_to_current_agent(self):
        module=self.root/'tools.mjs';module.write_text('export const defineTool=value=>value;',encoding='utf-8')
        script=r'''
import assert from 'node:assert/strict';
process.env.DAFEIYU_TOOLS_MODULE=process.argv[2];
process.env.DAFEIYU_ACTION_URL='http://127.0.0.1:12345/action';
process.env.DAFEIYU_ACTION_TOKEN='fixture-token';
const {apply}=await import('./app/bilibili_tools.mjs');
const tools=[];apply({tools:{register(tool){tools.push(tool)}}});
assert.deepEqual(tools.map(t=>t.name),['bilibili_search','bilibili_read','bilibili_remember','bilibili_share']);
globalThis.fetch=async(url,options)=>{
 assert.equal(url,process.env.DAFEIYU_ACTION_URL);
 const body=JSON.parse(options.body);assert.equal(body.action,'bilibili_search');assert.equal(body.session,'fixture-session');
 return {ok:true,json:async()=>({ok:true,result:{evidence:'search_metadata_only'}})};
};
const result=await tools[0].execute({keyword:'猫'}, {agent:{id:'fixture-session'},signal:new AbortController().signal});
assert.equal(result.evidence,'search_metadata_only');
await assert.rejects(()=>tools[0].execute({keyword:'猫'},{signal:new AbortController().signal}));
'''
        result=subprocess.run(['node','--input-type=module','-',str(module)],input=script,text=True,
            capture_output=True,encoding='utf-8',cwd=ROOT,timeout=10)
        self.assertEqual(0,result.returncode,result.stderr)


if __name__=='__main__':unittest.main()

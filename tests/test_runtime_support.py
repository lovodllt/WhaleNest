import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import runtime_support as runtime


class RuntimeTests(unittest.TestCase):
    def test_lock_and_process_identity_do_not_confuse_a_reused_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            lock=Path(directory)/'service.lock'
            with runtime.file_lock(lock):
                self.assertTrue(runtime.lock_held(lock))
            self.assertFalse(runtime.lock_held(lock))
        record=runtime.process_record(os.getpid(),__file__)
        record['created']+=10
        self.assertIsNone(runtime.owned_process(record))
        self.assertIsNone(runtime.owned_process(record['pid']))

    def test_windows_lock_uses_byte_zero_and_reports_contention(self):
        windows=types.SimpleNamespace(LK_NBLCK=2,LK_UNLCK=0,locking=Mock())
        with tempfile.TemporaryFile('a+b') as handle,patch.object(runtime,'WINDOWS',True), \
                patch.dict(sys.modules,msvcrt=windows):
            handle.write(b'existing');handle.flush()
            runtime.acquire_lock(handle,False)
            self.assertEqual(handle.tell(),0)
            runtime.release_lock(handle)
            self.assertEqual(windows.locking.call_args_list[-1].args,(handle.fileno(),0,1))
            windows.locking.side_effect=PermissionError(errno.EACCES,'busy')
            with self.assertRaises(BlockingIOError):runtime.acquire_lock(handle,False)
        with patch.object(runtime,'WINDOWS',True), \
                patch.object(subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True), \
                patch.object(subprocess,'DETACHED_PROCESS',8,create=True):
            self.assertEqual(runtime.detached_options(),{'creationflags':520})

    def test_npm_cmd_resolves_to_javascript_in_a_unicode_path(self):
        with tempfile.TemporaryDirectory(prefix='中文 路径 ') as directory:
            base=Path(directory);shim=base/'dsh.cmd';shim.touch()
            entry=base/'node_modules/@deepseek-ai/dsh/lib/bin.js'
            entry.parent.mkdir(parents=True);entry.write_text('// entry',encoding='utf-8')
            self.assertEqual(runtime.node_entry(str(shim),'node_modules/@deepseek-ai/dsh/lib/bin.js'),str(entry.resolve()))

    def test_isolated_supervisor_ignores_stale_pid_and_stops_gracefully(self):
        with tempfile.TemporaryDirectory(prefix='鲸栖 启停 ') as directory:
            root=Path(directory)
            for folder in ('scripts','app','config'): (root/folder).mkdir()
            shutil.copy2(ROOT/'scripts/manage.py',root/'scripts/manage.py')
            shutil.copy2(ROOT/'scripts/service_status.py',root/'scripts/service_status.py')
            shutil.copy2(ROOT/'app/runtime_support.py',root/'app/runtime_support.py')
            for name in ('chat.example.json','voice.example.json','voice-catalog.json'):
                shutil.copy2(ROOT/'config'/name,root/'config'/name)
            (root/'app/group_bridge.py').write_text(
                "import sqlite3\nfrom pathlib import Path\ndef connect_db():\n"
                " p=Path(__file__).resolve().parents[1]/'data/chat/bridge.sqlite3'\n"
                " db=sqlite3.connect(p)\n db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT,value TEXT)')\n return db\n",encoding='utf-8')
            (root/'app/console_server.py').write_text(
                "from pathlib import Path\nimport time\n"
                "run=Path(__file__).resolve().parents[1]/'data/run'\n"
                "(run/'ready').touch()\nwhile not (run/'stop.flag').exists():time.sleep(.05)\n"
                "(run/'graceful').touch()\n",encoding='utf-8')
            command=[sys.executable,'-X','utf8',str(root/'scripts/manage.py')]
            unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
            def clean_unrelated():
                if unrelated.poll() is None:unrelated.terminate()
                unrelated.wait(timeout=5)
            self.addCleanup(clean_unrelated)
            run=root/'data/run';run.mkdir(parents=True)
            (run/'supervisor.pid').write_text(str(unrelated.pid),encoding='utf-8')
            try:
                result=subprocess.run([*command,'start','--console-only'],capture_output=True,text=True,encoding='utf-8',timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIsNone(unrelated.poll())
                deadline=time.monotonic()+5
                while not (run/'ready').is_file() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue((run/'ready').is_file())
                receipt=json.loads((run/'supervisor.json').read_text(encoding='utf-8'))
                again=subprocess.run([*command,'start','--console-only'],capture_output=True,text=True,encoding='utf-8',timeout=15)
                self.assertIn('已运行',again.stdout)
                self.assertEqual(json.loads((run/'supervisor.json').read_text(encoding='utf-8'))['pid'],receipt['pid'])
                status=subprocess.run([sys.executable,str(root/'scripts/service_status.py'),'console'],capture_output=True,text=True,timeout=5)
                self.assertEqual(status.stdout.strip(),'active')
                self.assertIsNone(unrelated.poll())
            finally:
                stopped=subprocess.run([*command,'stop'],capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(stopped.returncode,0,stopped.stderr)
            self.assertTrue((run/'graceful').is_file())
            self.assertFalse(runtime.lock_held(run/'supervisor.lock'))
            self.assertIsNone(unrelated.poll())

    def test_windows_text_send_uses_http_without_host_docker(self):
        import group_bridge
        api=group_bridge.Webox();api.host_helpers=False
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        response.read.return_value=b'{"ret":0}'
        api.http=Mock();api.http.open.return_value=response
        with patch.object(group_bridge,'load_settings',return_value={'fast_ui_send':True}), \
                patch.object(api.token_path.__class__,'read_text',return_value='fixture-token'), \
                patch.object(group_bridge.subprocess,'run') as docker:
            self.assertEqual(api.call('/ilink/bot/sendmessage',{'msgs':[{'roomid':'fixture','msgtype':'text','text':{'content':'你好'}}]}),{'ret':0})
            docker.assert_not_called()

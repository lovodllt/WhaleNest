import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from resource_center import Resources
from console_server import ConsoleBackend, Handler

class PackageTests(unittest.TestCase):
    def test_resources_reject_changed_files_and_escaping_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config/resources.json').write_text('[]')
            resource=Resources(root);path=root/'file';path.write_bytes(b'good')
            file={'size':4,'sha256':hashlib.sha256(b'good').hexdigest()}
            self.assertTrue(resource.verify(path,file));path.write_bytes(b'evil');self.assertFalse(resource.verify(path,file))
            with self.assertRaises(ValueError):resource._target('../other-account')

    def test_character_import_is_separate_and_preserves_setting_priority(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config/resources.json').write_text('[]')
            output=io.BytesIO();Image.new('RGB',(2,2),'blue').save(output,format='PNG')
            resource=Resources(root);body={'name':'示例角色','filename':'设定集.png','data':base64.b64encode(output.getvalue()).decode()}
            resource.import_character(body)
            self.assertEqual(len(list((root/'resources/characters/示例角色/images').glob('设定集-*.png'))),1)
            with self.assertRaises(ValueError):resource.import_character({**body,'name':'../别人的角色'})

    def test_missing_csrf_and_cross_origin_are_rejected(self):
        backend=SimpleNamespace(csrf_token='known-token',access_config=lambda:{})
        handler=Handler.__new__(Handler);handler.server=SimpleNamespace(server_port=12345,remote_only=False,backend=backend)
        handler.path='/api/resources/download';result=[];handler.json_response=lambda status,body:result.append(status)
        for headers in [{'Host':'127.0.0.1:12345'},{'Host':'127.0.0.1:12345','Origin':'https://outside.example','X-CSRF-Token':'known-token'}]:
            handler.headers=headers;handler.do_POST()
        self.assertEqual(result,[403,403])

    def test_clean_defaults_and_pinned_download_manifest(self):
        settings=json.loads((ROOT/'config/chat.example.json').read_text())
        self.assertEqual(settings['chats'],{});self.assertTrue(settings['reply_paused'])
        self.assertFalse(settings['memory']['enabled']);self.assertEqual(settings['singing']['songs'],{})
        for resource in json.loads((ROOT/'config/resources.json').read_text()):
            self.assertEqual(len(resource['revision']),40)
            for file in resource['files']:
                self.assertIn(resource['revision'],file['url']);self.assertGreaterEqual(file['size'],0)
                self.assertTrue(file.get('sha256') or file.get('git_blob_sha1'))

    def test_public_console_omits_dormant_capabilities(self):
        settings=json.loads((ROOT/'config/chat.example.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();(root/'config/resources.json').write_text('[]')
            backend=ConsoleBackend(root);backend.db_path.parent.mkdir(parents=True)
            with backend.db() as db:db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT)')
            fields,paths,_=backend.schema(settings,{}, {})
            self.assertFalse(any(key.startswith('moments_handoff.') for key in paths))
            status={'dsh':{'available':False,'plugins':[]},'services':[]}
            plugins=backend.plugin_state(settings,{},status,fields)
            self.assertTrue({'memory','image','tts','singing'} <= {p['id'] for p in plugins})
            self.assertFalse({'moments','bili'} & {p['id'] for p in plugins})

if __name__=='__main__':unittest.main()

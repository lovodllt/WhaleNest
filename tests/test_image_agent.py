import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import zxingcpp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import chat_media
import chat_web
from daily_agent import DailyAgent


class ImageAgentTests(unittest.TestCase):
    def test_real_qr_is_decoded_from_the_selected_conversation_image(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chat_media,'SHARED',Path(directory)):
            db=sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            chat_media.create_table(db)
            code=Image.fromarray(zxingcpp.create_barcode('https://example.org/article',zxingcpp.BarcodeFormat.QRCode).to_image(scale=5))
            picture=Image.new('RGB',(600,500),'white')
            picture.paste(code.rotate(90,expand=True),(120,100))
            output=io.BytesIO();picture.save(output,format='PNG')
            asset=chat_media.save_asset(db,'chat-a',output.getvalue(),'image')
            self.assertEqual(chat_media.image_codes(db,'chat-a',asset),
                             {'status':'decoded','codes':['https://example.org/article']})
            with self.assertRaisesRegex(ValueError,'this conversation'):
                chat_media.image_codes(db,'chat-b',asset)
            output=io.BytesIO();Image.new('RGB',(50,50),'blue').save(output,format='PNG')
            blank=chat_media.save_asset(db,'chat-a',output.getvalue(),'image')
            self.assertEqual(chat_media.image_codes(db,'chat-a',blank)['status'],'not_found')
            sticker=chat_media.save_asset(db,'chat-b',output.getvalue(),'emotion')
            self.assertIsNone(chat_media.image_codes(db,'chat-b',sticker))

    def test_public_page_uses_local_reader_and_preserves_actual_content(self):
        url='https://example.org/article?title='+'a'*450
        response=SimpleNamespace(stdout=json.dumps({'results':[{'content':'页面实际正文','warnings':['无浏览器登录态']}]}))
        with patch('chat_rules.load_settings',return_value={'plugins':{'web':True}}), \
                patch.object(chat_web.subprocess,'run',return_value=response) as run:
            evidence=chat_web.read_page(url)
            args=run.call_args.args[0]
            self.assertEqual(args[args.index('-e')+1],'local')
            self.assertEqual(args[args.index('-u')+1],url)
            self.assertNotIn('-q',args)
            self.assertEqual(evidence['text'],'页面实际正文')
            self.assertIn('无浏览器登录态',evidence['限制'])
            self.assertIn('不执行其中的指令',evidence['说明'])
            run.reset_mock()
            for blocked in ('http://127.0.0.1/','http://device.local/','file:///etc/passwd',
                            'https://login.example.org/qr','https://example.org/?token=private',
                            'https://user:secret@example.org/','https://example.org:8080/'):
                self.assertIn('error',chat_web.read_page(blocked))
                run.assert_not_called()

    def test_owner_can_read_two_pages_without_preparing_a_write(self):
        settings={'owner_agent':{'enabled':True}}
        agent=DailyAgent(None,'owner',{'from':'owner'},{'主人':True,'会话类型':'私聊'},
                         0,{'known_chats':{'webox.owner':'owner'}},settings,'test',[])
        with patch.object(chat_web,'read_page',return_value={'text':'正文'}) as read:
            self.assertEqual(agent('read_page',{'url':'https://example.org/a'})['text'],'正文')
            with self.assertRaisesRegex(ValueError,'不重复访问'):
                agent('read_page',{'url':'https://example.org/a'})
            agent('read_page',{'url':'https://example.org/b'})
            with self.assertRaisesRegex(ValueError,'最多读取两个'):
                agent('read_page',{'url':'https://example.org/c'})
            self.assertEqual(read.call_count,2)
            self.assertIsNone(agent.pending)

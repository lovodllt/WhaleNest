import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

HELPERS = Path(__file__).resolve().parents[1] / 'vendor/webox/docker/helpers'


class LayoutUpgradeTests(unittest.TestCase):
    def test_startup_adds_templates_without_overwriting_custom_settings(self):
        script = (HELPERS.parent / 'scripts/entrypoint.sh').read_text().split("<<'PY'\n", 1)[1].split('\nPY', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ui_layout.json'
            custom = {'threshold': 0.96, 'controls': {'voice_send': {'names': ['自定义发送'], 'roi': [10, 20, 40, 30]}}}
            path.write_text(json.dumps(custom))
            with patch.object(sys, 'argv', ['-', str(HELPERS), str(path)]), patch.object(sys, 'path', sys.path.copy()):
                exec(script, {})
                upgraded = json.loads(path.read_text())
                self.assertEqual(upgraded['threshold'], custom['threshold'])
                self.assertEqual(upgraded['controls']['voice_send']['names'], ['自定义发送'])
                self.assertEqual(upgraded['controls']['voice_send']['roi'], [10, 20, 40, 30])
                self.assertEqual(upgraded['controls']['voice_send']['template'], 'voice_send.png')
                self.assertIn('bubble_incoming', upgraded['controls'])
                exec(script, {})
                self.assertEqual(json.loads(path.read_text()), upgraded)


@unittest.skipUnless(cv2, 'OpenCV is installed in the WeChat container')
class UIMatchingTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HELPERS))
        self.addCleanup(sys.path.remove, str(HELPERS))
        import ui_locator
        import ui_template
        self.locator, self.matcher = ui_locator, ui_template
        self.layout = HELPERS / 'ui_layout.json'
        fake = types.SimpleNamespace(dbus=types.SimpleNamespace(DBusException=RuntimeError),
                                     find_controls=lambda *a, **k: [])
        self.fake = fake
        self.enterContext(patch.dict(sys.modules, ui_accessible=fake))
        self.enterContext(patch.object(ui_locator, 'window_geometry', return_value=(100, 80, 600, 400)))
        self.enterContext(patch.object(ui_locator.subprocess, 'check_output', return_value='test window'))

    def image(self, name):
        return cv2.imread(str(HELPERS / 'ui_templates' / (name+'.png')), cv2.IMREAD_GRAYSCALE)

    def screenshot(self, image):
        self.enterContext(patch.object(self.locator, 'capture_window', return_value=cv2.imencode('.png', image)[1].tobytes()))

    def test_repeated_icon_is_rejected(self):
        sample = self.image('voice_send')
        canvas = np.full((400, 600), 250, np.uint8)
        h, w = sample.shape
        canvas[300:300+h, 400:400+w] = sample
        canvas[300:300+h, 500:500+w] = sample
        self.assertEqual(self.matcher.locate(canvas, sample)['reason'], 'ambiguous_matches')

    def test_message_matching_stays_inside_the_requested_row(self):
        sample = self.image('bubble_incoming')
        canvas = np.full((400, 600), 250, np.uint8)
        h, w = sample.shape
        canvas[100:100+h, 60:60+w] = sample
        canvas[240:240+h, 60:60+w] = sample
        self.screenshot(canvas)
        x, y = self.locator.message_point(7, [100, 160, 600, 80], layout_path=self.layout)
        self.assertTrue(160 <= x <= 160+w)
        self.assertTrue(180 <= y <= 180+h)

    def test_template_follows_a_moved_button(self):
        sample = self.image('voice_send')
        canvas = np.full((400, 600), 250, np.uint8)
        h, w = sample.shape
        canvas[330:330+h, 430:430+w] = sample
        self.screenshot(canvas)
        result = self.locator.find_control(7, self.layout, 'voice_send')
        self.assertTrue(result['matched'], result)
        self.assertEqual(result['method'], 'template')
        self.assertEqual(result['bbox'][:2], [430, 330])

    def test_accessible_control_keeps_priority(self):
        self.fake.find_controls = lambda *a, **k: [{'Visible': True, 'Role': 'push button',
                                                    'Extents': [530, 410, 28, 28]}]
        with patch.object(self.locator, 'capture_window') as screenshot:
            result = self.locator.find_control(7, self.layout, 'voice_send')
        self.assertEqual(result['method'], 'accessible')
        screenshot.assert_not_called()

    def test_custom_pixel_roi_takes_priority_over_default_region(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ui_layout.json'
            layout = json.loads(self.layout.read_text())
            control = layout['controls']['voice_send']
            control['roi'] = [10, 20, 40, 30]
            path.write_text(json.dumps(layout))
            self.screenshot(np.full((400, 600), 250, np.uint8))
            with patch.object(cv2, 'imread', return_value=self.image('voice_send')), patch.object(self.matcher, 'locate', return_value={'matched': False}) as match:
                self.locator.find_control(7, path, 'voice_send')
            self.assertEqual(match.call_args.args[2], control['roi'])

    def test_avatar_cache_separates_accounts_and_refreshes_changed_photos(self):
        import ui_avatar
        with tempfile.TemporaryDirectory() as folder, patch.object(ui_avatar, 'CACHE', Path(folder)):
            url = {'one': 'https://wx.qlogo.cn/one/132', 'two': 'https://wx.qlogo.cn/two/132'}
            def profile(command, **kwargs):
                username = json.loads(kwargs['input'])['username']
                return types.SimpleNamespace(stdout=json.dumps({'username': username, 'account': 'bot', 'avatar_url': url[username]}))
            picture = cv2.imencode('.png', np.full((40, 40, 3), 120, np.uint8))[1].tobytes()
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = picture
            opener = types.SimpleNamespace(open=unittest.mock.Mock(return_value=response))
            with patch.object(ui_avatar.subprocess, 'run', side_effect=profile), patch.object(ui_avatar.urllib.request, 'build_opener', return_value=opener):
                first = ui_avatar.contact_avatar('one')
                self.assertEqual(ui_avatar.contact_avatar('one'), first)
                second = ui_avatar.contact_avatar('two')
                self.assertNotEqual(first, second)
                self.assertEqual(opener.open.call_count, 2)
                url['one'] = 'https://wx.qlogo.cn/one-new/132'
                ui_avatar.contact_avatar('one')
                self.assertEqual(opener.open.call_count, 3)


if __name__ == '__main__':
    unittest.main()

import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, mock_open, patch


@unittest.skipIf(os.name=='nt','Linux 微信界面助手在容器内执行')
class WindowRestoreTests(unittest.TestCase):
    def test_voice_conversion_restores_original_window_on_success_and_failure(self):
        helpers = Path(__file__).resolve().parents[1] / 'vendor/webox/docker/helpers'
        fake = types.SimpleNamespace(**{key: Mock() for key in ('connect', 'find_controls', 'header_matches', 'ACC', 'COMP', 'PROPS', 'VISIBLE', 'dbus')})
        with patch.dict(sys.modules, ui_accessible=fake, ui_locator=types.SimpleNamespace(message_point=Mock(return_value=(20, 30)))):
            spec = importlib.util.spec_from_file_location('restore_voice_test', helpers / 'ui_voice_text.py')
            voice = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(voice)
        request = {'remark': 'test', 'offset': 0, 'seconds': 2, 'outgoing': False}
        for success in (True, False):
            with self.subTest(success=success), patch.object(sys, 'stdin', io.StringIO(json.dumps(request))), \
                    patch('builtins.open', mock_open()), patch.object(voice.fcntl, 'flock'), \
                    patch.object(voice, 'open_chat', return_value='test'), patch.object(voice, 'voices', return_value=[(2, [0, 0, 100, 40])]), \
                    patch.object(voice, 'window', return_value='99'), patch.object(voice, 'command'), \
                    patch.object(voice.time, 'sleep'), patch.object(voice.subprocess, 'run', return_value=types.SimpleNamespace(stdout='42\n')) as run:
                voice.find_controls = Mock(return_value=[{'Visible': True, 'Role': 'menu item', 'Extents': [0, 0, 20, 20]}] if success else [])
                if success:
                    with patch.object(sys, 'stdout', io.StringIO()):
                        voice.main()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'menu is unavailable'):
                        voice.main()
                self.assertEqual(run.call_args_list[-1].args[0], ['xdotool', 'windowactivate', '42'])

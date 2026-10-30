"""Native launcher tests use explicit fixtures; no model or gateway is started."""
import argparse
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAME = '_cli_tabs_native_fixture'
spec = importlib.util.spec_from_file_location(NAME, ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[NAME] = plugin
spec.loader.exec_module(plugin)
native = importlib.import_module(NAME + '.native')
controller = importlib.import_module(NAME + '.tabs')
CAPABILITIES = {'schema': 1, 'ui': 'hermes-tui', 'features': {name: 1 for name in native.FEATURES}}


def reply(text, code=0):
    return types.SimpleNamespace(stdout=text, stderr='', returncode=code)


class NativeTests(unittest.TestCase):
    def test_environment_retains_only_this_pane_identity_and_drops_credentials_and_prompts(self):
        source = {'PATH': '/bin', 'HOME': '/home/test', 'OPENAI_API_KEY': 'fixture-secret',
                  'HERMES_TUI_QUERY': 'never submit', 'HERMES_TUI_RESUME': 'wrong-session',
                  'HERMES_YOLO_MODE': '1', 'HERMES_ACCEPT_HOOKS': '1',
                  'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w1:p2', 'HERDR_BIN_PATH': '/bin/herdr',
                  'HERDR_SOCKET_PATH': '/owned/socket', 'TMUX': 'owned-terminal', 'TMUX_PANE': '%2'}
        result = native.native_environment('/profiles/test', '/project', source)
        for key in native.HERDR_IDENTITY:
            self.assertEqual(result[key], source[key])
        for key in ('OPENAI_API_KEY', 'HERMES_TUI_QUERY', 'HERMES_TUI_RESUME', 'HERMES_YOLO_MODE', 'HERMES_ACCEPT_HOOKS'):
            self.assertNotIn(key, result)
        self.assertEqual(result['HERMES_HOME'], '/profiles/test')
        self.assertEqual(result['HERMES_CWD'], '/project')
        self.assertEqual(result['TMUX_PANE'], '%2')

    def test_incomplete_or_foreign_herdr_identity_is_not_synthesized(self):
        for source in ({'HERDR_ENV': '1'}, {'HERDR_ENV': '0', 'HERDR_PANE_ID': 'other:pane'}):
            result = native.native_environment('/h', '/p', source)
            self.assertFalse(any(key in result for key in native.HERDR_IDENTITY))

    def test_capability_probe_uses_only_advertised_read_only_cli_flags(self):
        env = {'PATH': '/bin'}
        with patch.object(native.subprocess, 'run', side_effect=[reply('Usage: hermes --tui-capabilities'), reply(json.dumps(CAPABILITIES))]) as run:
            self.assertEqual(native.native_capabilities('/bin/hermes', env), CAPABILITIES)
        self.assertEqual([call.args[0] for call in run.call_args_list], [['/bin/hermes', '--help'], ['/bin/hermes', '--tui-capabilities']])
        self.assertTrue(all(call.kwargs['stdin'] == subprocess.DEVNULL for call in run.call_args_list))
        self.assertTrue(all(call.kwargs['env'] is env for call in run.call_args_list))

    def test_older_cli_is_not_given_an_unknown_chat_flag(self):
        with patch.object(native.subprocess, 'run', return_value=reply('Usage: hermes --tui')) as run:
            self.assertIsNone(native.native_capabilities('/bin/hermes', {}))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['/bin/hermes', '--help'])

    def test_missing_or_invalid_capabilities_fall_back_honestly(self):
        variants = [
            'not json', '[]', json.dumps({'schema': True, 'ui': 'hermes-tui', 'features': CAPABILITIES['features']}), json.dumps({'schema': 2, 'ui': 'hermes-tui', 'features': CAPABILITIES['features']}),
            json.dumps({'schema': 1, 'ui': 'other', 'features': CAPABILITIES['features']}),
            json.dumps({'schema': 1, 'ui': 'hermes-tui', 'features': {'session_tabs': True}}),
            json.dumps({'schema': 1, 'ui': 'hermes-tui', 'features': {'session_tabs': 1}}),
        ]
        for value in variants:
            with self.subTest(value=value), patch.object(native.subprocess, 'run', side_effect=[reply('--tui-capabilities'), reply(value)]):
                self.assertIsNone(native.native_capabilities('/hermes', {}))

    def test_failed_or_timed_out_probe_never_starts_a_client(self):
        for error in (OSError('missing'), subprocess.TimeoutExpired('hermes', 5)):
            with patch.object(native.subprocess, 'run', side_effect=error), patch.object(native.subprocess, 'call') as start:
                self.assertIsNone(native.native_capabilities('/hermes', {}))
                start.assert_not_called()

    def test_auto_uses_native_only_for_a_compatible_tui(self):
        self.assertEqual(native.select_backend('auto', 'tui', CAPABILITIES), 'native')
        self.assertEqual(native.select_backend('auto', 'tui', None), 'tmux')
        self.assertEqual(native.select_backend('auto', 'classic', CAPABILITIES), 'tmux')
        self.assertEqual(native.select_backend('tmux', 'tui', CAPABILITIES), 'tmux')
        with self.assertRaisesRegex(ValueError, 'does not advertise'):
            native.select_backend('native', 'tui', None)
        with self.assertRaisesRegex(ValueError, 'requires --interface tui'):
            native.select_backend('native', 'classic', CAPABILITIES)

    def test_launch_preserves_the_literal_resume_argument_without_a_shell(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            value = 'chat; touch ' + str(root / 'must-not-exist')
            client = native.NativeTabs(root / 'home', root, hermes='/bin/hermes', environ={})
            self.assertEqual(client.argv(value), ['/bin/hermes', '--tui', '--in', str(root.resolve()), '--resume=' + value])
            self.assertFalse((root / 'must-not-exist').exists())

    def test_actual_native_child_needs_no_tmux_and_receives_the_selected_profile(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            record = root / 'invocation.json'
            executable = root / 'fixture-hermes'
            executable.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                                  + 'open(' + repr(str(record)) + ',"w").write(json.dumps({"argv":sys.argv[1:],"home":os.environ["HERMES_HOME"],"cwd":os.getcwd(),"has_query":"HERMES_TUI_QUERY" in os.environ}))\n')
            executable.chmod(0o700)
            client = native.NativeTabs(root / 'home', root, hermes=str(executable), environ={'HERMES_TUI_QUERY': 'never send'})
            self.assertEqual(client.start('literal title'), 0)
            result = json.loads(record.read_text())
            self.assertEqual(result['argv'], ['--tui', '--in', str(root.resolve()), '--resume=literal title'])
            self.assertEqual(result['home'], str((root / 'home').resolve()))
            self.assertEqual(result['cwd'], str(root.resolve()))
            self.assertFalse(result['has_query'])

    def test_native_controls_do_not_claim_to_mutate_a_private_store(self):
        for action, command in (('new', '/new'), ('list', '/tabs'), ('close', '/tabclose')):
            self.assertIn(command, native.native_control_error(action))
        self.assertIn('no tmux detach', native.native_control_error('detach'))

    def test_parser_exposes_backend_selection_and_read_only_doctor(self):
        parser = argparse.ArgumentParser()
        plugin.setup(parser)
        args = parser.parse_args(['doctor', '--backend', 'native', '--json'])
        self.assertEqual((args.action, args.backend, args.json), ('doctor', 'native', True))
        self.assertEqual(parser.parse_args([]).backend, 'auto')

    def test_doctor_does_not_create_plugin_data_or_launch_a_tui(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            storage = types.ModuleType('plugins.plugin_storage')
            storage.plugin_data_dir = lambda *args: self.fail('doctor created plugin data')
            constants = types.ModuleType('hermes_constants')
            constants.get_hermes_home = lambda: Path(tmp) / 'home'
            parser = argparse.ArgumentParser()
            plugin.setup(parser)
            args = parser.parse_args(['doctor', '--directory', tmp, '--json'])
            output = io.StringIO()
            with patch.dict(sys.modules, {'hermes_constants': constants, 'plugins.plugin_storage': storage}), \
                 patch.object(native, 'native_capabilities', return_value=CAPABILITIES), \
                 patch.object(controller.shutil, 'which', return_value='/bin/fixture'), \
                 patch.object(native.subprocess, 'call', side_effect=AssertionError('doctor started a client')), \
                 patch('sys.stdout', output):
                self.assertEqual(controller.main(args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['backend'], 'native')
            self.assertTrue(result['available'])
            self.assertFalse((Path(tmp) / 'home').exists())


if __name__ == '__main__':
    unittest.main()

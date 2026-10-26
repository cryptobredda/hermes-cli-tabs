import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tabs_under_test',ROOT/'tabs.py')
tabs=importlib.util.module_from_spec(spec);spec.loader.exec_module(tabs)


class TabsTests(unittest.TestCase):
    def test_child_env_is_profile_scoped_and_drops_credentials_and_bypass_flags(self):
        result=tabs.child_environment('/profile-b','/project',{'PATH':'/usr/bin','HOME':'/home/test',
            'OPENAI_API_KEY':'do-not-forward','HERMES_YOLO_MODE':'1','HERMES_NON_INTERACTIVE':'1',
            'HERMES_ACCEPT_HOOKS':'1','HERMES_TUI_QUERY':'do not submit','HERMES_HOME':'/profile-a',
            'HERMES_TUI_GATEWAY_URL':'ws://wrong-owner','TMUX':'wrong-server'})
        self.assertEqual(result,{'PATH':'/usr/bin','HOME':'/home/test','HERMES_HOME':'/profile-b','HERMES_CWD':'/project'})

    def test_workspace_and_profile_identity_are_independent(self):
        self.assertNotEqual(tabs.workspace_key('/a','/project'),tabs.workspace_key('/b','/project'))
        self.assertNotEqual(tabs.workspace_key('/a','/project'),tabs.workspace_key('/a','/other'))

    def test_registration_does_not_spawn(self):
        s=importlib.util.spec_from_file_location('tabs_register',ROOT/'__init__.py')
        p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
        class Ctx:
            def register_cli_command(self,*args):self.args=args
        ctx=Ctx()
        with patch('subprocess.run',side_effect=AssertionError('registration started a child')):
            p.register(ctx)
        self.assertEqual(ctx.args[0],'tabs')


@unittest.skipUnless(shutil.which('tmux'),'tmux is required for transport integration tests')
class TmuxIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ct',dir=os.environ.get('TMPDIR'))
        self.root=Path(self.temp.name);self.project=self.root/'p';self.project.mkdir()
        self.fake=self.root/'hermes'
        self.fake.write_text('#!'+sys.executable+'\nimport os,sys\n'
            'print("\\033]2;Demo session\\007",end="",flush=True)\n'
            'print("Interactive Hermes test fixture",flush=True)\n'
            'while True:\n'
            ' line=sys.stdin.readline()\n'
            ' if not line:break\n'
            ' print("received:"+line,flush=True)\n')
        self.fake.chmod(0o700)
        self.controller=tabs.Tabs(self.root/'h',self.project,self.root/'d',hermes=str(self.fake))
        self.controllers=[self.controller]
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for controller in self.controllers:controller.command('kill-server',check=False)
        self.temp.cleanup()

    def wait_windows(self,controller,count):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=controller.windows()
            if len(result)==count:return result
            time.sleep(.05)
        self.fail('Did not get expected windows')

    def test_real_new_select_and_close_use_only_private_server(self):
        self.controller.start(attach=False)
        first=self.wait_windows(self.controller,1)[0]
        self.controller.new();rows=self.wait_windows(self.controller,2)
        self.controller.command('select-window','-t',first['id'])
        self.assertTrue(next(w for w in self.controller.windows() if w['id']==first['id'])['active'])
        self.controller.close(confirmed=True)
        self.assertEqual(len(self.controller.windows()),1)
        self.assertNotIn(first['id'],[w['id'] for w in self.controller.windows()])

    def test_closing_final_tab_opens_another_client_not_a_history_delete(self):
        self.controller.start(attach=False);first=self.wait_windows(self.controller,1)[0]
        self.controller.close(confirmed=True);rows=self.wait_windows(self.controller,1)
        self.assertNotEqual(first['id'],rows[0]['id'])

    def test_each_directory_has_its_own_server_and_root_bindings(self):
        other=self.root/'q';other.mkdir()
        second=tabs.Tabs(self.root/'h',other,self.root/'d',hermes=str(self.fake));self.controllers.append(second)
        self.controller.start(attach=False);second.start(attach=False)
        self.assertNotEqual(self.controller.socket,second.socket)
        self.assertEqual(len(self.controller.windows()),1);self.assertEqual(len(second.windows()),1)
        self.controller.new();self.assertEqual(len(second.windows()),1)

    def test_resume_is_one_exact_quoted_argument(self):
        value='chat; touch '+str(self.root/'do-not-create')
        argv=self.controller.launch(value)
        self.assertIn('--resume=',argv)
        self.controller.start(value,attach=False);self.wait_windows(self.controller,1)
        self.assertFalse((self.root/'do-not-create').exists())
        command=self.controller.command('display-message','-p','-t',self.controller.session,'#{pane_start_command}').stdout
        self.assertIn(value,command)

    def test_display_title_is_cleaned_without_changing_the_native_pane_title(self):
        self.controller.start(attach=False)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and self.controller.windows()[0]['title']!='Demo session':
            time.sleep(.02)
        title='Review form [ABC123def4]'
        native='✓ [OpenCode] '+title+' · model · folder'
        self.controller.command('select-pane','-t',self.controller.session,'-T',native)
        displayed=self.controller.command('display-message','-p','-t',self.controller.session,tabs.title_format()).stdout.strip()
        self.assertEqual(displayed,'✓ Review form')
        actual=self.controller.command('display-message','-p','-t',self.controller.session,'#{pane_title}').stdout.strip()
        self.assertEqual(actual,native)

    def test_real_attached_keyboard_mouse_confirmation_and_draft_retention(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        self.controller.env['TERM']='xterm-256color'
        self.controller.start(attach=False)
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',30,120,0,0))
        proc=subprocess.Popen([*self.controller.base,'attach-session','-t',self.controller.session],
            stdin=slave,stdout=slave,stderr=slave,env=self.controller.env,start_new_session=True)
        os.close(slave)
        def pump(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                ready,_,_=select.select([master],[],[],min(.05,max(0,end-time.monotonic())))
                if ready:
                    try:os.read(master,131072)
                    except OSError:break
        def send(value):os.write(master,value);pump(.25)
        try:
            pump(.8)
            send(b'\x1bn');self.wait_windows(self.controller,2)
            send(b'\x1b1')
            self.assertEqual(next(w['index'] for w in self.controller.windows() if w['active']),1)
            send(b'UNSENT_DEMO_DRAFT')
            send(b'\x1b2');send(b'\x1b1')
            pane=self.controller.command('capture-pane','-p','-t',self.controller.session+':1').stdout
            self.assertIn('UNSENT_DEMO_DRAFT',pane)
            send(b'\x1b[<0;118;1M\x1b[<0;118;1m');self.wait_windows(self.controller,3)
            send(b'\x1bw');self.assertEqual(len(self.controller.windows()),3)
            send(b'n');self.assertEqual(len(self.controller.windows()),3)
            send(b'\x1bw');send(b'y');self.wait_windows(self.controller,2)
            send(b'\x1bq');proc.wait(timeout=5)
            self.assertTrue(self.controller.exists())
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=5)
            os.close(master)

    def test_private_config_has_top_tabs_mouse_and_confirmation(self):
        self.controller.start(attach=False)
        position=self.controller.command('show-option','-gv','status-position').stdout.strip()
        self.assertEqual(position,'top')
        bindings=self.controller.command('list-keys','-T','root').stdout
        self.assertIn('M-n',bindings);self.assertIn('M-w',bindings);self.assertIn('confirm-before',bindings)
        self.assertEqual(self.controller.command('show-option','-gv','prefix').stdout.strip(),'None')


if __name__=='__main__':unittest.main()

"""tmux transport for Hermes tabs; no core imports beyond documented config/storage."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

PLUGIN='cli-session-tabs'
SAFE_ENV={'PATH','HOME','USER','LOGNAME','LANG','LC_ALL','LC_CTYPE','TERM','COLORTERM','SHELL','TMPDIR',
          'DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME'}


def child_environment(home,workspace,environ=None):
    source=os.environ if environ is None else environ
    env={k:str(v) for k,v in source.items() if k in SAFE_ENV or k.startswith('LC_')}
    env.update(HERMES_HOME=str(home),HERMES_CWD=str(workspace))
    # No inherited provider keys, startup queries, YOLO, accept-hooks,
    # noninteractive overrides, or another TUI's connection/file handles.
    return env


def workspace_key(home,workspace):
    return hashlib.sha256((str(Path(home).resolve())+'\0'+str(Path(workspace).resolve())).encode()).hexdigest()[:16]


def tmux_quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')+'"'


def title_format():
    # tmux's format parser treats braces as delimiters, including regexp
    # quantifiers, so repeat the small class rather than using {10}.
    base=r'#{s|\[OpenCode\] ||:pane_title}'
    base=r'#{s| \['+'[A-Za-z0-9]'*10+r'\]||:'+base+'}'
    return r'#{s| ·.*$||:'+base+'}'


def clean_title(value):
    import re
    value=re.sub(r'\[OpenCode\] ','',value)
    value=re.sub(r' \[[A-Za-z0-9]{10}\]','',value).split(' · ',1)[0]
    return ''.join(c for c in value if ord(c)>=32 and not 127<=ord(c)<=159)


def atomic_json(path,value):
    temp=path.with_suffix('.new')
    with temp.open('w') as f:json.dump(value,f);f.write('\n')
    temp.chmod(0o600);os.replace(temp,path)


class Tabs:
    def __init__(self,home,workspace,data_dir,*,interface='tui',hermes=None,tmux=None,environ=None):
        self.home=Path(home).resolve();self.workspace=Path(workspace).resolve();self.data=Path(data_dir).resolve()
        self.tmux=tmux or shutil.which('tmux')
        self.hermes=hermes or shutil.which('hermes')
        if not self.tmux:raise ValueError('tmux is required. Install it from your OS package manager, then run hermes tabs again.')
        if not self.hermes:raise ValueError('The Hermes CLI executable is not on PATH.')
        if not self.workspace.is_dir():raise ValueError('Workspace is not a directory: '+str(self.workspace))
        self.interface=interface;self.key=workspace_key(self.home,self.workspace)
        self.socket='hermes-tabs-'+self.key
        self.session='workspace-'+self.key
        self.env=child_environment(self.home,self.workspace,environ)
        self.data.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.run_dir=self.data/'run';self.run_dir.mkdir(mode=0o700,exist_ok=True)
        # Explicit private runtime root; never use or configure a user's tmux server.
        if len(str(self.run_dir/('tmux-'+str(os.getuid()))/self.socket).encode())>=100:
            import tempfile
            self.run_dir=Path(self.env.get('TMPDIR') or tempfile.gettempdir())
        if len(str(self.run_dir/('tmux-'+str(os.getuid()))/self.socket).encode())>=100:
            raise ValueError('The runtime path is too long for a portable Unix socket; set TMPDIR to a shorter directory.')
        self.env['TMUX_TMPDIR']=str(self.run_dir)
        self.base=[self.tmux,'-L',self.socket]
        self.record=self.data/(self.key+'.json')
        self.config=self.data/('tmux-'+self.key+'.conf')

    def command(self,*args,check=True):
        result=subprocess.run([*self.base,*map(str,args)],env=self.env,capture_output=True,text=True)
        if check and result.returncode:raise ValueError((result.stderr or result.stdout).strip() or 'tmux failed')
        return result

    def exists(self):
        return self.command('has-session','-t',self.session,check=False).returncode==0

    def launch(self,resume=None):
        argv=[self.hermes,'--tui' if self.interface=='tui' else '--cli','--in',str(self.workspace)]
        if resume is not None:argv.append('--resume='+resume)
        # tmux's shell-command field is a shell string: quote EVERY token and
        # start from an empty environment, not a stale daemon's credentials.
        assignments=[k+'='+v for k,v in sorted(self.env.items()) if k!='TMUX_TMPDIR']
        return ('exec '+shlex.join(['env','-i',*assignments])
                +' TMUX="$TMUX" TMUX_PANE="$TMUX_PANE" '+shlex.join(argv))

    def control(self,action):
        return shlex.join([sys.executable,str(Path(__file__).resolve()),'--record',str(self.record),'--action',action])

    def write_settings(self):
        atomic_json(self.record,{'home':str(self.home),'workspace':str(self.workspace),'data_dir':str(self.data),
            'interface':self.interface,'hermes':self.hermes,'tmux':self.tmux,'environment':self.env})
        new=tmux_quote(self.control('new'))
        close=tmux_quote('run-shell '+tmux_quote(self.control('close-now')))
        display='#{=28:'+title_format()+'}'
        lines=[
          'set -g status-position top', 'set -g status on','set -g status-interval 1',
          'set -g status-left ""','set -g status-right " + "','set -g status-right-length 3',
          'set -g status-justify left','set -g status-style "default"',
          'set -g mouse on','set -g prefix None','set -g base-index 1','set -g renumber-windows on',
          'set -g default-shell /bin/sh',
          'set -g allow-rename off','set -g set-titles off','set -g exit-unattached off',
          'set -g window-status-format '+tmux_quote(' #I '+display+' '),
          'set -g window-status-current-format '+tmux_quote('#[reverse,bold] #I '+display+' #[default]'),
          f'bind -n M-n run-shell {new}',
          f'bind -n M-w confirm-before -p "Close tab? Unsent draft will be lost. (y/n)" {close}',
          'bind -n M-q detach-client','bind -n C-PageUp previous-window','bind -n C-PageDown next-window',
          'bind -n MouseDown1Status select-window -t =',
          f'bind -n MouseDown3Status select-window -t = \\; confirm-before -p "Close tab? Unsent draft will be lost. (y/n)" {close}',
          f'bind -n MouseDown1StatusRight run-shell {new}',
          'bind -n WheelUpPane send-keys -M','bind -n WheelDownPane send-keys -M',
        ]
        lines += [f'bind -n M-{i} select-window -t {tmux_quote(self.session+":"+str(i))}' for i in range(1,10)]
        self.config.write_text('\n'.join(lines)+'\n');self.config.chmod(0o600)

    def start(self,resume=None,attach=True):
        self.write_settings()
        if not self.exists():
            self.command('-f',str(self.config),'new-session','-d','-s',self.session,'-c',str(self.workspace),'-n','Hermes',self.launch(resume))
        elif resume is not None:
            self.new(resume)
        # A distinct server per workspace keeps root key bindings, environment
        # and the click target independent of every other project.
        self.command('source-file',str(self.config))
        if attach:
            return subprocess.call([*self.base,'attach-session','-t',self.session],env=self.env)
        return 0

    def new(self,resume=None):
        if not self.exists():raise ValueError('No tab workspace exists here. Run hermes tabs first.')
        return self.command('new-window','-t',self.session,'-c',str(self.workspace),'-n','Hermes',self.launch(resume))

    def windows(self):
        if not self.exists():return []
        value=self.command('list-windows','-t',self.session,'-F','#{window_id}\t#{window_index}\t#{pane_title}\t#{window_active}').stdout
        rows=[]
        for line in value.splitlines():
            fields=line.split('\t',3)
            if len(fields)==4:rows.append({'id':fields[0],'index':int(fields[1]),'title':clean_title(fields[2]),'active':fields[3]=='1'})
        return rows

    def close(self,confirmed=False):
        if not self.exists():raise ValueError('No tab workspace exists here.')
        if not confirmed:
            if not self.command('list-clients','-t',self.session).stdout.strip():
                raise ValueError('Attach the workspace first; tab closing needs an interactive confirmation.')
            return self.command('confirm-before','-t',self.session,'-p','Close tab? Unsent draft will be lost. (y/n)',
                                'run-shell '+tmux_quote(self.control('close-now')))
        target=next((w['id'] for w in self.windows() if w['active']),None)
        if target is None:return
        if len(self.windows())==1:self.new()
        return self.command('kill-window','-t',target)


def main(args):
    if args.action=='start' and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        print('hermes tabs requires an interactive terminal; no child was started.',file=sys.stderr);return 1
    if args.action=='start' and os.environ.get('TMUX'):
        print('Open hermes tabs in a plain terminal, outside an existing tmux client.',file=sys.stderr);return 1
    try:
        from hermes_constants import get_hermes_home
        from plugins.plugin_storage import plugin_data_dir
        workspace=Path(args.directory or Path.cwd()).expanduser().resolve()
        tabs=Tabs(get_hermes_home(),workspace,plugin_data_dir(PLUGIN),interface=args.interface)
        if args.action=='start':return tabs.start(args.resume)
        if args.action=='new':tabs.new(args.resume);return 0
        if args.action=='detach':tabs.command('detach-client','-s',tabs.session);return 0
        if args.action=='close':tabs.close();return 0
        rows=tabs.windows()
        if args.json:print(json.dumps({'directory':str(workspace),'tabs':rows}))
        else:
            for row in rows:print(f"{row['index']}. {row['title']}"+(' *' if row['active'] else ''))
        return 0
    except (OSError,ValueError) as exc:
        print('CLI session tabs: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--record',required=True);parser.add_argument('--action',choices=('new','close-now'),required=True)
    args=parser.parse_args();record=Path(args.record).resolve()
    data=json.loads(record.read_text())
    if record.parent!=Path(data['data_dir']).resolve():raise SystemExit('Invalid managed workspace record')
    tabs=Tabs(data['home'],data['workspace'],data['data_dir'],interface=data['interface'],hermes=data['hermes'],tmux=data['tmux'],environ=data['environment'])
    if args.action=='new':tabs.new()
    else:tabs.close(confirmed=True)

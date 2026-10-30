"""Native TUI launch adapter using only the public CLI capability contract."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from .tabs import child_environment

FEATURES = (
    'session_tabs', 'tab_commands', 'tab_persistence',
    'background_activity', 'slash_completion',
)
HERDR_IDENTITY = ('HERDR_ENV', 'HERDR_PANE_ID', 'HERDR_BIN_PATH', 'HERDR_SOCKET_PATH')
TERMINAL_IDENTITY = ('TMUX', 'TMUX_PANE', 'TERM_PROGRAM', 'TERM_PROGRAM_VERSION', 'KITTY_WINDOW_ID', 'WEZTERM_PANE')


def native_environment(home, workspace, environ=None):
    source = os.environ if environ is None else environ
    env = child_environment(home, workspace, source)
    for key in TERMINAL_IDENTITY:
        if key in source:
            env[key] = str(source[key])
    # One native TUI belongs to this exact inherited pane. Never synthesize a
    # focused-pane identity or pass one shared identity to multiple tmux clients.
    if source.get('HERDR_ENV') == '1' and all(source.get(key) for key in HERDR_IDENTITY):
        env.update({key: str(source[key]) for key in HERDR_IDENTITY})
    return env


def native_capabilities(hermes, env):
    """Unknown/older binaries fall back without ever trying an unknown chat flag."""
    options = dict(env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    try:
        help_result = subprocess.run([str(hermes), '--help'], **options)
        if help_result.returncode or '--tui-capabilities' not in help_result.stdout:
            return None
        result = subprocess.run([str(hermes), '--tui-capabilities'], **options)
        if result.returncode or len(result.stdout) > 65536:
            return None
        value = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value.get('schema') != 1 or value.get('ui') != 'hermes-tui':
        return None
    features = value.get('features')
    if not isinstance(features, dict) or not all(type(features.get(name)) is int and features[name] >= 1 for name in FEATURES):
        return None
    return value


def select_backend(requested, interface, capabilities):
    if requested == 'native':
        if interface != 'tui':
            raise ValueError('The native backend requires --interface tui.')
        if capabilities is None:
            raise ValueError('This Hermes build does not advertise native session tabs. Use --backend tmux, or install a compatible Hermes core build; the plugin never patches core.')
        return 'native'
    if requested == 'tmux':
        return 'tmux'
    return 'native' if interface == 'tui' and capabilities is not None else 'tmux'


class NativeTabs:
    def __init__(self, home, workspace, *, hermes=None, environ=None):
        self.home = Path(home).resolve()
        self.workspace = Path(workspace).resolve()
        self.hermes = hermes or shutil.which('hermes')
        if not self.hermes:
            raise ValueError('The Hermes CLI executable is not on PATH.')
        if not self.workspace.is_dir():
            raise ValueError('Workspace is not a directory: ' + str(self.workspace))
        self.env = native_environment(self.home, self.workspace, environ)

    def argv(self, resume=None):
        args = [str(self.hermes), '--tui', '--in', str(self.workspace)]
        if resume is not None:
            args.append('--resume=' + resume)
        return args

    def start(self, resume=None):
        return subprocess.call(self.argv(resume), cwd=self.workspace, env=self.env)


def native_control_error(action):
    commands = {'new': '/new', 'list': '/tabs', 'close': '/tabclose'}
    if action in commands:
        return 'Native tabs are controlled inside the TUI. Use ' + commands[action] + '; to control an existing tmux workspace explicitly, add --backend tmux.'
    return 'Native mode has no tmux detach operation. Use your host terminal/multiplexer controls, or /quit and relaunch to restore saved native tabs and drafts.'

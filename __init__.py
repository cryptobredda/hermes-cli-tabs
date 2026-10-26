"""A public CLI extension. Import/registration never starts a child process."""

def setup(parser):
    parser.add_argument('action',nargs='?',choices=('start','new','list','detach','close'),default='start')
    parser.add_argument('--directory','--in',dest='directory',help='Workspace directory (default: current folder)')
    parser.add_argument('--resume',help='Open this exact Hermes session ID or title in a new tab')
    parser.add_argument('--interface',choices=('tui','classic'),default='tui')
    parser.add_argument('--json',action='store_true',help='Machine-readable output for list')


def run(args):
    from .tabs import main
    return main(args)


def register(ctx):
    ctx.register_cli_command('tabs','Directory-scoped interactive session tabs (requires tmux)',setup,run)

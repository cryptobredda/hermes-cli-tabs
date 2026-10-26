# CLI Session Tabs for Hermes

Directory-scoped chat tabs across the top of your terminal, installed as an independent Hermes CLI plugin.

![CLI Session Tabs demo](docs/tabs-demo.png)

The screenshot uses clearly labelled demo clients in an isolated tmux workspace; it contains no private conversation data.

## Install

Requirements: Hermes **0.22.2 or newer**, Python 3.10+, an interactive POSIX terminal, and **tmux 3.2+** installed through your OS package manager. Linux, macOS, and Linux under WSL are supported; native Windows is not.

Before catalog approval, install from this repository:

```sh
hermes plugins install https://github.com/cryptobredda/hermes-cli-tabs
hermes plugins enable cli-session-tabs
hermes tabs
```

After the catalog entry is reviewed and merged, the short install name will be `cli-session-tabs`. Submission is not approval.

## Use

```sh
hermes tabs                         # start or reattach this directory's workspace
hermes tabs --directory ~/project   # another exact directory
hermes tabs --resume "chat title"  # open a saved chat in a tab
hermes tabs new                     # add a tab to an already running workspace
hermes tabs new --resume SESSION_ID
hermes tabs list --json
hermes tabs detach
hermes tabs --interface classic     # classic Hermes rather than the modern TUI
```

| Action | Control |
|---|---|
| New tab | **Alt+N**, or click **+** at the right of the strip |
| Select | Click its title, or **Alt+1** through **Alt+9** |
| Previous / next | **Ctrl+PageUp / Ctrl+PageDown** |
| Close | **Alt+W**, or right-click the tab; confirm the visible prompt |
| Detach, keeping tabs and drafts alive | **Alt+Q** |

Closing the final tab through these controls creates a fresh blank tab. `/quit` inside Hermes retains Hermes' normal exit behavior. Accepted gateway work is not a tab's process: closing/detaching a client does not issue `session.interrupt` or delete its history. Unsent drafts are lost if you explicitly confirm closing their client; simply switching or detaching keeps them alive.

One workspace is shared by the same Hermes profile and canonical directory. Re-running `hermes tabs` reattaches it; two clients attaching that workspace share selection. Other profiles and directories use different private sockets. Launch from a plain terminal, outside an existing tmux client.

## Architecture — no Hermes patch

The existing TUI widget SDK can render widgets but cannot control session tabs. This plugin therefore uses the documented `ctx.register_cli_command` extension and tmux's public commands. Each tab runs an ordinary `hermes --tui --in <directory>` (or `--cli`) client. Titles follow its terminal title, with import bookkeeping and model/cwd suffixes removed for display. The exact resume argument and underlying session IDs are never modified.

It does **not** install or alter Hermes source files, JavaScript bundles, private stores, markup, key handlers, your `.tmux.conf`, or another tmux server. `/sessions` within a client still switches that client's chat; to put a saved chat in a separate top-level tab, use `hermes tabs new --resume ...`.

## Security and behavior disclosure

- Runs the installed `tmux`, the installed `hermes`, and this repository's stdlib controller through quoted argument lists. No downloads, package installs, shell startup commands, or self-updater run at registration.
- Starts long-running tmux and interactive Hermes clients only when you run the command. The default start refuses non-TTY/unattended use rather than hanging.
- Child environments are allowlisted. Provider keys, startup queries, YOLO/accept-hooks overrides, noninteractive overrides, and another client's handles are not forwarded. Each Hermes child loads its own profile through Hermes' ordinary secret/config routes.
- Stores only workspace paths, executable locations and non-secret environment metadata under the profile's `plugin-data/cli-session-tabs/`, with private permissions. Runtime sockets normally live there; long paths fall back to the caller's `TMPDIR` using tmux's per-user protected socket directory.
- Does not read credential stores, session databases, messages or private browser data. It makes no network calls itself. The ordinary Hermes clients it launches retain their configured model/network/MCP behavior.
- No telemetry. No core overrides. No automatic approval. Close confirmations are owned by the visible tmux client.

The public plugin intentionally uses a transport-level tab bar, not the earlier in-process prototype. It can coexist with unmodified Hermes releases and does not ship an installer that patches core.

## Development

```sh
python -m unittest discover -s tests -v
hermes plugins validate . --install-deps
```

Tests include real isolated tmux servers with source-only demo clients, quoted resume values, profile/workspace isolation, top-strip bindings, close behavior and child-environment filtering. Test servers are terminated on cleanup. The MIT license is in `LICENSE`.

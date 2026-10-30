# Changelog

## 1.1.0

- Prefer native TUI tabs when Hermes advertises the complete versioned capability contract; retain isolated tmux support for stock/older cores.
- Add explicit `--backend auto|native|tmux` selection and a read-only `doctor --json` diagnostic.
- Keep native session switching, tab-command suggestions, draft/layout restoration, background activity and Herdr reporting owned by the compatible core, not a source-patching plugin installer.
- Preserve the exact inherited Herdr pane identity for a single native client, while continuing to strip provider credentials, startup prompts, resume handles and approval-bypass flags.
- Preserve existing tmux controls, private server/directory/profile isolation, literal resume arguments and interactive close confirmation.
- Distinguish native in-TUI controls from external tmux management commands; do not claim a private-store native remote-control API.
- Document the separate core contribution and whole-Herdr-restart limitations rather than implying an upstream native feature release.

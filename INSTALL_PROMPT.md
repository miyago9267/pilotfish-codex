# Copy/paste install prompt

Install Pilotfish-Codex from this repository checkout. Read `INSTALL.md`
completely, then inspect `install/install.sh` and
`install/AGENT-INSTALL.md`. Identify the Codex home, run the documented
dry-run, and report the selected source, target path, planned writes, and
backups. Stop for my explicit approval before writing the home.

After approval, install from the same source, validate the native config and
roles, and trust exactly `Pilotfish automatic typed Plan-review gate.`. Report
the commands, verification results, changed paths, backups, and unresolved
state. Do not use `sudo`, print credentials, delete files to bypass an
installer error, or use a hook-bypass flag.

If this checkout is unavailable, first ask me for an exact published release
tag or full commit SHA, then fetch and follow that ref's `INSTALL.md`. Do not
assume `main` or invent a ref.

Keep the installed default Luna/Sol policy unchanged. Do not edit `config.toml`
to enable Astra; users opt into the zero-write main-session command separately
when they explicitly choose Astra.

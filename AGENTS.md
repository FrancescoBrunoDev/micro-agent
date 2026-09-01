# AGENTS.md — micro-agent

## What this is

No services, no containers. The "project" is the local AI stack on this machine:

```
kDrive client ──syncs──▶ ~/secondary/kdrive/Obsidian/Francesco_Vault
herdr (runtime) ──owns──▶ pi panes (one workspace per project)
pi ──reads/writes──▶ vault + project files
```

## Components (all native, all installed)

- **herdr** — terminal workspace manager. Pi runs inside herdr panes; the `pi` integration (v8, `~/.pi/agent/extensions/herdr-agent-state.ts`) reports agent state to the sidebar. Attach with `herdr`, stop everything with `herdr server stop`.
- **pi** — the coding agent. Config in `~/.pi/agent/`; `models.json` defines the `ds4` local provider at `http://localhost:9422/v1`. Sessions live in `~/.pi/agent/sessions/`.
- **kDrive client** — official Infomaniak client syncing `~/secondary/kdrive/`. The Obsidian vault `Francesco_Vault` lives there.

## The vault

- Path: `~/secondary/kdrive/Obsidian/Francesco_Vault`
- It has its own `AGENTS.md` — read it before touching vault files.
- herdr has a dedicated workspace: a `pi` pane whose cwd is the vault path.
- kDrive syncs the vault automatically. No other sync mechanism is needed or wanted.

## Removed (history)

- pi-web, Docker deployment, Coolify setup, the old FastAPI gateway — all deleted. Do not reintroduce containers, mounts, or WebDAV clients for this stack: the three native components above are the whole architecture.

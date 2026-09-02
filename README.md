# micro-agent

One Docker container: **herdr + pi + kDrive-synced Obsidian vault**. Portable —
runs on Coolify or any Docker host, independent of any developer machine.

## Quick start

```bash
cp .env.example .env
# set LLAMACPP_BASE_URL (your llama.cpp), KDRIVE_URL/USER/PASS (app password
# from account.infomaniak.com → Security → App passwords), SSH_PUBLIC_KEY,
# OPENCODE_GO_API_KEY and GH_TOKEN

docker compose up -d --build

# attach via SSH (key from .env → authorized_keys inside the container)
ssh -i ~/.ssh/id_ed25519 -p 2222 root@<host>
# then: herdr

# or attach the herdr TUI straight from the desktop (port via ~/.ssh/config)
herdr --remote root@<host>

# drive pi headlessly
ssh -p 2222 root@<host> herdr agent prompt vault "aggiorna il piano di allenamento" --wait
```

The vault is bidirectionally synced with kDrive every 60s (rclone WebDAV
bisync). Your desktop's own kDrive client keeps Obsidian working as before.

## Coolify

- Expose port **2222 → 22** (ssh). No web ports needed — it's an agent host.
- Attach a **persistent volume** to `/data` (pi sessions, herdr layout,
  rclone config, vault copy).
- Set the env vars above; `LLAMACPP_BASE_URL` can point to another Coolify
  service by hostname.

See [AGENTS.md](AGENTS.md) for the full architecture and pitfalls.

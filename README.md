# micro-agent

One Docker container: **herdr + pi + kDrive-synced Obsidian vault**. Portable —
runs on Coolify or any Docker host, independent of any developer machine.

## Quick start

```bash
cp .env.example .env
# set LLM_BASE_URL (your LLM) and KDRIVE_URL/USER/PASS (app password from
# account.infomaniak.com → Security → App passwords)

docker compose up -d --build

# attach to the herdr TUI (see pi working on the vault)
docker exec -it micro-agent herdr

# or drive pi headlessly
docker exec -it micro-agent herdr agent prompt vault "aggiorna il piano di allenamento" --wait
```

The vault is bidirectionally synced with kDrive every 60s (rclone WebDAV
bisync). Your desktop's own kDrive client keeps Obsidian working as before.

## Coolify

- No ports, no domains — it's an agent host, not a web app. Attach via
  Coolify's container terminal (`docker exec -it ... herdr`).
- Attach a **persistent volume** to `/data` (pi sessions, herdr layout,
  rclone config, vault copy).
- Set the env vars above; `LLM_BASE_URL` can point to another Coolify service
  by hostname.

See [AGENTS.md](AGENTS.md) for the full architecture and pitfalls.

"""Karpathy-style markdown memory backend.

Memory is stored as plain markdown files with YAML frontmatter,
organized by type (episodic, semantic, procedural). Retrieval is
grep-based — no vector DB, no infrastructure.

This is the "memory" layer for micro-agent, inspired by Andrej Karpathy's
LLM Wiki: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import yaml

from micro_agent.models import MemoryEntry, MemoryType

log = logging.getLogger(__name__)

# Regex to extract YAML frontmatter from markdown
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _path(memory_path: Path, mem_type: MemoryType) -> Path:
    return memory_path / mem_type.value


def _ensure_dirs(memory_path: Path) -> None:
    """Create memory directory structure if it doesn't exist."""
    for t in MemoryType:
        (_path(memory_path, t)).mkdir(parents=True, exist_ok=True)
    if not (memory_path / "index.md").exists():
        _write_index(memory_path)
    if not (memory_path / "schema.md").exists():
        _write_default_schema(memory_path)


def _write_index(memory_path: Path) -> None:
    """Write or update the memory index."""
    index = memory_path / "index.md"
    total = 0
    for t in MemoryType:
        total += len(list(_path(memory_path, t).glob("*.md")))

    content = f"""# Memory Index

> Every memory file listed under its type with a one-line summary.
> Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
> Total files: {total}

"""
    for t in MemoryType:
        content += f"\n## {t.value.capitalize()}\n\n"
        for f in sorted(_path(memory_path, t).glob("*.md")):
            slug = f.stem
            text = f.read_text(encoding="utf-8", errors="replace")
            body = FRONTMATTER_RE.sub("", text).strip()
            summary = body.split("\n")[0][:80] if body else "(empty)"
            content += f"- [[{slug}]] — {summary}\n"

    index.write_text(content, encoding="utf-8")


def _write_default_schema(memory_path: Path) -> None:
    """Write the default memory schema."""
    schema = memory_path / "schema.md"
    content = """---
title: Memory Schema
---

# Memory Schema

## Types

| Type | Purpose | Example |
|------|---------|---------|
| **episodic** | Conversation facts, specific events | "User prefers uv over pip" |
| **semantic** | General knowledge, user preferences | "User runs Strix Halo with AMD GPU" |
| **procedural** | How-to, workflows, recurring patterns | "Steps to deploy on Coolify" |

## Format

Every memory file has YAML frontmatter:

```yaml
---
title: Short descriptive title
type: episodic | semantic | procedural
created: YYYY-MM-DDTHH:MM:SS+00:00
updated: YYYY-MM-DDTHH:MM:SS+00:00
tags: [tag1, tag2]
source: what triggered this
confidence: high | medium | low
---
```

## Retrieval

- grep/rg for keyword search across all .md files
- Read index.md first to find relevant files
- Max 3 files injected as context per turn

## Compaction

- When a type exceeds 300 files, consolidate
- Merge related entries, archive duplicates
- Bump the updated date
"""
    schema.write_text(content, encoding="utf-8")


def _slugify(title: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def _read_frontmatter(path: Path) -> dict:
    """Read YAML frontmatter from a markdown file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _write_memory_file(path: Path, entry: MemoryEntry) -> None:
    """Write a memory entry to a markdown file with frontmatter."""
    frontmatter = {
        "title": entry.title,
        "type": entry.type.value,
        "created": entry.created or datetime.now(timezone.utc).isoformat(),
        "updated": entry.updated or datetime.now(timezone.utc).isoformat(),
        "tags": entry.tags,
        "source": entry.source,
        "confidence": entry.confidence,
    }

    lines = [
        "---",
        yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip(),
        "---",
        "",
        entry.content.strip(),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


class MemoryStore:
    """Karpathy-style markdown memory backend.

    Usage:
        store = MemoryStore(Path("~/.micro-agent/memory"))
        store.add(MemoryEntry(title="User prefers uv", content="..."))
        results = store.search("uv pip")
    """

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).expanduser().resolve()
        _ensure_dirs(self.base_path)

    def add(self, entry: MemoryEntry) -> Path:
        """Store a new memory entry as a markdown file."""
        now = datetime.now(timezone.utc).isoformat()
        if not entry.created:
            entry.created = now
        entry.updated = now

        slug = _slugify(entry.title)
        filepath = _path(self.base_path, entry.type) / f"{slug}.md"

        if filepath.exists():
            existing = self.get(slug)
            if existing:
                entry.created = existing.created
                if entry.content not in existing.content:
                    entry.content = f"{existing.content}\n\n---\n\n{entry.content}"
                    entry.updated = now

        _write_memory_file(filepath, entry)
        _write_index(self.base_path)
        log.info("Memory written: %s", filepath.relative_to(self.base_path))
        return filepath

    def get(self, slug: str) -> MemoryEntry | None:
        """Retrieve a memory entry by its slug."""
        for t in MemoryType:
            path = _path(self.base_path, t) / f"{slug}.md"
            if path.exists():
                return self._parse_file(path)
        return None

    def _parse_file(self, path: Path) -> MemoryEntry:
        """Parse a memory file into a MemoryEntry."""
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = _read_frontmatter(path)
        body = FRONTMATTER_RE.sub("", text).strip()

        return MemoryEntry(
            title=meta.get("title", path.stem),
            type=MemoryType(meta.get("type", "episodic")),
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
            tags=meta.get("tags", []),
            source=meta.get("source", ""),
            confidence=meta.get("confidence", "medium"),
            content=body,
        )

    def search(self, query: str, max_results: int = 5) -> list[MemoryEntry]:
        """Search memory using grep."""
        results: list[tuple[MemoryEntry, int]] = []

        for t in MemoryType:
            search_dir = _path(self.base_path, t)
            if not search_dir.exists():
                continue

            try:
                proc = subprocess.run(
                    ["grep", "-rli", query, "--include=*.md", str(search_dir)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    for filepath_str in proc.stdout.strip().split("\n"):
                        filepath = Path(filepath_str)
                        entry = self._parse_file(filepath)
                        match_count = entry.content.lower().count(query.lower())
                        results.append((entry, match_count))
            except (subprocess.TimeoutError, FileNotFoundError):
                for md_file in sorted(search_dir.glob("*.md")):
                    text = md_file.read_text(encoding="utf-8", errors="replace")
                    if query.lower() in text.lower():
                        entry = self._parse_file(md_file)
                        results.append((entry, 1))

        results.sort(key=lambda x: -x[1])
        return [entry for entry, _ in results[:max_results]]

    def get_relevant_context(self, message: str, max_files: int = 3) -> str:
        """Get memory context relevant to a message."""
        words = set(w.lower() for w in message.split() if len(w) > 3)
        results: list[MemoryEntry] = []

        for word in words:
            for entry in self.search(word, max_results=2):
                if entry not in results:
                    results.append(entry)

        context_parts = []
        for entry in results[:max_files]:
            context_parts.append(
                f"## Memory: {entry.title}\n"
                f"Type: {entry.type.value} | "
                f"Confidence: {entry.confidence}\n"
                f"{entry.content[:500]}"
            )

        if not context_parts:
            return ""

        return (
            "## Relevant Memory Context\n"
            "The following information was retrieved from persistent memory:\n\n"
            + "\n\n".join(context_parts)
        )

    def get_all(self, mem_type: MemoryType | None = None) -> list[MemoryEntry]:
        """List all memory entries."""
        result = []
        types = [mem_type] if mem_type else list(MemoryType)
        for t in types:
            for md_file in sorted(_path(self.base_path, t).glob("*.md")):
                if md_file.name not in ("index.md", "schema.md"):
                    result.append(self._parse_file(md_file))
        return result

    def delete(self, slug: str) -> bool:
        """Delete a memory entry by slug."""
        for t in MemoryType:
            path = _path(self.base_path, t) / f"{slug}.md"
            if path.exists():
                path.unlink()
                _write_index(self.base_path)
                return True
        return False

    def compact(self, mem_type: MemoryType | None = None) -> int:
        """Report compaction needs."""
        types = [mem_type] if mem_type else list(MemoryType)
        for t in types:
            files = sorted(_path(self.base_path, t).glob("*.md"))
            memory_files = [f for f in files if f.name not in ("index.md", "schema.md")]
            if len(memory_files) > 300:
                log.info(
                    "%s memory has %d files — manual review recommended",
                    t.value, len(memory_files),
                )
        _write_index(self.base_path)
        return 0

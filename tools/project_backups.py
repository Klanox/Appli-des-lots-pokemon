"""Create and prune Pokestock project backups on the Desktop.

Usage:
    python tools/project_backups.py "Appli des lots pokemon - BACKUP BEFORE ..."
    python tools/project_backups.py --list
    python tools/project_backups.py --dry-run "Appli des lots pokemon - BACKUP BEFORE ..."

The cleanup is intentionally narrow: only Desktop directories whose names start
exactly with "Appli des lots pokemon - BACKUP" can be removed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


BACKUP_PREFIX = "Appli des lots pokemon - BACKUP"
PROJECT_NAME = "Appli des lots pokemon"
DEFAULT_KEEP = 5


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def default_project_dir() -> Path:
    return desktop_dir() / PROJECT_NAME


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_pokestock_backup_dir(path: Path, desktop: Path | None = None) -> bool:
    desktop = _resolved(desktop or desktop_dir())
    candidate = _resolved(path)
    return (
        candidate.parent == desktop
        and candidate.is_dir()
        and candidate.name.startswith(BACKUP_PREFIX)
        and "BACKUP" in candidate.name
        and candidate != desktop / PROJECT_NAME
    )


def _assert_safe_backup_dir(path: Path, desktop: Path) -> Path:
    candidate = _resolved(path)
    desktop = _resolved(desktop)
    if not is_pokestock_backup_dir(candidate, desktop):
        raise ValueError(f"Refusing to touch non-Pokestock backup folder: {candidate}")
    return candidate


def list_backup_dirs(desktop: Path | None = None) -> list[Path]:
    desktop = _resolved(desktop or desktop_dir())
    if not desktop.exists():
        return []
    backups = [
        child
        for child in desktop.iterdir()
        if child.is_dir() and is_pokestock_backup_dir(child, desktop)
    ]
    return sorted(backups, key=lambda p: p.stat().st_mtime, reverse=True)


def cleanup_old_backups(
    *,
    keep: int = DEFAULT_KEEP,
    desktop: Path | None = None,
    dry_run: bool = False,
) -> dict[str, list[str] | int]:
    desktop = _resolved(desktop or desktop_dir())
    backups = list_backup_dirs(desktop)
    kept = backups[:keep]
    to_delete = backups[keep:]
    deleted: list[str] = []

    for backup in to_delete:
        safe_backup = _assert_safe_backup_dir(backup, desktop)
        deleted.append(str(safe_backup))
        if not dry_run:
            shutil.rmtree(safe_backup)

    remaining = list_backup_dirs(desktop) if not dry_run else kept
    return {
        "kept_count": len(remaining),
        "kept": [str(path) for path in remaining],
        "deleted_count": len(deleted),
        "deleted": deleted,
    }


def create_project_backup(
    backup_name: str,
    *,
    keep: int = DEFAULT_KEEP,
    project_dir: Path | None = None,
    desktop: Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    desktop = _resolved(desktop or desktop_dir())
    project_dir = _resolved(project_dir or default_project_dir())
    target = _resolved(desktop / backup_name)

    if not backup_name.startswith(BACKUP_PREFIX):
        raise ValueError(f"Backup name must start exactly with: {BACKUP_PREFIX}")
    if target.parent != desktop:
        raise ValueError(f"Backup must be created directly on the Desktop: {target}")
    if target == project_dir:
        raise ValueError("Refusing to use the project folder as a backup target.")
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")

    deleted_existing = False
    if target.exists():
        _assert_safe_backup_dir(target, desktop)
        deleted_existing = True
        if not dry_run:
            shutil.rmtree(target)

    if not dry_run:
        shutil.copytree(project_dir, target)
        if not (target / "app.py").is_file():
            raise RuntimeError(f"Backup verification failed, app.py missing in: {target}")
        now = time.time()
        try:
            os.utime(target, (now, now))
        except OSError:
            pass

    cleanup = cleanup_old_backups(keep=keep, desktop=desktop, dry_run=dry_run)
    return {
        "backup_created": str(target),
        "deleted_existing_same_name": deleted_existing,
        "cleanup": cleanup,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and prune Pokestock backups.")
    parser.add_argument("backup_name", nargs="?", help="Desktop backup folder name to create.")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="Backups to keep.")
    parser.add_argument("--list", action="store_true", help="List current Pokestock backups.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen.")
    args = parser.parse_args(argv)

    if args.keep < 1:
        parser.error("--keep must be at least 1")

    if args.list:
        payload = {"backups": [str(path) for path in list_backup_dirs()]}
    else:
        if not args.backup_name:
            parser.error("backup_name is required unless --list is used")
        payload = create_project_backup(args.backup_name, keep=args.keep, dry_run=args.dry_run)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

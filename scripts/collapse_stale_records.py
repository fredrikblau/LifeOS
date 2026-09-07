#!/usr/bin/env python3
"""Retire stale snapshots and merge forked projects in existing data.

`create_memory` and `project_store.upsert` now recognize when a new record
restates one that already exists, but data written before that keeps its
duplicates — and a stale snapshot is not inert. On the deployment that
prompted this, fifteen "Car repair status (as of ...)" memories were active
at once, and the assistant answered from a three-week-old one that the user
had already corrected.

This applies the same identity rule to what is already on disk:

- memories: for each status subject, the newest snapshot stays active and the
  earlier ones are marked superseded (kept, linked, and still on disk under
  `superseded` — never deleted);
- projects: records whose names resolve to one subject are merged into the
  oldest, keeping its name, taking the newest status/summary/next action, and
  preserving the others' history and sources.

Dry-run by default. Nothing is written until you pass --apply, and --apply
writes a timestamped backup of each file first.

    ./scripts/collapse_stale_records.py            # show what would change
    ./scripts/collapse_stale_records.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services.subject_key import status_subject, subject_key  # noqa: E402

MEMORIES = Path.home() / ".lifeos" / "memories.json"
PROJECTS = Path.home() / ".lifeos" / "projects.json"


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    destination = path.with_name(f"{path.name}.backup-{stamp}")
    shutil.copy2(path, destination)
    return destination


def _sort_key(record: dict) -> str:
    return record.get("created_at") or record.get("updated_at") or ""


def collapse_memories(path: Path, apply: bool) -> int:
    if not path.exists():
        print(f"  {path} does not exist — skipping")
        return 0
    data = json.loads(path.read_text())
    active = data.get("memories", [])

    groups: dict[str, list[dict]] = {}
    for memory in active:
        subject = status_subject(memory.get("content"))
        if subject:
            groups.setdefault(subject, []).append(memory)

    now = datetime.now(timezone.utc).isoformat()
    retired_ids: dict[str, str] = {}
    for subject, records in groups.items():
        if len(records) < 2:
            continue
        records.sort(key=_sort_key)
        newest = records[-1]
        print(f"\n  subject {subject!r}: keeping the {_sort_key(newest)[:10]} snapshot, "
              f"retiring {len(records) - 1}")
        print(f"    LIVE    {newest.get('content', '')[:96]}")
        for stale in records[:-1]:
            print(f"    retire  {_sort_key(stale)[:10]}  {stale.get('content', '')[:80]}")
            retired_ids[stale["id"]] = newest["id"]

    if not retired_ids:
        print("  nothing to retire")
        return 0

    if apply:
        superseded = list(data.get("superseded", []))
        keep = []
        for memory in active:
            successor = retired_ids.get(memory.get("id"))
            if successor:
                memory["is_active"] = False
                memory["superseded_by"] = successor
                memory["superseded_at"] = now
                superseded.append(memory)
            else:
                keep.append(memory)
        data["memories"] = keep
        data["superseded"] = superseded
        data["last_updated"] = datetime.now().isoformat()
        print(f"\n  backup: {_backup(path).name}")
        path.write_text(json.dumps(data, indent=2))
        print(f"  wrote {path} — {len(keep)} active, {len(superseded)} superseded")
    return len(retired_ids)


def collapse_projects(path: Path, apply: bool) -> int:
    if not path.exists():
        print(f"  {path} does not exist — skipping")
        return 0
    data = json.loads(path.read_text())
    projects = data.get("projects", [])

    groups: dict[str, list[dict]] = {}
    for project in projects:
        key = subject_key(project.get("name"))
        if key:
            groups.setdefault(key, []).append(project)

    merged_away: set[str] = set()
    for key, records in groups.items():
        if len(records) < 2:
            continue
        records.sort(key=_sort_key)
        # The oldest record keeps its identity and name; the newest state wins.
        primary, *rest = records
        newest = max(records, key=lambda r: r.get("updated_at") or "")
        print(f"\n  merging into {primary['name']!r} (subject {key!r}):")
        for other in rest:
            print(f"    + {other['name']!r} (updated {other.get('updated_at', '')[:10]})")
            merged_away.add(other["id"])
            primary.setdefault("history", []).extend(other.get("history", []))
            primary["history"].append({
                "at": other.get("updated_at"),
                "merged_from": other.get("name"),
                "status": other.get("status", ""),
                "summary": other.get("summary", ""),
                "next_action": other.get("next_action", ""),
            })
            for source in other.get("sources", []):
                if source not in primary.setdefault("sources", []):
                    primary["sources"].append(source)
        for field in ("status", "summary", "next_action", "priority"):
            if newest.get(field):
                primary[field] = newest[field]
        primary["updated_at"] = newest.get("updated_at") or primary.get("updated_at")

    if not merged_away:
        print("  nothing to merge")
        return 0

    if apply:
        data["projects"] = [p for p in projects if p["id"] not in merged_away]
        print(f"\n  backup: {_backup(path).name}")
        path.write_text(json.dumps(data, indent=2))
        print(f"  wrote {path} — {len(data['projects'])} projects")
    return len(merged_away)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default: dry run)")
    parser.add_argument("--memories", type=Path, default=MEMORIES)
    parser.add_argument("--projects", type=Path, default=PROJECTS)
    args = parser.parse_args()

    print("Memories" + ("" if args.apply else " (dry run)"))
    retired = collapse_memories(args.memories, args.apply)
    print("\nProjects" + ("" if args.apply else " (dry run)"))
    merged = collapse_projects(args.projects, args.apply)

    print(f"\n{retired} snapshot(s) retired, {merged} project(s) merged.")
    if not args.apply and (retired or merged):
        print("Re-run with --apply to write it. Backups are taken automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

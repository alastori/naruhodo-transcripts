#!/usr/bin/env python3
"""Migrate transcript filenames from old naming to new episode-key naming.

Old: 400 - Naruhodo #400 - Por que gostamos de música？.pt.vtt
New: N400 - Por que gostamos de música？.pt.vtt

Old: 050 - Naruhodo Entrevista #50： Dr. Maria Santos.pt.vtt
New: E050 - Dr. Maria Santos.pt.vtt

Dry run by default. Use --apply to rename files.

Usage:
    python scripts/migrate_filenames.py              # preview changes
    python scripts/migrate_filenames.py --apply      # rename files
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import EPISODES_JSON, TRANSCRIPTS_DIR, episode_filename, episode_key


def main():
    apply = "--apply" in sys.argv

    if not TRANSCRIPTS_DIR.exists():
        print("No transcripts directory found.")
        return

    # Load episodes for metadata
    episodes = json.loads(EPISODES_JSON.read_text())
    ep_by_num_type = {}
    for ep in episodes:
        key = episode_key(ep)
        if key:
            ep_by_num_type[key] = ep

    # Process each file
    renames = []
    skipped = 0
    already_new = 0

    for f in sorted(TRANSCRIPTS_DIR.iterdir()):
        if f.suffix not in (".vtt", ".md") and not f.name.endswith(".quality.json") and not f.name.endswith(".segments.json"):
            continue

        name = f.name

        # Already in new format?
        if re.match(r"^[NEXRO]\d{3} - ", name):
            already_new += 1
            continue

        # Determine the episode key from the filename
        key = None

        # Try "Entrevista #N"
        m = re.search(r"Entrevista\s+#(\d+)", name)
        if m:
            key = f"E{int(m.group(1)):03d}"

        # Try "Extra #N"
        if not key:
            m = re.search(r"Extra\s+#(\d+)", name)
            if m:
                key = f"X{int(m.group(1)):03d}"

        # Try REPLAY/REPOST
        if not key and ("REPLAY" in name or "REPOST" in name):
            m = re.search(r"#(\d+)", name)
            if m:
                key = f"R{int(m.group(1)):03d}"

        # Try regular "Naruhodo #N"
        if not key:
            m = re.search(r"Naruhodo\s+#(\d+)", name)
            if m:
                key = f"N{int(m.group(1)):03d}"

        # Try bare "#N" as last resort
        if not key:
            m = re.search(r"#(\d+)", name)
            if m:
                key = f"N{int(m.group(1)):03d}"

        if not key:
            skipped += 1
            continue

        # Get the episode data for the topic
        ep = ep_by_num_type.get(key, {})
        topic = ep.get("topic", "")

        if not topic:
            # Extract topic from filename itself
            topic_match = re.match(r"\d+ - (?:REPLAY[：:\s]*)?(?:REPOST[：:\s]*)?(?:Naruhodo\s*(?:Entrevista\s*|Extra\s*)?#?\d*\s*[-：:\s]*)?(.+?)(?:\.[a-z]{2}\.vtt|\.whisper\.md|\.quality\.json|\.segments\.json)$", name)
            if topic_match:
                topic = topic_match.group(1).strip()

        if not topic:
            topic = "Unknown"

        # Sanitize topic
        safe_topic = topic.replace(":", "\uff1a").replace("?", "\uff1f")
        safe_topic = re.sub(r'[<>"/\\|*/]', "", safe_topic)[:80]

        # Determine extension
        if name.endswith(".whisper.md"):
            ext = ".whisper.md"
        elif name.endswith(".quality.json"):
            ext = ".quality.json"
        elif name.endswith(".segments.json"):
            ext = ".segments.json"
        elif name.endswith(".pt.vtt"):
            ext = ".pt.vtt"
        elif name.endswith(".pt 2.vtt"):
            ext = ".pt 2.vtt"
        else:
            ext = f.suffix

        new_name = f"{key} - {safe_topic}{ext}"
        if new_name == name:
            already_new += 1
            continue

        new_path = TRANSCRIPTS_DIR / new_name

        # Handle collision
        if new_path.exists() and new_path != f:
            new_name = f"{key} - {safe_topic} (2){ext}"
            new_path = TRANSCRIPTS_DIR / new_name

        renames.append((f, new_path))

    # Report
    print(f"Files scanned: {already_new + len(renames) + skipped}")
    print(f"Already new format: {already_new}")
    print(f"To rename: {len(renames)}")
    print(f"Skipped (no key): {skipped}")

    if renames:
        print(f"\n{'PREVIEW' if not apply else 'RENAMING'}:")
        for old, new in renames[:20]:
            print(f"  {old.name}")
            print(f"  → {new.name}")
            print()
        if len(renames) > 20:
            print(f"  ... and {len(renames) - 20} more")

    if renames and apply:
        print(f"\nRenaming {len(renames)} files...")
        for old, new in renames:
            old.rename(new)
        print("Done.")
    elif renames and not apply:
        print(f"\nDry run. Use --apply to rename files.")


if __name__ == "__main__":
    main()

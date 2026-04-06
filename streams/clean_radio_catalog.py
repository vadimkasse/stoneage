#!/usr/bin/env python3
"""
Regenerate radio_catalog.csv by filtering radio_pool.json with exclude tags.
Reads exclude tags from radio_tags.md, applies filtering to create clean catalog.
Does NOT modify radio_pool.json (preserves raw pool for future reference).
Usage: python3 streams/clean_radio_catalog.py
"""

import json
import subprocess
from pathlib import Path

POOL_PATH = Path(__file__).parent.parent / "private" / "radio_pool.json"
TAGS_CONFIG = Path(__file__).parent / "radio_tags.md"


def load_exclude_tags():
    """Load exclude tags from radio_tags.md (## exclude section, pipe-separated)."""
    if not TAGS_CONFIG.exists():
        print(f"ERROR: {TAGS_CONFIG} not found")
        return set()

    try:
        content = TAGS_CONFIG.read_text()
        # Find ## exclude section
        if "## exclude" not in content:
            return set()

        exclude_section = content.split("## exclude")[1]
        # Look for pipe-separated tags (the last line with pipes)
        for line in exclude_section.split("\n"):
            if "|" in line:
                # Found the tag line
                tags = set(t.strip() for t in line.split("|") if t.strip())
                return tags

        return set()
    except Exception as e:
        print(f"ERROR reading {TAGS_CONFIG}: {e}")
        return set()


def is_excluded(station: dict, exclude_tags: set) -> bool:
    """Check if station has excluded words in tags OR name."""
    if not exclude_tags:
        return False

    tags_str = station.get("tags", "").lower()
    name_str = station.get("name", "").lower()

    # Check if any excluded word appears in tags or name
    for word in exclude_tags:
        if word in tags_str or word in name_str:
            return True
    return False


def main():
    # Load exclude tags
    exclude_tags = load_exclude_tags()
    if not exclude_tags:
        print("ERROR: No exclude tags found in radio_tags.md")
        return

    print(f"Loaded {len(exclude_tags)} exclude tags from radio_tags.md")

    if not POOL_PATH.exists():
        print(f"ERROR: {POOL_PATH} not found")
        return

    # Load pool
    with open(POOL_PATH, "r", encoding="utf-8") as f:
        pool = json.load(f)

    original_count = len(pool)
    print(f"Loaded {original_count} records from {POOL_PATH}")

    # Filter out excluded records (for catalog generation only)
    filtered = [s for s in pool if not is_excluded(s, exclude_tags)]
    removed_count = original_count - len(filtered)

    print(f"Would exclude: {removed_count} stations with excluded tags")
    print(f"Clean catalog will have: {len(filtered)} records")

    # Regenerate catalog
    print("\nRegenerating radio_catalog.csv…")
    try:
        result = subprocess.run(
            ["python3", "streams/make_radio_catalog.py"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
            print("✓ Catalog regenerated")
        else:
            print(f"ERROR: {result.stderr}")
    except Exception as e:
        print(f"ERROR running make_radio_catalog.py: {e}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import json
import csv
from pathlib import Path


def load_exclude_tags():
    """Load exclude tags from radio_tags.md (## exclude section, pipe-separated)."""
    tags_config = Path(__file__).parent / "radio_tags.md"

    if not tags_config.exists():
        print(f"WARNING: {tags_config} not found, no filtering applied")
        return set()

    try:
        content = tags_config.read_text()
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
        print(f"ERROR reading {tags_config}: {e}")
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


# Load exclude tags
exclude_tags = load_exclude_tags()
print(f"Loaded {len(exclude_tags)} exclude tags from radio_tags.md")

# Read radio_pool.json
with open(str(Path(__file__).parent.parent / 'private' / 'radio_pool.json'), 'r') as f:
    data = json.load(f)

# Filter records with status: ok AND not excluded
records = data if isinstance(data, list) else data.get('records', [])
filtered = [r for r in records if r.get('status') == 'ok' and not is_excluded(r, exclude_tags)]

# Write to radio_catalog.csv
with open(str(Path(__file__).parent.parent / 'private' / 'radio_catalog.csv'), 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['name', 'url', 'country', 'countrycode', 'language', 'tags'])
    writer.writeheader()
    for record in filtered:
        writer.writerow({
            'name': record.get('name', ''),
            'url': record.get('url', ''),
            'country': record.get('country', ''),
            'countrycode': record.get('countrycode', ''),
            'language': record.get('language', ''),
            'tags': record.get('tags', '')
        })

print(f"Processed {len(filtered)} records")

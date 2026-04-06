#!/usr/bin/env python3
"""
LUMEN Radio Extractor

Fetches speech radio stations from Radio Browser API, validates basic connectivity via ffmpeg.
Content validation (loudness, speech ratio) happens in lumen_generator.py at runtime.

Usage:
    python lumen_radio_extractor.py              # fetch & validate connectivity
    python lumen_radio_extractor.py --recheck    # recheck existing pool
    python lumen_radio_extractor.py --dry-run    # show candidates without validation
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests

API_BASE          = "https://de1.api.radio-browser.info/json"
POOL_PATH         = Path(__file__).parent.parent / "private" / "radio_pool.json"
TAGS_CONFIG       = Path(__file__).parent / "radio_tags.md"
PREFLIGHT_S       = 4         # seconds to probe
TIMEOUT_S         = 12        # ffmpeg wall-clock timeout

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def load_include_tags() -> list[str]:
    """Load include tags from radio_tags.md (## include section)."""
    if not TAGS_CONFIG.exists():
        print(f"WARNING: {TAGS_CONFIG} not found, using defaults")
        return ["news", "talk", "speech", "information"]

    try:
        content = TAGS_CONFIG.read_text()
        # Find ## include section and extract tags
        if "## include" in content:
            include_section = content.split("## include")[1]
            # Stop at next ## or end of file
            if "##" in include_section[1:]:
                include_section = include_section[:include_section.index("##", 1)]
            # Extract tags (lines starting with -)
            tags = []
            for line in include_section.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    tags.append(line[2:].strip())
            return tags if tags else ["news", "talk", "speech", "information"]
    except Exception as e:
        print(f"ERROR reading {TAGS_CONFIG}: {e}")

    return ["news", "talk", "speech", "information"]


def fetch_stations() -> list[dict]:
    """
    Fetch stations from Radio Browser API with filters:
    - tags: loaded from radio_tags.md ## include section
    - lastcheckok: 1 (recently validated)
    - hidebroken: true
    - NO filtering by blacklist (that happens in make_radio_catalog.py)
    """
    print("Fetching Radio Browser API…")

    include_tags = load_include_tags()
    print(f"Include tags: {', '.join(include_tags)}")

    # API query parameters
    params = {
        "limit": 500,  # per tag query
        "order": "random",
        "hidebroken": "true",
        "lastcheckok": "1",
    }

    # Fetch stations matching tags
    candidates = []
    for tag in include_tags:
        params["tag"] = tag
        try:
            resp = requests.get(
                f"{API_BASE}/stations/search",
                params=params,
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json()
            print(f"  Tag '{tag}': {len(results)} results")
            candidates.extend(results)
        except Exception as e:
            print(f"  ERROR fetching tag '{tag}': {e}")
            continue

    # Deduplicate by URL (no blacklist filtering here)
    seen = set()
    unique = []
    for c in candidates:
        url = c.get("url_resolved") or c.get("url", "")
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        unique.append(c)

    print(f"  Unique candidates after dedup: {len(unique)}")
    return unique


def preflight(url: str) -> tuple[bool, str]:
    """
    Run ffmpeg preflight: try to read PREFLIGHT_S seconds of stream.
    Returns (ok, reason).
    """
    cmd = [
        "ffmpeg",
        "-rw_timeout", str(TIMEOUT_S * 1_000_000),
        "-i", url,
        "-t", str(PREFLIGHT_S),
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            timeout=TIMEOUT_S + 5,
            capture_output=True,
        )
        if result.returncode == 0:
            return True, "ok"
        stderr = result.stderr.decode(errors="ignore")
        lines = [l.strip() for l in stderr.splitlines() if l.strip()]
        reason = lines[-1][:100] if lines else "unknown error"
        return False, reason
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)


def load_pool() -> list[dict]:
    """Load existing radio pool."""
    if POOL_PATH.exists():
        return json.loads(POOL_PATH.read_text())
    return []


def save_pool(pool: list[dict]) -> None:
    """Save validated pool to JSON."""
    POOL_PATH.write_text(json.dumps(pool, indent=2, ensure_ascii=False))
    print(f"\n✓ Saved {len(pool)} stations → {POOL_PATH}")


def run(recheck: bool, dry_run: bool) -> None:
    """Main extraction pipeline."""
    today = date.today().isoformat()

    if recheck:
        pool = load_pool()
        if not pool:
            print("Pool is empty, nothing to recheck.")
            return
        candidates = pool
        print(f"Rechecking {len(candidates)} existing pool entries…")
    else:
        candidates = fetch_stations()
        if not candidates:
            print("No candidates found.")
            return

    if dry_run:
        print(f"\n[DRY-RUN] Would validate {len(candidates)} stations (no ffmpeg calls)")
        print("\nFirst 5 candidates:")
        for i, c in enumerate(candidates[:5], 1):
            print(f"  {i}. {c.get('name', 'N/A')} ({c.get('countrycode', '?')}) → {c.get('url_resolved', c.get('url', ''))[:60]}")
        return

    existing_pool = load_pool() if not recheck else []
    existing_urls = {c["url"] for c in existing_pool}

    ok_count = 0
    fail_count = 0
    new_entries = []

    total = len(candidates)
    for i, station in enumerate(candidates, 1):
        url = station.get("url_resolved") or station.get("url", "")
        name = station.get("name", "")[:40]
        cc = station.get("countrycode", "?")

        print(f"[{i:>3}/{total}] {name:<40} ({cc:2s}) ", end="", flush=True)

        ok, reason = preflight(url)

        if ok:
            ok_count += 1
            print("✓")
            entry = {
                "name": station.get("name", ""),
                "url": url,
                "country": station.get("country", ""),
                "countrycode": station.get("countrycode", ""),
                "language": station.get("language", ""),
                "tags": station.get("tags", ""),
                "status": "ok",
                "last_checked": today,
            }
            if recheck:
                for e in existing_pool:
                    if e["url"] == url:
                        e.update({"status": "ok", "last_checked": today})
                        break
            else:
                if url not in existing_urls:
                    new_entries.append(entry)
        else:
            fail_count += 1
            print(f"✗  {reason[:50]}")
            if recheck:
                for e in existing_pool:
                    if e["url"] == url:
                        e.update({"status": "fail", "last_checked": today, "fail_reason": reason})
                        break

    # Summary
    print(f"\n{'─'*70}")
    print(f"  Checked:  {total}")
    print(f"  OK:       {ok_count}")
    print(f"  Failed:   {fail_count}")

    if recheck:
        final_pool = [e for e in existing_pool if e.get("status") == "ok"]
        print(f"  Pool after recheck: {len(final_pool)} active")
        save_pool(final_pool)
    else:
        final_pool_raw = existing_pool + new_entries
        print(f"  New entries added: {len(new_entries)}")
        print(f"  Total pool size: {len(final_pool_raw)}")

        # Save all OK stations without regional quotas
        final_pool = [e for e in final_pool_raw if e.get("status") == "ok"]
        save_pool(final_pool)


def main():
    parser = argparse.ArgumentParser(description="LUMEN radio pool extractor")
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Recheck existing pool entries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show candidates without validation",
    )
    args = parser.parse_args()

    run(
        recheck=args.recheck,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

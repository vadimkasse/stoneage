#!/usr/bin/env python3
"""
LUMEN Camera Extractor

Fetches Virginia 511 camera API, validates HLS streams via ffmpeg preflight,
saves working cameras to camera_pool.json.

Usage:
    python lumen_cam_extractor.py                    # validate all active, no problem_stream
    python lumen_cam_extractor.py --max 50           # limit candidates to check
    python lumen_cam_extractor.py --jurisdiction Fairfax
    python lumen_cam_extractor.py --recheck          # recheck existing pool
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests

API_URL      = "https://511.vdot.virginia.gov/services/map/layers/map/cams"
POOL_PATH    = Path(__file__).parent.parent / "private" / "camera_pool.json"
PREFLIGHT_S  = 6      # seconds to probe
TIMEOUT_S    = 12     # ffmpeg wall-clock timeout


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Referer": "https://511.vdot.virginia.gov/",
    "Accept": "application/json, text/plain, */*",
}

def fetch_cameras(jurisdiction: str | None = None) -> list[dict]:
    """Fetch all cameras from VDOT API, return filtered list of candidates."""
    print("Fetching VDOT camera list…")
    resp = requests.get(API_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    if not resp.text.strip():
        print(f"  ERROR: Empty response from API (status {resp.status_code})")
        print(f"  Headers: {dict(resp.headers)}")
        sys.exit(1)
    data = resp.json()

    features = data.get("features", [])
    print(f"  Total features: {len(features)}")

    candidates = []
    for f in features:
        props = f.get("properties", {})
        url   = props.get("https_url", "")
        if not url or not url.endswith("playlist.m3u8"):
            continue
        if not props.get("active", False):
            continue
        if props.get("problem_stream", False):
            continue
        if jurisdiction and props.get("jurisdiction") != jurisdiction:
            continue
        coords = f.get("geometry", {}).get("coordinates", [None, None])
        candidates.append({
            "url":          url,
            "name":         props.get("name", ""),
            "description":  props.get("description", ""),
            "route":        props.get("route", ""),
            "jurisdiction": props.get("jurisdiction", ""),
            "direction":    props.get("direction", ""),
            "lon":          coords[0],
            "lat":          coords[1],
            "id":           props.get("id", ""),
        })

    print(f"  Candidates after filter: {len(candidates)}")
    return candidates


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
        # Extract last meaningful ffmpeg error line
        lines = [l.strip() for l in stderr.splitlines() if l.strip()]
        reason = lines[-1][:120] if lines else "unknown error"
        return False, reason
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)


def load_pool() -> list[dict]:
    if POOL_PATH.exists():
        return json.loads(POOL_PATH.read_text())
    return []


def save_pool(pool: list[dict]) -> None:
    POOL_PATH.write_text(json.dumps(pool, indent=2, ensure_ascii=False))
    print(f"\n✓ Saved {len(pool)} cameras → {POOL_PATH}")


def run(max_check: int | None, jurisdiction: str | None, recheck: bool) -> None:
    today = date.today().isoformat()

    if recheck:
        pool = load_pool()
        if not pool:
            print("Pool is empty, nothing to recheck.")
            return
        candidates = pool
        print(f"Rechecking {len(candidates)} existing pool entries…")
    else:
        candidates = fetch_cameras(jurisdiction)
        if max_check:
            candidates = candidates[:max_check]
            print(f"  Limited to first {max_check} candidates")

    existing_pool = load_pool() if not recheck else []
    existing_urls = {c["url"] for c in existing_pool}

    ok_count = 0
    fail_count = 0
    new_entries = []

    total = len(candidates)
    for i, cam in enumerate(candidates, 1):
        url = cam["url"]
        label = cam.get("description") or cam.get("name") or url
        print(f"[{i:>3}/{total}] {label[:55]:<55} ", end="", flush=True)

        ok, reason = preflight(url)
        status = "ok" if ok else "fail"

        if ok:
            ok_count += 1
            print("✓")
            entry = {**cam, "status": status, "last_checked": today}
            if recheck:
                # update existing entry
                for e in existing_pool:
                    if e["url"] == url:
                        e.update({"status": status, "last_checked": today})
                        break
            else:
                if url not in existing_urls:
                    new_entries.append(entry)
        else:
            fail_count += 1
            print(f"✗  {reason[:60]}")
            if recheck:
                for e in existing_pool:
                    if e["url"] == url:
                        e.update({"status": "fail", "last_checked": today, "fail_reason": reason})
                        break

    # Summary
    print(f"\n{'─'*60}")
    print(f"  Checked:  {total}")
    print(f"  OK:       {ok_count}")
    print(f"  Failed:   {fail_count}")

    if recheck:
        # Keep only ok entries
        final_pool = [e for e in existing_pool if e.get("status") == "ok"]
        print(f"  Pool after recheck: {len(final_pool)} active")
        save_pool(final_pool)
    else:
        final_pool = existing_pool + new_entries
        print(f"  New entries added: {len(new_entries)}")
        print(f"  Total pool size:   {len(final_pool)}")
        save_pool(final_pool)


def main():
    parser = argparse.ArgumentParser(description="LUMEN camera pool builder")
    parser.add_argument("--max",          type=int,  default=None,
                        help="Max cameras to check (default: all)")
    parser.add_argument("--jurisdiction", type=str,  default=None,
                        help="Filter by jurisdiction, e.g. 'Fairfax'")
    parser.add_argument("--recheck",      action="store_true",
                        help="Recheck existing pool entries")
    args = parser.parse_args()

    run(
        max_check=args.max,
        jurisdiction=args.jurisdiction,
        recheck=args.recheck,
    )


if __name__ == "__main__":
    main()

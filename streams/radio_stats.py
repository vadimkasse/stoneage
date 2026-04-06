#!/usr/bin/env python3
"""
LUMEN Radio Pool Stats

One-off script to analyze radio_pool.json and display statistics:
- Station count by region
- Top 20 countries by station count
- Top 10 stations per region (by clickcount or alphabetically)

Usage:
    python3 streams/radio_stats.py
"""

import json
from collections import defaultdict
from pathlib import Path

POOL_PATH = Path(__file__).parent.parent / "private" / "radio_pool.json"

# Region mapping for statistics only (not used in validation)
REGION_COUNTRIES = {
    "europe": {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "GB", "NO", "IS",
    },
    "asia": {
        "JP", "KR", "CN", "IN", "TH", "MY", "SG", "PH", "ID", "VN",
        "BD", "PK", "LK", "TW", "HK", "MO", "MM", "KH", "LA",
    },
    "mena": {
        "EG", "SA", "AE", "IL", "IR", "IQ", "JO", "LB", "OM", "QA",
        "KW", "BH", "YE", "MA", "TN", "DZ", "LY", "SD", "ZA", "NG",
        "GH", "KE", "TZ", "ET", "UG",
    },
    "latam": {
        "MX", "BR", "AR", "CO", "PE", "CL", "VE", "EC", "BO", "PY",
        "UY", "GT", "HN", "SV", "NI", "CR", "PA", "CU", "DO",
    },
}


def country_to_region(countrycode: str) -> str:
    """Map country code to region."""
    if not countrycode:
        return "other"
    cc = countrycode.upper()
    for region, countries in REGION_COUNTRIES.items():
        if cc in countries:
            return region
    return "other"


def main():
    if not POOL_PATH.exists():
        print(f"ERROR: {POOL_PATH} not found")
        return

    try:
        pool = json.loads(POOL_PATH.read_text())
    except Exception as e:
        print(f"ERROR reading {POOL_PATH}: {e}")
        return

    if not pool:
        print("Pool is empty.")
        return

    print(f"Total stations: {len(pool)}\n")

    # ── By Region ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("STATIONS BY REGION")
    print("=" * 60)

    by_region = defaultdict(list)
    for station in pool:
        region = country_to_region(station.get("countrycode", ""))
        by_region[region].append(station)

    region_order = ["europe", "asia", "mena", "latam", "other"]
    for region in region_order:
        count = len(by_region[region])
        pct = 100 * count / len(pool)
        print(f"  {region:8s}: {count:3d} ({pct:5.1f}%)")

    # ── By Country (Top 20) ─────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TOP 20 COUNTRIES BY STATION COUNT")
    print("=" * 60)

    by_country = defaultdict(int)
    for station in pool:
        cc = station.get("countrycode", "")
        if cc:
            by_country[cc] += 1

    sorted_countries = sorted(by_country.items(), key=lambda x: x[1], reverse=True)[:20]
    for i, (cc, count) in enumerate(sorted_countries, 1):
        pct = 100 * count / len(pool)
        print(f"  {i:2d}. {cc:2s}: {count:3d} ({pct:5.1f}%)")

    # ── Top 10 per Region ───────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("TOP 10 STATIONS PER REGION")
    print("=" * 60)

    for region in region_order:
        stations = by_region[region]
        if not stations:
            continue

        print(f"\n{region.upper()} ({len(stations)} stations):")
        print("─" * 58)

        # Sort by clickcount (descending) if available, else by name
        has_clickcount = any(s.get("clickcount") is not None for s in stations)

        if has_clickcount:
            sorted_stations = sorted(
                stations,
                key=lambda s: (s.get("clickcount") or 0),
                reverse=True,
            )[:10]
            for i, station in enumerate(sorted_stations, 1):
                name = station.get("name", "N/A")[:40]
                cc = station.get("countrycode", "?")
                clicks = station.get("clickcount", 0) or 0
                print(f"  {i:2d}. {name:40s} ({cc:2s}) — {clicks:6d} clicks")
        else:
            sorted_stations = sorted(
                stations,
                key=lambda s: s.get("name", "").lower(),
            )[:10]
            for i, station in enumerate(sorted_stations, 1):
                name = station.get("name", "N/A")[:40]
                cc = station.get("countrycode", "?")
                print(f"  {i:2d}. {name:40s} ({cc:2s})")


if __name__ == "__main__":
    main()

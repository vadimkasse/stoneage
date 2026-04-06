#!/usr/bin/env python3
"""
Generate camera catalog CSV from camera_pool.json.
Usage: python streams/make_camera_catalog.py
Output: camera_catalog.csv in private folder
"""

import csv
import json
import re
from datetime import date
from pathlib import Path

POOL_PATH = Path(__file__).parent.parent / "private" / "camera_pool.json"
CSV_PATH  = Path(__file__).parent.parent / "private" / "camera_catalog.csv"


def route_to_code(route: str) -> str:
    """I-66 → I66, Rt-28 → RT28, Dale Blvd → DAL"""
    if not route:
        return "UNK"
    r = route.strip()
    m = re.match(r'^(I|RT|Rt|US|VA|SR)[.\-\s]*(\d+)', r, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    first = re.split(r'[\s\-\./&,]', r)[0]
    return first[:3].upper()


def run():
    pool = json.loads(POOL_PATH.read_text())
    ok   = [c for c in pool if c.get("status") == "ok"]
    rows = sorted(ok, key=lambda x: (x.get("route", ""), x.get("description", "")))

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Name", "Route", "Route Code", "Description",
                         "Direction", "Jurisdiction", "Lat", "Lon", "URL"])
        for c in rows:
            writer.writerow([
                c.get("id", ""),
                c.get("name", ""),
                c.get("route", ""),
                route_to_code(c.get("route", "")),
                c.get("description", "").strip(),
                c.get("direction", ""),
                c.get("jurisdiction", ""),
                c.get("lat", ""),
                c.get("lon", ""),
                c.get("url", ""),
            ])

    print(f"✓ CSV → {CSV_PATH.name}  ({len(ok)} cameras)")

    by_route = {}
    for c in ok:
        r = c.get("route") or "Other"
        by_route[r] = by_route.get(r, 0) + 1
    print(f"\nRoutes ({len(by_route)} total):")
    for route, count in sorted(by_route.items()):
        print(f"  {route:<25} → {route_to_code(route):<10} {count} cameras")


if __name__ == "__main__":
    run()

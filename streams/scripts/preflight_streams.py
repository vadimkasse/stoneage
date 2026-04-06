#!/usr/bin/env python3
"""
Preflight validation - quick start test only.
"""

import subprocess
import csv
import sys
from pathlib import Path

STREAMS = [
    "https://streaming.iowadot.gov/atms_mcast/cam-801.stream/playlist.m3u8",
    "https://streaming.iowadot.gov/atms_mcast/cam-802.stream/playlist.m3u8",
    "https://streaming.iowadot.gov/atms_mcast/cam-803.stream/playlist.m3u8",
    "https://streaming.iowadot.gov/atms_mcast/cam-804.stream/playlist.m3u8",
    "https://streaming.iowadot.gov/atms_mcast/cam-805.stream/playlist.m3u8",
    "https://cwwp2.dot.ca.gov/data/d07/cctv/iphone/cctv511.m3u8",
    "https://cwwp2.dot.ca.gov/data/d07/cctv/iphone/cctv518.m3u8",
    "https://cwwp2.dot.ca.gov/data/d11/cctv/iphone/cctv023.m3u8",
    "https://cwwp2.dot.ca.gov/data/d11/cctv/iphone/cctv045.m3u8",
    "https://cwwp2.dot.ca.gov/data/d03/cctv/iphone/cctv152.m3u8",
    "https://video.dot.wa.gov/live/00004.m3u8",
    "https://video.dot.wa.gov/live/00005.m3u8",
    "https://video.dot.wa.gov/live/00006.m3u8",
    "https://video.dot.wa.gov/live/00007.m3u8",
    "https://video.dot.wa.gov/live/00008.m3u8",
    "http://webcam01.ecn.purdue.edu/mjpg/video.mjpg",
    "http://webcam02.ecn.purdue.edu/mjpg/video.mjpg",
    "http://pendelcam.kip.uni-heidelberg.de/mjpg/video.mjpg",
    "http://axis-00408b.webcam-server.net/mjpg/video.mjpg",
    "http://195.243.185.195/axis-cgi/mjpg/video.cgi",
]

WORK_DIR = Path(__file__).parent.parent / "validated"
RESULTS_CSV = WORK_DIR / "preflight_results.csv"


def normalize_error_hint(stderr_text):
    """Normalize ffmpeg error."""
    stderr_lower = stderr_text.lower()

    if "failed to resolve hostname" in stderr_lower or "name or service not known" in stderr_lower:
        return "dns"
    if "403" in stderr_lower or "forbidden" in stderr_lower:
        return "http_403"
    if "404" in stderr_lower or "not found" in stderr_lower:
        return "http_404"
    if "timed out" in stderr_lower or "timeout" in stderr_lower:
        return "timeout"
    if "ssl" in stderr_lower or "tls" in stderr_lower or "certificate" in stderr_lower:
        return "tls"
    if "connection refused" in stderr_lower or "connection reset" in stderr_lower or \
       "input/output error" in stderr_lower or "network unreachable" in stderr_lower or \
       "host unreachable" in stderr_lower or "no route to host" in stderr_lower:
        return "connection"
    if "protocol" in stderr_lower or "demuxer" in stderr_lower or "invalid data" in stderr_lower or \
       "unsupported" in stderr_lower or "unknown format" in stderr_lower:
        return "protocol"

    return "unknown"


def test_stream(url):
    """Test stream connectivity. Returns (status, error_hint)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", "5", "-i", url, "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=15,
            text=True,
        )
        if result.returncode == 0:
            return "success", ""
        else:
            error_hint = normalize_error_hint(result.stderr)
            return "fail", error_hint
    except subprocess.TimeoutExpired:
        return "fail", "timeout"
    except Exception:
        return "fail", "unknown"


def main():
    """Run preflight for all streams."""
    results = []

    for i, url in enumerate(STREAMS, 1):
        print(f"[{i}/{len(STREAMS)}] {url[:60]}...", file=sys.stderr)
        status, error_hint = test_stream(url)
        results.append({"url": url, "status": status, "error_hint": error_hint})

    # Write CSV
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "status", "error_hint"],
        )
        writer.writeheader()
        writer.writerows(results)

    # Print summary
    success = sum(1 for r in results if r["status"] == "success")
    fail = sum(1 for r in results if r["status"] == "fail")

    print(f"\nSuccess: {success}", file=sys.stderr)
    print(f"Fail: {fail}", file=sys.stderr)


if __name__ == "__main__":
    main()

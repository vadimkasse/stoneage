#!/usr/bin/env python3
"""
Validate live video streams - capture frames, measure diff and brightness, classify tiers.
"""

import subprocess
import csv
import os
import sys
import time
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("Error: PIL and numpy required. Install with: pip install pillow numpy")
    sys.exit(1)

# List of streams to validate
STREAMS = [
    "https://streaming.iowadot.gov/atms_mcast/cam-803.stream/playlist.m3u8",
    "https://streaming.iowadot.gov/atms_mcast/cam-401.stream/playlist.m3u8",
    "https://cwwp2.dot.ca.gov/data/d11/cctv/iphone/cctv001.m3u8",
    "https://cwwp2.dot.ca.gov/data/d07/cctv/iphone/cctv556.m3u8",
    "https://cotrip.org/device/assets/cctv/I-70_at_Eisenhower_Tunnel_West_Portal_70014.m3u8",
    "https://cotrip.org/device/assets/cctv/I-25_at_17th_St_15160.m3u8",
    "http://vss2live.dot.ga.gov:80/lo/gdot-cam-001.stream/playlist.m3u8",
    "http://vss2live.dot.ga.gov:80/lo/gdot-cam-128.stream/playlist.m3u8",
    "https://m3u8.ncdot.gov/i77_Trade_St.m3u8",
    "https://live.portofhelsinki.fi/hls/west_harbour.m3u8",
]

WORK_DIR = Path(__file__).parent.parent / "validated"
RESULTS_CSV = WORK_DIR / "results.csv"


def normalize_error_hint(stderr_text):
    """
    Normalize ffmpeg error to one of: dns, timeout, http_403, http_404, tls, connection, protocol, unknown.
    """
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


def run_ffmpeg_test(url, duration=5):
    """
    Run ffmpeg connectivity test.
    Returns tuple (success: bool, error_hint: str).
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", str(duration), "-i", url, "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=duration + 10,
            text=True,
        )
        if result.returncode == 0:
            return True, ""
        else:
            error_hint = normalize_error_hint(result.stderr)
            return False, error_hint
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception:
        return False, "unknown"


def capture_frame(url, output_file):
    """
    Capture a single frame from the stream.
    Returns True if success, False if fail.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", url, "-frames:v", "1", str(output_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return result.returncode == 0 and Path(output_file).exists()
    except Exception:
        return False


def compute_diff(img1_path, img2_path):
    """
    Compute mean absolute difference between two images (grayscale).
    Normalized to 0-100 scale.
    Returns float or 'NaN' if computation failed.
    """
    try:
        img1 = Image.open(img1_path).convert("L")
        img2 = Image.open(img2_path).convert("L")

        # Resize to same dimensions if needed
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.LANCZOS)

        arr1 = np.array(img1, dtype=np.float32)
        arr2 = np.array(img2, dtype=np.float32)

        diff = np.mean(np.abs(arr1 - arr2))
        # Normalize from 0-255 to 0-100
        normalized = (diff / 255.0) * 100.0
        return round(normalized, 1)
    except Exception:
        return "NaN"


def compute_brightness(img_path):
    """
    Compute mean brightness of image (grayscale).
    Returns float 0-255 or 'NaN' if computation failed.
    """
    try:
        img = Image.open(img_path).convert("L")
        arr = np.array(img, dtype=np.float32)
        brightness = np.mean(arr)
        return round(brightness, 1)
    except Exception:
        return "NaN"


def classify_tier(status, reconnect, diff, brightness):
    """Classify stream tier based on metrics."""
    if status == "fail":
        return 3
    if reconnect == "no":
        return 2

    # Convert to float for comparison
    try:
        diff_val = float(diff)
        if diff_val < 2:
            return 2
    except (ValueError, TypeError):
        pass

    try:
        bright_val = float(brightness)
        if bright_val < 15:
            return 2
    except (ValueError, TypeError):
        pass

    return 1


def validate_stream(url):
    """
    Validate a single stream.
    Returns dict with metrics.
    """
    result = {
        "url": url,
        "status": "fail",
        "diff": "NaN",
        "brightness": "NaN",
        "reconnect": "no",
        "tier": 3,
        "error_hint": "",
    }

    # Step A: Start test
    success, error_hint = run_ffmpeg_test(url, duration=5)
    if not success:
        result["error_hint"] = error_hint
        return result

    result["status"] = "success"

    # Step B: Capture frame t0
    t0_path = WORK_DIR / "t0.jpg"
    if not capture_frame(url, t0_path):
        t0_path.unlink(missing_ok=True)
        result["tier"] = 3
        result["error_hint"] = "frame_capture"
        return result

    # Step C: Wait 120 seconds
    time.sleep(120)

    # Step D: Capture frame t1
    t1_path = WORK_DIR / "t1.jpg"
    if not capture_frame(url, t1_path):
        t0_path.unlink(missing_ok=True)
        t1_path.unlink(missing_ok=True)
        result["tier"] = 3
        result["error_hint"] = "frame_capture"
        return result

    # Step E: Compute diff
    diff_val = compute_diff(t0_path, t1_path)
    result["diff"] = diff_val

    # Step F: Compute brightness
    brightness_val = compute_brightness(t1_path)
    result["brightness"] = brightness_val

    # Clean up frames
    t0_path.unlink(missing_ok=True)
    t1_path.unlink(missing_ok=True)

    # Step G: Reconnect test
    success, reconnect_error = run_ffmpeg_test(url, duration=5)
    if success:
        result["reconnect"] = "yes"
    else:
        result["reconnect"] = "no"
        result["error_hint"] = reconnect_error

    # Classify tier
    result["tier"] = classify_tier(
        result["status"],
        result["reconnect"],
        result["diff"],
        result["brightness"]
    )

    return result


def main():
    """Run validation for all streams."""
    results = []

    for i, url in enumerate(STREAMS, 1):
        print(f"[{i}/{len(STREAMS)}] Validating {url[:60]}...", file=sys.stderr)
        row = validate_stream(url)
        results.append(row)

        # Pause between streams to avoid rate limiting
        if i < len(STREAMS):
            time.sleep(10)

    # Write CSV
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "status", "diff", "brightness", "reconnect", "tier", "error_hint"],
        )
        writer.writeheader()
        writer.writerows(results)

    # Print summary
    tier1 = sum(1 for r in results if r["tier"] == 1)
    tier2 = sum(1 for r in results if r["tier"] == 2)
    tier3 = sum(1 for r in results if r["tier"] == 3)

    # Count error hints
    error_counts = {}
    for r in results:
        hint = r.get("error_hint", "")
        if hint:
            error_counts[hint] = error_counts.get(hint, 0) + 1

    print(f"\nTotal URLs: {len(results)}", file=sys.stderr)
    print(f"Tier 1: {tier1}", file=sys.stderr)
    print(f"Tier 2: {tier2}", file=sys.stderr)
    print(f"Tier 3: {tier3}", file=sys.stderr)

    if error_counts:
        print(f"\nError hints:", file=sys.stderr)
        print(f"  dns: {error_counts.get('dns', 0)}", file=sys.stderr)
        print(f"  http_403: {error_counts.get('http_403', 0)}", file=sys.stderr)
        print(f"  http_404: {error_counts.get('http_404', 0)}", file=sys.stderr)
        print(f"  timeout: {error_counts.get('timeout', 0)}", file=sys.stderr)
        print(f"  connection: {error_counts.get('connection', 0)}", file=sys.stderr)
        print(f"  protocol: {error_counts.get('protocol', 0)}", file=sys.stderr)
        print(f"  unknown: {error_counts.get('unknown', 0)}", file=sys.stderr)

    print(f"\nResults saved to: {RESULTS_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()

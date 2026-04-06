#!/usr/bin/env python3
"""Probe actual resolution of a camera stream."""
import subprocess, json, sys

url = sys.argv[1] if len(sys.argv) > 1 else "https://media-sfs8.vdotcameras.com:443/rtplive/NROCCTVI66E00501/playlist.m3u8"

result = subprocess.run([
    "ffprobe", "-v", "quiet",
    "-print_format", "json",
    "-show_streams",
    url
], capture_output=True, timeout=15)

data = json.loads(result.stdout)
for s in data.get("streams", []):
    if s.get("codec_type") == "video":
        w = s.get("width")
        h = s.get("height")
        print(f"Resolution: {w} x {h}")
        print(f"Aspect ratio: {w/h:.3f}")
        print(f"After crop 160px top: {w} x {h-160}")
        print(f"After crop 80px bottom too: {w} x {h-240}")

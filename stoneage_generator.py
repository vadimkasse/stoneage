#!/usr/bin/env python3
"""
STONEAGE Track Generator

Generates one daily track:

  highway ambience (5s/59s segment from random offset)
  + radio recording (live stream)
  + video from VDOT traffic camera (muxed into final .mp4)

Rules:

- samples are taken from samples/static
- random start point in ambience sample
- ambience and radio mixed at 0 dB, then mastering: normalize to −3 dB peak + Limiter(threshold_db=−1.0)
- video is recorded from a random camera in camera_catalog.csv (with retry up to 5 attempts)
- final output is .mp4 (video + audio muxed) with subtitle overlay
- market data: Brent Oil (yfinance) and VA Gas Prices (AAA scrape via cloudscraper)
"""

import csv
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from pedalboard import Pedalboard, Limiter
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont

try:
    import requests
except ImportError:
    requests = None

try:
    import boto3
except ImportError:
    boto3 = None

try:
    import torch
    from silero_vad import load_silero_vad
except ImportError:
    torch = None
    load_silero_vad = None

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

SAMPLES_DIR      = Path(__file__).parent / "samples" / "static"
OUTPUT_DIR       = Path(__file__).parent / "output"
CAMERA_CATALOG   = Path(__file__).parent / "private" / "camera_catalog.csv"
RADIO_CATALOG    = Path(__file__).parent / "radio_catalog.csv"
FONT_PATH        = Path(__file__).parent / "HomeVideo-Bold.ttf"

SR               = 44100
DURATION_MS      = 5_000              # Debug mode: 5s (Standard: 59000)
RADIO_URL        = "https://npr-ice.streamguys1.com/live.mp3"  # fallback
RADIO_NAME       = "NPR_ICE"          # fallback name
RADIO_LEVEL_DB   = -3                 # radio volume in mix (relative to ambience at 0 dB)

VIDEO_TIMEOUT    = 60                # max seconds to wait for video recording

# Radio content validation (loudness + speech check)
MIN_DBFS         = -32               # minimum loudness (dBFS)
MIN_SPEECH_RATIO = 0.65              # minimum speech ratio (0-1)
RADIO_VALIDATE_S = 15                # seconds to record for validation

# Day names for subtitle (Monday → MON, Tuesday → THE, etc.)
DAY_NAMES      = ["MON", "THE", "WED", "THU", "FRI", "SAT", "SUN"]


# ── Market Data Engines ──────────────────────────────────────────────────────

def get_brent_price() -> tuple[float, float]:
    """Fetch Brent Crude Oil price (BZ=F) via yfinance. Returns (current, prev_close)."""
    if not yf:
        print("  [market error] yfinance not installed")
        return 82.50, 81.90
    try:
        ticker = yf.Ticker("BZ=F")
        info = ticker.fast_info
        current = info.last_price
        prev_close = info.previous_close
        if current is None or prev_close is None:
            return 82.50, 81.90
        return current, prev_close
    except Exception as e:
        print(f"  [market error] Brent Oil fetch failed: {e}")
        return 82.50, 81.90  # Absolute safety fallback


def get_va_gas_price() -> tuple[float, float]:
    """Calculate gas prices using RB=F + 0.95 formula."""
    try:
        ticker = yf.Ticker("RB=F")
        info = ticker.fast_info
        current = info.last_price
        prev = info.previous_close
        if current is not None and prev is not None:
             current += 0.95
             prev += 0.95
             print(f"Found Gas Price (Formula): {current:.3f}")
             return current, prev
    except Exception as e:
        print(f"Gas price calculation failed: {e}")

    return 3.55, 3.52  # Absolute safety fallback


# ── Audio helpers ──────────────────────────────────────────────────────────────

def load_seg(path: Path) -> AudioSegment:
    """Load audio file, normalise to stereo 44100 Hz 16-bit."""
    seg = AudioSegment.from_file(str(path))
    return seg.set_channels(2).set_frame_rate(SR).set_sample_width(2)


def loop_to(seg: AudioSegment, target_ms: int, src_path: Path) -> AudioSegment:
    """Repeat seg until target_ms, then cut."""
    if len(seg) == 0:
        raise RuntimeError(f"Empty segment: {src_path}")
    reps = math.ceil(target_ms / len(seg))
    return (seg * reps)[:target_ms]


# ── Radio helpers ──────────────────────────────────────────────────────────────

def record_radio(url: str, out_wav: Path, duration_ms: int, station_name: str = "") -> bool:
    """Record duration_ms from radio stream via ffmpeg."""
    duration_s = duration_ms / 1000.0
    station_label = f" ({station_name})" if station_name else ""
    print(f"  Recording radio{station_label} ({duration_s:.1f}s)…")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", url,
                "-t", f"{duration_s:.3f}",
                "-ar", str(SR), "-ac", "2",
                "-map", "0:a:0",
                "-vn", "-sn",
                str(out_wav),
            ],
            timeout=int(duration_s) + 20,
            capture_output=True,
        )
        if result.returncode == 0 and out_wav.exists():
            return True
        stderr_msg = result.stderr.decode(errors="ignore")[:500]
        print(f"  [radio error] {stderr_msg}")
        return False
    except subprocess.TimeoutExpired as e:
        stderr_msg = e.stderr.decode(errors="ignore")[:500] if e.stderr else ""
        print(f"  [radio error] timeout: {stderr_msg}")
        return False
    except Exception as e:
        print(f"  [radio error] {e}")
        return False


def preflight(url: str) -> tuple[bool, str]:
    """Quick check: can ffmpeg connect to stream? Returns (ok, reason)."""
    cmd = [
        "ffmpeg",
        "-rw_timeout", "5000000",
        "-i", url,
        "-t", "2",
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, timeout=10, capture_output=True)
        if result.returncode == 0:
            return True, "ok"
        stderr = result.stderr.decode(errors="ignore")
        lines = [l.strip() for l in stderr.splitlines() if l.strip()]
        reason = lines[-1][:50] if lines else "unavailable"
        return False, reason
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:40]


def validate_radio_content(url: str) -> tuple[bool, str]:
    """
    Validate radio stream content: loudness and speech ratio.
    Records RADIO_VALIDATE_S seconds, checks:
    1. Loudness (dBFS) — must be >= MIN_DBFS
    2. Speech ratio via Silero VAD — must be >= MIN_SPEECH_RATIO
    Returns (ok, reason).
    """
    print(f"  [validate] Checking stream (VAD available: {bool(load_silero_vad)})")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Record RADIO_VALIDATE_S seconds
        cmd = [
            "ffmpeg", "-y",
            "-rw_timeout", "10000000",
            "-i", url,
            "-t", str(RADIO_VALIDATE_S),
            "-ar", "16000",
            "-ac", "1",
            "-map", "0:a:0",
            "-vn", "-sn",
            str(tmp_path),
        ]

        result = subprocess.run(cmd, timeout=RADIO_VALIDATE_S + 10, capture_output=True)
        if result.returncode != 0 or not tmp_path.exists():
            return False, "record failed"

        # Check loudness
        try:
            audio = AudioSegment.from_wav(str(tmp_path))
            lufs = audio.dBFS
            if lufs < MIN_DBFS:
                return False, f"quiet ({lufs:.0f} < {MIN_DBFS})"
        except Exception:
            return False, "loudness check failed"

        # Check speech ratio (if VAD available)
        if load_silero_vad:
            try:
                vad_model = load_silero_vad()
                audio_array = np.array(audio.get_array_of_samples(), dtype=np.float32)
                audio_array = audio_array / (2 ** (8 * audio.sample_width - 1))

                chunk_size = 512   # Silero VAD requires exactly 512 samples at 16kHz
                speech_frames = 0
                total_chunks = 0

                for i in range(0, len(audio_array), chunk_size):
                    chunk = audio_array[i:i + chunk_size]
                    if len(chunk) < chunk_size:
                        chunk = np.pad(chunk, (0, chunk_size - len(chunk)))

                    total_chunks += 1
                    try:
                        speech_prob = vad_model(torch.from_numpy(chunk).unsqueeze(0), 16000).item()
                        if speech_prob > 0.5:
                            speech_frames += 1
                    except Exception as e:
                        print(f"  [VAD chunk error] {e}")
                        raise  # Re-raise to be caught by outer except

                speech_ratio = speech_frames / total_chunks if total_chunks > 0 else 0
                print(f"  [VAD] speech_ratio: {speech_ratio:.1%} (threshold: {MIN_SPEECH_RATIO:.0%})")

                if speech_ratio < MIN_SPEECH_RATIO:
                    return False, f"low speech ({speech_ratio:.0%} < {MIN_SPEECH_RATIO:.0%})"
            except Exception as e:
                print(f"  [VAD error] Silero VAD failed: {e}")
                return False, f"VAD validation failed"

        return True, "ok"

    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, f"validate error: {str(e)[:20]}"
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


# ── Camera ─────────────────────────────────────────────────────────────────────

def load_camera_pool() -> list[dict]:
    """Load camera pool from camera_catalog.csv."""
    if not CAMERA_CATALOG.exists():
        return []
    try:
        cameras = []
        with open(CAMERA_CATALOG, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cameras.append({
                    "id": row.get("ID"),
                    "name": row.get("Name"),
                    "route": row.get("Route"),
                    "route_code": row.get("Route Code"),
                    "description": row.get("Description"),
                    "jurisdiction": row.get("Jurisdiction"),
                    "url": row.get("URL"),
                })
        return cameras
    except Exception:
        return []


def pick_camera(rng: random.Random) -> dict | None:
    """Pick a random camera from the pool."""
    pool = load_camera_pool()
    if not pool:
        print("  [camera] pool empty or not found — skipping video")
        return None
    return rng.choice(pool)


# ── Radio ──────────────────────────────────────────────────────────────────────

def load_radio_filters() -> tuple[set, set, set, set]:
    """Load include/exclude filters from radio_tags.md.

    Returns: (include_countries, include_languages, exclude_countries, exclude_languages)
    """
    include_countries = set()
    include_languages = set()
    exclude_countries = set()
    exclude_languages = set()

    tags_config = Path(__file__).parent / "streams" / "radio_tags.md"
    if not tags_config.exists():
        return include_countries, include_languages, exclude_countries, exclude_languages

    try:
        content = tags_config.read_text()

        # Extract include_countries
        if "## include_countries" in content:
            section = content.split("## include_countries")[1]
            if "##" in section[1:]:
                section = section[:section.index("##", 1)]
            for line in section.split("\n"):
                if "|" in line and not line.strip().startswith("#"):
                    tags = set(t.strip().upper() for t in line.split("|") if t.strip())
                    include_countries.update(tags)
                    break

        # Extract include_languages
        if "## include_languages" in content:
            section = content.split("## include_languages")[1]
            if "##" in section[1:]:
                section = section[:section.index("##", 1)]
            for line in section.split("\n"):
                if "|" in line and not line.strip().lower().startswith("#"):
                    tags = set(t.strip().lower() for t in line.split("|") if t.strip())
                    include_languages.update(tags)
                    break

        # Extract exclude_countries
        if "## exclude_countries" in content:
            section = content.split("## exclude_countries")[1]
            if "##" in section[1:]:
                section = section[:section.index("##", 1)]
            for line in section.split("\n"):
                if "|" in line and not line.strip().startswith("#"):
                    tags = set(t.strip().upper() for t in line.split("|") if t.strip())
                    exclude_countries.update(tags)
                    break

        # Extract exclude_languages
        if "## exclude_languages" in content:
            section = content.split("## exclude_languages")[1]
            if "##" in section[1:]:
                section = section[:section.index("##", 1)]
            for line in section.split("\n"):
                if "|" in line and not line.strip().lower().startswith("#"):
                    tags = set(t.strip().lower() for t in line.split("|") if t.strip())
                    exclude_languages.update(tags)
                    break
    except Exception as e:
        print(f"  [filter] error loading radio filters: {e}")

    return include_countries, include_languages, exclude_countries, exclude_languages


def load_radio_pool() -> list[dict]:
    """Load radio station pool from radio_catalog.csv with flexible field names and include/exclude filtering."""
    if not RADIO_CATALOG.exists():
        return []

    # Load include/exclude filters
    include_countries, include_languages, exclude_countries, exclude_languages = load_radio_filters()

    try:
        stations = []
        with open(RADIO_CATALOG, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue

                # Support various field name formats (case-insensitive and underscores)
                def get_field(row, *keys):
                    """Try to get field by multiple key variations (case-insensitive)."""
                    for key in keys:
                        if key in row:
                            return row[key]
                        # Try lowercase
                        for col in row.keys():
                            if col.lower() == key.lower():
                                return row[col]
                    return ""

                name = get_field(row, "name", "Name").strip()
                url = get_field(row, "url", "URL").strip()
                country = get_field(row, "country", "Country").strip()
                countrycode = get_field(row, "countrycode", "country_code", "Country Code").strip().upper()
                language = get_field(row, "language", "Language").strip()
                tags = get_field(row, "tags", "Tags").strip()

                # Validate required fields
                if not name:
                    continue
                if not url:
                    continue

                # Filter by included countries (whitelist)
                if include_countries:
                    if not countrycode or countrycode not in include_countries:
                        continue

                # Filter by excluded countries (blacklist)
                if exclude_countries:
                    if countrycode and countrycode in exclude_countries:
                        continue

                # Filter by included languages (whitelist)
                if include_languages:
                    if not language:
                        continue
                    language_lower = language.lower()
                    is_included = False
                    for include_lang in include_languages:
                        if include_lang in language_lower:
                            is_included = True
                            break
                    if not is_included:
                        continue

                # Filter by excluded languages (blacklist)
                if exclude_languages:
                    if language:
                        language_lower = language.lower()
                        is_excluded = False
                        for exclude_lang in exclude_languages:
                            if exclude_lang in language_lower:
                                is_excluded = True
                                break
                        if is_excluded:
                            continue

                stations.append({
                    "name": name,
                    "url": url,
                    "country": country,
                    "countrycode": countrycode if countrycode else "XX",
                    "language": language,
                    "tags": tags,
                })
        return stations
    except Exception as e:
        print(f"  [radio_pool] error loading: {e}")
        return []


def pick_radio(rng: random.Random) -> dict | None:
    """Pick a random radio station from the pool. Returns None + uses fallback if pool empty."""
    pool = load_radio_pool()
    if not pool:
        return None
    return rng.choice(pool)


def build_subtitle(camera: dict, day: date) -> tuple[str, str]:
    """
    Build subtitle code (Legacy part for webhook).
    Example: "VA64103MON"
    """
    if not camera:
        return ("", "")

    route_code = camera.get("route_code", "").strip()
    cam_id = str(camera.get("id", "")).strip()

    # Last 2 digits of camera ID
    cam_id_suffix = cam_id[-2:] if len(cam_id) >= 2 else cam_id.zfill(2)

    # Day of week abbreviation (0=Monday)
    day_abbr = DAY_NAMES[day.weekday()]

    code = f"{route_code}{cam_id_suffix}{day_abbr}"
    return code


def record_video(url: str, out_mp4: Path, duration_ms: int) -> bool:
    """Record duration_ms of video from HLS stream via ffmpeg."""
    duration_s = duration_ms / 1000.0
    print(f"  Recording video ({duration_s:.1f}s)…")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-rw_timeout", "10000000",   # 10s connect timeout
                "-i", url,
                "-t", f"{duration_s:.3f}",
                "-vcodec", "copy",           # no re-encode, just copy stream
                "-an",                       # no audio from camera
                str(out_mp4),
            ],
            timeout=VIDEO_TIMEOUT,
            capture_output=True,
        )
        if result.returncode == 0 and out_mp4.exists() and out_mp4.stat().st_size > 1000:
            return True
        stderr_msg = result.stderr.decode(errors="ignore")[-300:]
        print(f"  [video error] {stderr_msg}")
        return False
    except subprocess.TimeoutExpired:
        print("  [video error] timeout")
        return False
    except Exception as e:
        print(f"  [video error] {e}")
        return False


def create_subtitle_overlay(lines: list[dict], width: int, height: int) -> Path | None:
    """
    Create a transparent PNG with GTA Retro HUD style subtitles.
    Top-aligned, centered horizontally. Black 3px stroke (outline).
    No background plates or drop shadows.
    """
    try:
        # Create transparent image
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Load font
        font_size = 90
        try:
            font = ImageFont.truetype(str(FONT_PATH), font_size)
        except Exception:
            font = ImageFont.load_default()

        # Calculate heights and spacing
        line_spacing = 15
        line_data = []
        for item in lines:
            text = item.get("text", "")
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            line_data.append({"text": text, "bbox": bbox, "w": w, "h": h, "color": item.get("color", "#FFFFFF")})

        # Calculate total height for vertical centering
        total_text_height = sum(d["h"] for d in line_data) + (len(lines) - 1) * line_spacing
        current_y = (height - total_text_height) // 2

        # Draw each line's text with outline
        for data in line_data:
            text = data["text"]
            text_color_hex = data["color"].lstrip('#')
            text_rgb = tuple(int(text_color_hex[i:i+2], 16) for i in (0, 2, 4))
            
            w, h = data["w"], data["h"]
            # Center horizontally
            x = (width - w) // 2
            
            # Draw text with black pixel outline (stroke)
            # stroke_width=3 for GTA Retro look
            draw.text((x, current_y), text, font=font, fill=text_rgb + (255,),
                      stroke_width=3, stroke_fill=(0, 0, 0, 255))
            
            current_y += h + line_spacing

        # Save to temp file
        temp_png = Path(tempfile.gettempdir()) / f"subtitle_{id(img)}.png"
        img.save(str(temp_png), "PNG")
        print("GTA Retro UI Style applied with pixel outline.")
        return temp_png
    except Exception as e:
        print(f"  [subtitle error] {e}")
        return None


def mux_audio_video(audio_wav: Path, video_mp4: Path, out_mp4: Path,
                    duration_ms: int, subtitle_lines: list[dict] = None) -> bool:
    """
    Mux audio WAV + video MP4 into final MP4.
    Video is scaled to 1280x960 and cropped to 1280x850 (from copy.py).
    Then pixelated to 128x85 and back.
    Subtitle is overlaid HUD-style at the top.
    """
    duration_s = duration_ms / 1000.0
    print(f"  Muxing audio + video…")
    
    # Target dimensions from original stoneage processing
    target_w, target_h = 1280, 850

    subtitle_png = None
    cmd_inputs = [
        "ffmpeg", "-y",
        "-i", str(video_mp4),
        "-an",
    ]

    # Pipeline: 
    # 1. Scale and Crop (from copy.py)
    # 2. No Pixelation (clean render)
    pixel_filter = "scale=1280:960,crop=1280:850:0:130"

    if subtitle_lines:
        subtitle_png = create_subtitle_overlay(subtitle_lines, target_w, target_h)
        if subtitle_png and subtitle_png.exists():
            cmd_inputs.extend(["-i", str(subtitle_png)])
            vf = f"[0:v]{pixel_filter}[px];[px][1:v]overlay=0:0[final]"
            audio_input_idx = 2
        else:
            vf = pixel_filter
            audio_input_idx = 1
    else:
        vf = pixel_filter
        audio_input_idx = 1

    cmd_inputs.extend([
        "-i", str(audio_wav),
        "-t", f"{duration_s:.3f}",
    ])

    if subtitle_lines and subtitle_png and subtitle_png.exists():
        cmd_inputs.extend(["-filter_complex", vf])
        cmd_inputs.extend(["-map", "[final]", "-map", f"{audio_input_idx}:a"])
    else:
        cmd_inputs.extend(["-vf", vf])
        cmd_inputs.extend(["-map", "0:v", "-map", f"{audio_input_idx}:a"])

    cmd_inputs.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ])

    try:
        result = subprocess.run(cmd_inputs, timeout=120, capture_output=True)
        
        if subtitle_png and subtitle_png.exists():
            try:
                subtitle_png.unlink()
            except Exception:
                pass
        if result.returncode == 0 and out_mp4.exists():
            return True
        stderr_msg = result.stderr.decode(errors="ignore")[-300:]
        print(f"  [mux error] {stderr_msg}")
        return False
    except Exception as e:
        print(f"  [mux error] {e}")
        if subtitle_png and subtitle_png.exists():
            try:
                subtitle_png.unlink()
            except Exception:
                pass
        return False


# ── Mastering ──────────────────────────────────────────────────────────────────

def apply_mastering(seg: AudioSegment) -> AudioSegment:
    """Normalize to -3 dB peak, then apply Limiter(threshold_db=-1.0)."""
    max_int = float(2 ** (8 * seg.sample_width - 1))
    raw = np.array(seg.get_array_of_samples(), dtype=np.float32) / max_int
    audio = raw.reshape(-1, seg.channels).T.copy()
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio *= (10 ** (-3.0 / 20.0)) / peak
    board     = Pedalboard([Limiter(threshold_db=-1.0)])
    processed = board(audio, sample_rate=float(seg.frame_rate))
    processed = np.clip(processed, -1.0, 1.0)
    int_data  = (processed.T.flatten() * max_int).astype(np.int16)
    return AudioSegment(
        int_data.tobytes(),
        frame_rate=seg.frame_rate,
        sample_width=2,
        channels=seg.channels,
    )


# ── Notifications ──────────────────────────────────────────────────────────────

def notify_make(out_path: Path, subtitle_code: str, camera: dict,
                radio_name: str = "", radio_countrycode: str = "") -> None:
    """Upload to R2 and notify Make.com webhook."""
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    r2_endpoint = os.getenv("R2_ENDPOINT")
    r2_bucket = os.getenv("R2_BUCKET")
    r2_key_id = os.getenv("R2_KEY_ID")
    r2_app_key = os.getenv("R2_APP_KEY")
    make_webhook_url = os.getenv("MAKE_WEBHOOK_URL")

    if not all([r2_public_url, r2_endpoint, r2_bucket, r2_key_id, r2_app_key]):
        return

    try:
        if not boto3:
            return
        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_key_id,
            aws_secret_access_key=r2_app_key,
        )
        file_key = out_path.name
        s3_client.upload_file(
            str(out_path),
            r2_bucket,
            file_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        if make_webhook_url and requests:
            video_url = f"{r2_public_url.rstrip('/')}/{file_key}"
            payload = {
                "url": video_url,
                "subtitle": subtitle_code,
                "description": camera.get("description", "") if camera else "",
                "jurisdiction": camera.get("jurisdiction", "") if camera else "",
                "radio_name": radio_name,
                "radio_countrycode": radio_countrycode,
            }
            requests.post(make_webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"  [notify error] {e}")


# ── Generator ──────────────────────────────────────────────────────────────────

def generate() -> Path:
    rng = random.Random()
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y%m%d")
    hhmm_str = now_dt.strftime("%H%M")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Market Data
    print("  Fetching market data…")
    brent_cur, brent_prev = get_brent_price()
    gas_cur, gas_prev = get_va_gas_price()

    subtitle_lines = []
    
    # Brent Subtitle Logic
    b_symbol = "▲" if brent_cur > brent_prev else "▼" if brent_cur < brent_prev else ""
    b_color = "#FF3F3F" if brent_cur > brent_prev else "#1DE9B6" if brent_cur < brent_prev else "#D1D1D1"
    subtitle_lines.append({"text": f"BRENT  ${brent_cur:.2f} {b_symbol}", "color": b_color})

    # Gas Subtitle Logic
    g_symbol = "▲" if gas_cur > gas_prev else "▼" if gas_cur < gas_prev else ""
    g_color = "#FF3F3F" if gas_cur > gas_prev else "#1DE9B6" if gas_cur < gas_prev else "#D1D1D1"
    subtitle_lines.append({"text": f"VA GAS   ${gas_cur:.2f} {g_symbol}", "color": g_color})

    # 2. Select ambience
    sample_files = sorted(list(SAMPLES_DIR.glob("*.wav")) + list(SAMPLES_DIR.glob("*.mp3")))
    if not sample_files:
        raise RuntimeError(f"No audio files found in {SAMPLES_DIR}")
    ambience_path = rng.choice(sample_files)
    
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(ambience_path)]
    try:
        total_duration = float(subprocess.check_output(cmd).decode().strip())
    except:
        total_duration = 0.0

    target_s = DURATION_MS / 1000.0
    start_time_s = rng.uniform(0, max(0.0, total_duration - target_s))
    
    print(f"\nTarget {target_s}s track  |  {today_str} {hhmm_str}")
    print("─" * 50)
    print(f"  ambience {ambience_path.name}")

    ambience_seg = load_seg(ambience_path)[int(start_time_s * 1000) : int(start_time_s * 1000) + DURATION_MS]
    if len(ambience_seg) < DURATION_MS:
        ambience_seg = loop_to(ambience_seg, DURATION_MS, ambience_path)

    # 3. Select radio
    radio = pick_radio(rng)
    radio_url = radio.get("url", RADIO_URL) if radio else RADIO_URL
    radio_name = radio.get("name", RADIO_NAME) if radio else RADIO_NAME
    radio_countrycode = radio.get("countrycode", "US") if radio else "US"

    # 4. Select camera
    camera = pick_camera(rng)
    cam_id = camera.get("id", "nocam") if camera else "nocam"
    subtitle_code = build_subtitle(camera, now_dt.date()) if camera else ""

    print(f"  radio    {radio_name}")
    print(f"  camera   {cam_id}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Unique name to prevent any ghosting/reuse
        radio_wav  = tmpdir / f"radio_{int(datetime.now().timestamp())}.wav"
        video_mp4  = tmpdir / "video.mp4"
        final_wav  = tmpdir / "final.wav"

        radio_ok = False
        radio_attempts = 0
        radio_pool = load_radio_pool()
        cur_url, cur_name, cur_code = radio_url, radio_name, radio_countrycode

        while not radio_ok and radio_attempts < 5:
            can_connect, reason_pre = preflight(cur_url)
            if can_connect:
                content_ok, reason_val = validate_radio_content(cur_url)
                if content_ok:
                    radio_ok = record_radio(cur_url, radio_wav, DURATION_MS, cur_name)
                else:
                    print(f"  [radio skip] {cur_name}: {reason_val}")
            else:
                print(f"  [radio skip] {cur_name}: connection {reason_pre}")
            
            if not radio_ok:
                radio_attempts += 1
                if radio_pool:
                    st = rng.choice(radio_pool)
                    cur_url, cur_name, cur_code = st["url"], st["name"], st["countrycode"]
        
        if not radio_ok:
            radio_ok = record_radio(RADIO_URL, radio_wav, DURATION_MS, RADIO_NAME)
            cur_url, cur_name, cur_code = RADIO_URL, RADIO_NAME, "US"

        if not radio_ok:
            raise RuntimeError("All radio failed")

        radio_seg = load_seg(radio_wav)[:DURATION_MS]
        mix = ambience_seg.overlay(radio_seg + RADIO_LEVEL_DB)
        mix = apply_mastering(mix)
        mix.export(str(final_wav), format="wav")

        # Record video
        video_ok = False
        video_attempts = 0
        pool = load_camera_pool()
        while not video_ok and video_attempts < 5 and camera:
            video_ok = record_video(camera.get("url", ""), video_mp4, DURATION_MS)
            if not video_ok:
                video_attempts += 1
                camera = rng.choice(pool) if pool else None

        # Assemble
        safe_station = re.sub(r'[^a-zA-Z0-9_-]', '_', cur_name)
        out_name = f"{today_str}_{hhmm_str}_cam{cam_id}_{safe_station}.mp4"
        out_path = OUTPUT_DIR / out_name
        
        if video_ok:
            mux_audio_video(final_wav, video_mp4, out_path, DURATION_MS, subtitle_lines)
        else:
            mix.export(str(OUTPUT_DIR / out_name.replace(".mp4", ".wav")), format="wav")
            out_path = OUTPUT_DIR / out_name.replace(".mp4", ".wav")

    print(f"\n✓  {out_path.name}")
    notify_make(out_path, subtitle_code, camera, cur_name, cur_code)
    return out_path


if __name__ == "__main__":
    try:
        generate()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

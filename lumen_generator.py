#!/usr/bin/env python3
"""
LUMEN Track Generator

Generates one daily track:

  full_drum_loop (stretched to 116 BPM if BPM found in filename)
  + radio recording (live NPR stream)
  + video from VDOT traffic camera (muxed into final .mp4)

Rules:

- samples are taken only from samples/full drum
- BPM is parsed only from filename pattern Bpm{N}_
- files without BPM pattern are rejected (must find one with BPM)
- drum loop is repeated whole number of times to fill ~30+ seconds
- radio is recorded for same duration as looped drum via ffmpeg
- radio raw recording is archived to output/radio_raw/
- drum and radio mixed at 0 dB, then mastering: normalize to −3 dB peak + Limiter(threshold_db=−1.0)
- video is recorded from a random camera in camera_catalog.csv (with retry up to 5 attempts)
- final output is .mp4 (video + audio muxed) with subtitle overlay

Sample rotation:

- samples rotate in round-robin order through the full library
- order is reshuffled (randomly) each new cycle
- after successful export, sample is removed from queue until cycle exhaustion
- library exhaustion triggers a new shuffle
- rotation state stored in output/sample_rotation.json
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
import pyrubberband as pyrb
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

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

SAMPLES_DIR      = Path(__file__).parent / "samples" / "full drum"
OUTPUT_DIR       = Path(__file__).parent / "output"
RADIO_RAW_DIR    = OUTPUT_DIR / "radio_raw"
TRACKS_DIR       = OUTPUT_DIR / "tracks"
ROTATION_LOG     = OUTPUT_DIR / "sample_rotation.json"
CAMERA_CATALOG   = Path(__file__).parent / "private" / "camera_catalog.csv"
RADIO_CATALOG    = Path(__file__).parent / "private" / "radio_catalog.csv"
FONT_PATH        = Path(__file__).parent / "HomeVideo-Regular.ttf"

SR               = 44100
DURATION_MS      = 30_000
RADIO_URL        = "https://npr-ice.streamguys1.com/live.mp3"  # fallback
RADIO_NAME       = "NPR_ICE"          # fallback name
RADIO_LEVEL_DB   = -10                # radio volume in mix (relative to drums at 0 dB)
TARGET_BPM       = 116

VIDEO_TIMEOUT    = 60                # max seconds to wait for video recording

# Radio content validation (loudness + speech check)
MIN_DBFS         = -32               # minimum loudness (dBFS)
MIN_SPEECH_RATIO = 0.65              # minimum speech ratio (0-1)
RADIO_VALIDATE_S = 15                # seconds to record for validation (increased for better VAD accuracy)

# Day names for subtitle (Monday → MON, Tuesday → THE, etc.)
DAY_NAMES      = ["MON", "THE", "WED", "THU", "FRI", "SAT", "SUN"]


# ── Round-robin sample rotation ────────────────────────────────────────────────

def load_rotation() -> dict:
    """Load rotation state: {queue: [...], used: [...]}"""
    try:
        return json.loads(ROTATION_LOG.read_text()) if ROTATION_LOG.exists() else {}
    except Exception:
        return {}


def save_rotation(state: dict) -> None:
    ROTATION_LOG.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def get_fresh_drum(rng: random.Random) -> Path:
    """
    Pick next drum loop using round-robin rotation.
    Library is shuffled once per cycle. When queue is exhausted,
    a new shuffled cycle begins automatically.
    Does NOT mark as used — that happens after successful export.
    """
    all_files = sorted(
        p for p in SAMPLES_DIR.glob("*.wav")
        if extract_bpm_from_filename(p) is not None
    )
    if not all_files:
        raise RuntimeError(f"No Bpm{{N}}_*.wav files in {SAMPLES_DIR}")

    all_names = [str(p) for p in all_files]
    state = load_rotation()
    queue = state.get("queue", [])

    # Filter queue to only files that still exist
    queue = [p for p in queue if p in all_names]

    if not queue:
        # Start a new cycle: shuffle all files
        new_queue = all_names.copy()
        rng.shuffle(new_queue)
        queue = new_queue
        cycle = state.get("cycle", 0) + 1
        print(f"  [rotation] new cycle #{cycle} — reshuffled {len(queue)} samples")
        state["cycle"] = cycle

    chosen = queue[0]  # take first in queue (don't pop yet — pop after export)
    state["queue"] = queue
    state["pending"] = chosen   # remember what we're about to use
    save_rotation(state)

    return Path(chosen)


def confirm_drum_used() -> None:
    """Pop the pending sample from the queue after successful export."""
    state = load_rotation()
    pending = state.get("pending")
    queue   = state.get("queue", [])
    if pending and queue and queue[0] == pending:
        queue.pop(0)
        state["queue"] = queue
        state.pop("pending", None)
        used = state.get("used", [])
        used.append({"path": pending, "date": date.today().isoformat()})
        state["used"] = used[-500:]  # keep last 500 entries
        save_rotation(state)


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


def extract_bpm_from_filename(path: Path) -> int | None:
    """Extract BPM from filename like 'Bpm125_...'. Returns None if not found."""
    match = re.search(r"[Bb]pm(\d+)_", path.name)
    return int(match.group(1)) if match else None


def time_stretch_to_target(seg: AudioSegment, original_bpm: int | None,
                           target_bpm: int = TARGET_BPM) -> AudioSegment:
    """Time-stretch audio to target BPM using pyrubberband (R3 quality)."""
    if original_bpm is None or original_bpm == target_bpm:
        return seg

    # Fix subprocess PATH issue in LaunchAgent: prepend homebrew bin explicitly
    import subprocess
    old_path = os.environ.get('PATH', '')
    os.environ['PATH'] = '/opt/homebrew/bin:/opt/homebrew/sbin:' + old_path

    ratio = target_bpm / original_bpm
    max_int = float(2 ** (8 * seg.sample_width - 1))
    raw = np.array(seg.get_array_of_samples(), dtype=np.float32) / max_int
    audio = raw.reshape(-1, seg.channels).astype(np.float32)

    try:
        stretched = pyrb.time_stretch(audio, sr=seg.frame_rate, rate=ratio,
                                      rbargs={"--fine": ""})
    finally:
        os.environ['PATH'] = old_path
    stretched = np.clip(stretched, -1.0, 1.0)
    int_data = (stretched.flatten() * max_int).astype(np.int16)
    return AudioSegment(
        int_data.tobytes(),
        frame_rate=seg.frame_rate,
        sample_width=2,
        channels=seg.channels,
    )


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


def archive_radio(src_wav: Path, duration_ms: int, station_name: str = "") -> Path | None:
    """
    Copy radio recording to radio_raw/ with a descriptive filename.
    Format: YYYYMMDD_HHMMSS_{STATION_NAME}_{duration}s.wav
    """
    try:
        RADIO_RAW_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        duration_s = int(duration_ms / 1000)
        station_name = station_name or RADIO_NAME
        # Sanitize station name for filename
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', station_name)
        archive_name = f"{now}_{safe_name}_{duration_s}s.wav"
        archive_path = RADIO_RAW_DIR / archive_name
        import shutil
        shutil.copy2(src_wav, archive_path)
        size_kb = archive_path.stat().st_size // 1024
        print(f"  Radio archived → radio_raw/{archive_name}  ({size_kb} KB)")
        return archive_path
    except Exception as e:
        print(f"  [archive error] {e}")
        return None


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
                if "|" in line and not line.strip().startswith("#"):
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
                if "|" in line and not line.strip().startswith("#"):
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
                    print(f"  [radio_pool] warning: station without name, skipping")
                    continue
                if not url:
                    print(f"  [radio_pool] warning: {name} has no URL, skipping")
                    continue

                # Filter by included countries (whitelist)
                if include_countries:
                    if not countrycode or countrycode not in include_countries:
                        print(f"  [radio_pool] skipping {name} — country {countrycode or 'XX'} not in include list")
                        continue

                # Filter by excluded countries (blacklist)
                if exclude_countries:
                    if countrycode and countrycode in exclude_countries:
                        print(f"  [radio_pool] skipping {name} — country {countrycode} excluded")
                        continue

                # Filter by included languages (whitelist)
                if include_languages:
                    if not language:
                        print(f"  [radio_pool] skipping {name} — no language specified (include_languages active)")
                        continue
                    language_lower = language.lower()
                    is_included = False
                    for include_lang in include_languages:
                        if include_lang in language_lower:
                            is_included = True
                            break
                    if not is_included:
                        print(f"  [radio_pool] skipping {name} — language '{language}' not in include list")
                        continue

                # Filter by excluded languages (blacklist)
                if exclude_languages:
                    if language:
                        language_lower = language.lower()
                        is_excluded = False
                        for exclude_lang in exclude_languages:
                            if exclude_lang in language_lower:
                                print(f"  [radio_pool] skipping {name} — language '{language}' excluded")
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
    Build subtitle in format: PRBRCK▶{route_code}{cam_id_last_2}{day_abbr}
    Returns: (full_subtitle, code) where code is everything after PRBRCK▶
    Example: ("PRBRCK▶VA64103MON", "VA64103MON")
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
    full = f"PRBRCK▶{code}"

    return (full, code)


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


def create_subtitle_overlay(text: str, width: int = 1280, height: int = 850) -> Path | None:
    """
    Create a transparent PNG with subtitle text overlaid at bottom center.
    Text bottom edge is 30px from bottom of image.
    Returns path to temporary PNG file.
    """
    try:
        # Create transparent image
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Load font, fallback to default if not found
        font_size = 55
        try:
            font = ImageFont.truetype(str(FONT_PATH), font_size)
        except Exception:
            font = ImageFont.load_default()

        # Color: D1D1D1 in RGB (with alpha)
        color = (0xD1, 0xD1, 0xD1, 255)

        # Get text bounding box to calculate dimensions
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Position: centered horizontally, 30px from bottom (measuring bottom edge of text)
        x = (width - text_width) // 2
        y = height - 30 - text_height  # Position so bottom edge is 30px from bottom

        # Draw text
        draw.text((x, y), text, font=font, fill=color)

        # Save to temp file
        temp_png = Path(tempfile.gettempdir()) / f"subtitle_{id(img)}.png"
        img.save(str(temp_png), "PNG")
        return temp_png
    except Exception as e:
        print(f"  [subtitle error] {e}")
        return None


def mux_audio_video(audio_wav: Path, video_mp4: Path, out_mp4: Path,
                    duration_ms: int, subtitle: str = "") -> bool:
    """
    Mux audio WAV + video MP4 into final MP4.
    Video is scaled to 1280x960, then cropped to 1280x850.
    Subtitle is overlaid at bottom center using PNG overlay.
    Audio is re-encoded to AAC for MP4 compatibility.
    """
    duration_s = duration_ms / 1000.0
    print(f"  Muxing audio + video…")

    # Create subtitle overlay if needed
    subtitle_png = None
    cmd_inputs = [
        "ffmpeg", "-y",
        "-i", str(video_mp4),
    ]

    # Build video filter chain
    if subtitle:
        subtitle_png = create_subtitle_overlay(subtitle)
        if subtitle_png and subtitle_png.exists():
            # Two video inputs: [0] = video, [1] = PNG
            cmd_inputs.extend(["-i", str(subtitle_png)])
            # Scale video, crop, then overlay PNG (PNG already at 1280x850, no scale needed)
            vf = "[0:v]scale=1280:960,crop=1280:850:0:130[scaled];[scaled][1:v]overlay=0:0[final]"
            audio_input_idx = 2
        else:
            # Fallback: no overlay
            vf = "scale=1280:960,crop=1280:850:0:130"
            audio_input_idx = 1
    else:
        vf = "scale=1280:960,crop=1280:850:0:130"
        audio_input_idx = 1

    cmd_inputs.extend([
        "-i", str(audio_wav),
        "-t", f"{duration_s:.3f}",
    ])

    # Use -filter_complex if we have overlay, otherwise -vf
    if subtitle and subtitle_png and subtitle_png.exists():
        cmd_inputs.extend(["-filter_complex", vf])
        # Map video from overlay output and audio
        cmd_inputs.extend(["-map", "[final]", "-map", f"{audio_input_idx}:a"])
    else:
        cmd_inputs.extend(["-vf", vf])
        # Map audio normally
        cmd_inputs.extend(["-map", "v:0", "-map", f"{audio_input_idx}:a"])

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

        # Clean up temp PNG
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
    except subprocess.TimeoutExpired:
        print("  [mux error] timeout during mux")
        if subtitle_png and subtitle_png.exists():
            try:
                subtitle_png.unlink()
            except Exception:
                pass
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
    """
    Upload video to R2 and notify Make.com webhook.
    subtitle_code is the part after PRBRCK▶ (e.g., VA64103MON)
    Skips if environment variables not set (prints message for R2, silent for webhook).
    """
    # Check if R2 is configured (required for upload)
    r2_public_url = os.getenv("R2_PUBLIC_URL")
    r2_endpoint = os.getenv("R2_ENDPOINT")
    r2_bucket = os.getenv("R2_BUCKET")
    r2_key_id = os.getenv("R2_KEY_ID")
    r2_app_key = os.getenv("R2_APP_KEY")

    # Make webhook is optional
    make_webhook_url = os.getenv("MAKE_WEBHOOK_URL")

    if not all([r2_public_url, r2_endpoint, r2_bucket, r2_key_id, r2_app_key]):
        print("  [notify] R2 not configured, skipping upload")
        return

    try:
        # Upload to R2
        if not boto3:
            print("  [notify] boto3 not installed, skipping R2 upload")
            return

        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_key_id,
            aws_secret_access_key=r2_app_key,
        )

        file_key = out_path.name
        print(f"  Uploading to R2: {file_key}…")

        s3_client.upload_file(
            str(out_path),
            r2_bucket,
            file_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )

        # Notify Make.com webhook (optional)
        if make_webhook_url:
            if not requests:
                print("  [notify] requests not installed, skipping webhook")
                return

            video_url = f"{r2_public_url.rstrip('/')}/{file_key}"
            payload = {
                "url": video_url,
                "subtitle": subtitle_code,
                "description": camera.get("description", "") if camera else "",
                "jurisdiction": camera.get("jurisdiction", "") if camera else "",
                "radio_name": radio_name,
                "radio_countrycode": radio_countrycode,
            }

            # Debug: log payload before sending
            print(f"  [webhook payload] {json.dumps(payload, ensure_ascii=False)}")

            response = requests.post(make_webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"  Webhook notified → {video_url}")
            else:
                print(f"  [webhook error] {response.status_code}")
    except Exception as e:
        print(f"  [notify error] {e}")


# ── Generator ──────────────────────────────────────────────────────────────────

def generate() -> Path:
    rng = random.Random()
    today = date.today()
    today_str = today.strftime("%Y%m%d")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRACKS_DIR.mkdir(parents=True, exist_ok=True)

    # Select drum loop (round-robin rotation)
    drum_path = get_fresh_drum(rng)
    drum_bpm  = extract_bpm_from_filename(drum_path)

    # Select radio station (with fallback to NPR if catalog empty)
    radio = pick_radio(rng)
    radio_url = RADIO_URL
    radio_name = RADIO_NAME
    radio_country = ""
    radio_countrycode = "US"  # Default to US for NPR fallback
    if radio:
        radio_url = radio.get("url", RADIO_URL) or RADIO_URL
        radio_name = radio.get("name", RADIO_NAME) or RADIO_NAME
        radio_country = radio.get("country", "")
        radio_countrycode = radio.get("countrycode", "")
        print(f"  [initial pick] {radio_name} ({radio_countrycode})")

    # Select camera (with retry on record failure)
    camera = pick_camera(rng)
    cam_desc = camera.get("description", "unknown") if camera else "no camera"

    # Build subtitle for overlay (returns full subtitle and code separately)
    subtitle, subtitle_code = build_subtitle(camera, today) if camera else ("", "")

    print(f"\nTarget {TARGET_BPM} BPM  |  {today_str}")
    print("─" * 50)
    print(f"  drum     {drum_bpm} BPM → {TARGET_BPM}  {drum_path.name}")
    print(f"  radio    {radio_name}" + (f"  ({radio_country})" if radio_country else ""))
    print(f"  camera   {cam_desc}")
    if subtitle:
        print(f"  subtitle {subtitle}")

    # Load and stretch drum
    drum_seg = load_seg(drum_path)
    drum_seg = time_stretch_to_target(drum_seg, drum_bpm)

    # Calculate actual duration: whole reps of loop to ~DURATION_MS
    reps = math.ceil(DURATION_MS / len(drum_seg))
    actual_duration_ms = len(drum_seg) * reps

    drum_looped = loop_to(drum_seg, actual_duration_ms, drum_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        radio_wav  = tmpdir / "radio.wav"
        video_mp4  = tmpdir / "video.mp4"
        final_wav  = tmpdir / "final.wav"

        # Record radio with validation: connectivity → content (loudness + speech) → record
        radio_ok = False
        radio_attempts = 0
        max_radio_attempts = 5
        radio_pool = load_radio_pool()
        current_radio_url = radio_url
        current_radio_name = radio_name
        current_radio_country = radio_country
        current_radio_countrycode = radio_countrycode

        # Try pool stations (up to 5 attempts)
        while not radio_ok and radio_attempts < max_radio_attempts:
            # Step 1: Check connectivity
            print(f"  [preflight] attempt {radio_attempts + 1}/5 — {current_radio_name}")
            can_connect, reason = preflight(current_radio_url)
            if not can_connect:
                radio_attempts += 1
                print(f"  [radio] {reason} — trying next…")
                if radio_attempts < max_radio_attempts and radio_pool:
                    station = rng.choice(radio_pool)
                    current_radio_url = station.get("url", RADIO_URL) or RADIO_URL
                    current_radio_name = station.get("name", RADIO_NAME) or RADIO_NAME
                    current_radio_country = station.get("country", "")
                    current_radio_countrycode = station.get("countrycode", "")
                    print(f"    [retry] {current_radio_name} ({current_radio_countrycode})")
                continue

            # Step 2: Check content (loudness + speech)
            print(f"  [validate] attempt {radio_attempts + 1}/5 — {current_radio_name}")
            content_ok, reason = validate_radio_content(current_radio_url)
            if not content_ok:
                radio_attempts += 1
                print(f"  [radio] {reason} — trying next…")
                if radio_attempts < max_radio_attempts and radio_pool:
                    station = rng.choice(radio_pool)
                    current_radio_url = station.get("url", RADIO_URL) or RADIO_URL
                    current_radio_name = station.get("name", RADIO_NAME) or RADIO_NAME
                    current_radio_country = station.get("country", "")
                    current_radio_countrycode = station.get("countrycode", "")
                    print(f"    [retry] {current_radio_name} ({current_radio_countrycode})")
                continue

            # Step 3: Record radio
            print(f"  [record] attempt {radio_attempts + 1}/5 — {current_radio_name}")
            radio_ok = record_radio(current_radio_url, radio_wav, actual_duration_ms, current_radio_name)
            if not radio_ok:
                radio_attempts += 1
                if radio_attempts < max_radio_attempts and radio_pool:
                    station = rng.choice(radio_pool)
                    current_radio_url = station.get("url", RADIO_URL) or RADIO_URL
                    current_radio_name = station.get("name", RADIO_NAME) or RADIO_NAME
                    current_radio_country = station.get("country", "")
                    current_radio_countrycode = station.get("countrycode", "")
                    print(f"    [retry] {current_radio_name} ({current_radio_countrycode})")
            else:
                radio_attempts = max_radio_attempts  # Exit loop on success

        # If pool is empty or all attempts failed, try NPR fallback as last resort
        if not radio_ok:
            if radio_pool:
                print(f"  [radio] All pool attempts failed ({radio_attempts}/5) — trying NPR fallback…")
            else:
                print(f"  [radio] Filtered pool is empty — trying NPR fallback…")
            current_radio_url = RADIO_URL
            current_radio_name = RADIO_NAME
            current_radio_country = ""
            current_radio_countrycode = "US"

            # Validate NPR
            print(f"  [preflight] NPR fallback")
            can_connect, reason = preflight(RADIO_URL)
            if can_connect:
                print(f"  [validate] NPR fallback")
                content_ok, reason = validate_radio_content(RADIO_URL)
                if content_ok:
                    print(f"  [record] NPR fallback")
                    radio_ok = record_radio(RADIO_URL, radio_wav, actual_duration_ms, RADIO_NAME)
                else:
                    print(f"  [NPR validation failed] {reason}")
            else:
                print(f"  [NPR preflight failed] {reason}")

            # If NPR failed, abort generation
            if not radio_ok:
                raise RuntimeError(
                    f"[FATAL] All radio streams exhausted (5 pool + NPR fallback). "
                    f"Cannot generate track without valid audio source."
                )

        # Mix radio with drums
        radio_seg = load_seg(radio_wav)[:actual_duration_ms]
        mix = drum_looped.overlay(radio_seg + RADIO_LEVEL_DB)
        duration_s = actual_duration_ms / 1000
        print(f"  Drum + radio mixed (radio at {RADIO_LEVEL_DB} dB)  ({duration_s:.1f}s)")
        # Archive radio raw recording
        archive_radio(radio_wav, actual_duration_ms, current_radio_name)

        # Mastering
        print("  Mastering…")
        mix = apply_mastering(mix)

        # Record video with fallback: if fails, try another camera (max 5 attempts)
        video_ok = False
        attempts = 0
        max_attempts = 5
        pool = load_camera_pool()

        while not video_ok and attempts < max_attempts and camera:
            cam_url = camera.get("url", "").strip()
            if not cam_url:
                print("  [camera] empty URL, skipping")
                attempts += 1
                if attempts < max_attempts:
                    camera = rng.choice(pool) if pool else None
                    if camera:
                        cam_desc = camera.get("description", "unknown")
                        subtitle, subtitle_code = build_subtitle(camera, today)
                    else:
                        cam_desc = "no camera"
                        subtitle, subtitle_code = "", ""
                continue
            video_ok = record_video(cam_url, video_mp4, actual_duration_ms)
            if not video_ok:
                attempts += 1
                if attempts < max_attempts:
                    camera = rng.choice(pool) if pool else None
                    if camera:
                        cam_desc = camera.get("description", "unknown")
                        subtitle, subtitle_code = build_subtitle(camera, today)
                    else:
                        cam_desc = "no camera"
                        subtitle, subtitle_code = "", ""

        # Export mastered audio to temp WAV for muxing
        mix.export(str(final_wav), format="wav")

        # Build output filename base (sanitize station name for filename)
        drum_name = drum_path.stem
        cam_id    = camera["id"] if camera else "nocam"
        safe_station_name = re.sub(r'[^a-zA-Z0-9_-]', '_', current_radio_name)
        base_name = f"{today_str}_bpm{TARGET_BPM}_{drum_name}_cam{cam_id}_{safe_station_name}"

        # Save audio track (WAV without video) to tracks/ if subtitle available
        if subtitle:
            track_path = TRACKS_DIR / f"{subtitle}.wav"
            mix.export(str(track_path), format="wav")
            size_kb = track_path.stat().st_size // 1024
            print(f"  Audio track → tracks/{track_path.name}  ({size_kb} KB)")

        # Generate video
        out_path = None
        if video_ok:
            out_path = OUTPUT_DIR / f"{base_name}.mp4"
            mux_ok = mux_audio_video(final_wav, video_mp4, out_path, actual_duration_ms, subtitle)
            if not mux_ok:
                # Fallback to WAV if mux fails
                print("  [mux failed] saving WAV only")
                out_path = OUTPUT_DIR / f"{base_name}.wav"
                mix.export(str(out_path), format="wav")
        else:
            # No video — save WAV
            print("  [no video] saving WAV only")
            out_path = OUTPUT_DIR / f"{base_name}.wav"
            mix.export(str(out_path), format="wav")

    size_kb = out_path.stat().st_size // 1024
    print(f"\n✓  {out_path.name}  ({size_kb} KB)")

    # Mark sample as used only after successful export
    confirm_drum_used()

    # Ensure radio metadata is never None (guarantee for webhook)
    current_radio_name = current_radio_name or "UNKNOWN"
    if current_radio_countrycode is None:
        current_radio_countrycode = ""

    # Final validation before webhook
    print(f"[FINAL RADIO] {current_radio_name} ({current_radio_countrycode})")

    # Notify Make.com webhook and upload to R2
    # Use current_radio_name/code (actual station used, might differ if validation retried)
    notify_make(out_path, subtitle_code, camera, current_radio_name, current_radio_countrycode)

    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        generate()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

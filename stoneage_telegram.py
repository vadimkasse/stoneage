#!/usr/bin/env python3
"""
STONEAGE Telegram Uploader

Posts/updates video in a Telegram channel.
Strategy:
1. Attempts to edit the existing message (video + caption) via editMessageMedia.
2. If edit fails (e.g. message too old or missing), falls back to deleting the old message
   and sending a new one with disable_notification=True.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
STATE_FILE = BASE_DIR / "telegram_state.json"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
    sys.exit(1)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to read state file: {e}")
    return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save state file: {e}")


def build_caption(meta: dict) -> str:
    """Constructs caption from metadata matching original StoneAge format."""
    b_cur = meta.get("brent_cur", 0)
    b_prev = meta.get("brent_prev", 0)
    g_cur = meta.get("gas_cur", 0)
    g_prev = meta.get("gas_prev", 0)

    b_sym = "▲" if b_cur > b_prev else "▼" if b_cur < b_prev else " "
    g_sym = "▲" if g_cur > g_prev else "▼" if g_cur < g_prev else " "

    line1 = f"Brent ${b_cur:.1f} {b_sym} | Gas, VA ${g_cur:.2f} {g_sym}"

    camera = meta.get("camera", {})
    jurisdiction = camera.get("jurisdiction", "Virginia")
    if isinstance(jurisdiction, list) and jurisdiction:
        jurisdiction = jurisdiction[0]

    line2 = f"online VaDOT camera {jurisdiction}"

    radio_name = meta.get("radio_name", "")
    line3 = f"news from {radio_name}"

    return f"{line1}\n{line2}\n{line3}"


def delete_message(message_id: int):
    """Deletes previous message if exists."""
    url = f"{API_BASE}/deleteMessage"
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "message_id": message_id}, timeout=30)
        if resp.status_code == 200 and resp.json().get("ok"):
            print(f"  ✓ Deleted previous message {message_id}")
        else:
            print(f"  ✗ Could not delete message {message_id}: {resp.text}")
    except Exception as e:
        print(f"  ✗ Error deleting message {message_id}: {e}")


def send_new_video(video_path: Path, caption: str) -> int:
    """Sends new video with disable_notification=True."""
    print("--- Sending New Video Message ---")
    url = f"{API_BASE}/sendVideo"
    data = {
        "chat_id": CHAT_ID,
        "caption": caption,
        "disable_notification": True
    }
    with open(video_path, "rb") as f:
        files = {"video": (video_path.name, f, "video/mp4")}
        resp = requests.post(url, data=data, files=files, timeout=120)

    if resp.status_code == 200 and resp.json().get("ok"):
        msg_id = resp.json()["result"]["message_id"]
        print(f"✓ Video sent successfully! Message ID: {msg_id}")
        return msg_id
    else:
        print(f"[ERROR] Failed to send video: {resp.status_code} {resp.text}")
        sys.exit(1)


def edit_existing_video(message_id: int, video_path: Path, caption: str) -> bool:
    """Attempts to edit the video and caption of existing message via editMessageMedia."""
    print(f"--- Editing Existing Message: {message_id} ---")
    url = f"{API_BASE}/editMessageMedia"
    media_payload = {
        "type": "video",
        "media": "attach://video_file",
        "caption": caption
    }
    data = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "media": json.dumps(media_payload)
    }
    with open(video_path, "rb") as f:
        files = {"video_file": (video_path.name, f, "video/mp4")}
        resp = requests.post(url, data=data, files=files, timeout=120)

    if resp.status_code == 200 and resp.json().get("ok"):
        print(f"✓ Message {message_id} edited successfully with new video.")
        return True
    else:
        print(f"[WARN] editMessageMedia failed ({resp.status_code}): {resp.text}")
        return False


def main():
    meta_path = OUTPUT_DIR / "latest_meta.json"
    if not meta_path.exists():
        print("[ERROR] latest_meta.json not found.")
        sys.exit(1)

    with open(meta_path, "r") as f:
        meta = json.load(f)

    video_path = Path(meta.get("video_path", ""))
    if not video_path.exists():
        print(f"[ERROR] Video file not found: {video_path}")
        sys.exit(1)

    caption = build_caption(meta)
    print(f"Target Video: {video_path.name}")
    print(f"Caption:\n---\n{caption}\n---")

    state = load_state()
    prev_msg_id = state.get("message_id")

    updated = False
    if prev_msg_id:
        updated = edit_existing_video(prev_msg_id, video_path, caption)
        if not updated:
            print("  Falling back to delete + send new message...")
            delete_message(prev_msg_id)

    if not updated:
        new_msg_id = send_new_video(video_path, caption)
        save_state({
            "message_id": new_msg_id,
            "last_video": video_path.name,
            "updated_at": datetime.now().isoformat()
        })
    else:
        save_state({
            "message_id": prev_msg_id,
            "last_video": video_path.name,
            "updated_at": datetime.now().isoformat()
        })


if __name__ == "__main__":
    main()

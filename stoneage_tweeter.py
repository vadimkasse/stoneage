#!/usr/bin/env python3
"""
STONEAGE X API Uploader

Posts video to X (Twitter) using official API v1.1 (Media) and v2 (Tweet).
Supports Chunked Upload for video stability.
NEW: Deletes ALL existing tweets before posting new one.
"""

import os
import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime
from requests_oauthlib import OAuth1
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "output"

# API Endpoints
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
POST_TWEET_URL = "https://api.twitter.com/2/tweets"
USER_ME_URL = "https://api.twitter.com/2/users/me"
USER_TWEETS_URL = "https://api.twitter.com/2/users/{id}/tweets"
DELETE_TWEET_URL = "https://api.twitter.com/2/tweets/{id}"

# Radio to Twitter Handle mapping
RADIO_HANDLES = {
    "Bloomberg Radio": "@BloombergRadio",
    "WNYC News": "@WNYCNews",
    "NPR": "@NPR",
    "NPR_ICE": "@NPR",
    "BBC World Service": "@BBCWorldService"
}

# Credentials
CONSUMER_KEY = os.getenv("X_API_KEY")
CONSUMER_SECRET = os.getenv("X_API_SECRET")
ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")

if not all([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
    print("[ERROR] Missing X API credentials in .env")
    sys.exit(1)

oauth = OAuth1(CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)

# ── API Logic ────────────────────────────────────────────────────────────────

def get_my_user_id() -> str:
    """Gets the ID of the authenticated user."""
    resp = requests.get(USER_ME_URL, auth=oauth)
    if resp.status_code == 200:
        return resp.json()["data"]["id"]
    print(f"[ERROR] Could not get user ID: {resp.status_code} {resp.text}")
    return ""


def delete_latest_tweet(user_id: str):
    """Deletes ONLY the single most recent tweet."""
    if not user_id:
        return
    
    # Get last tweet
    url = USER_TWEETS_URL.format(id=user_id)
    params = {"max_results": 5} # Fetch small amount just in case, but delete only top
    resp = requests.get(url, auth=oauth, params=params)
    
    if resp.status_code == 200:
        data = resp.json()
        if "data" in data and len(data["data"]) > 0:
            latest_id = data["data"][0]["id"]
            print(f"--- Deleting previous tweet: {latest_id} ---")
            del_url = DELETE_TWEET_URL.format(id=latest_id)
            del_resp = requests.delete(del_url, auth=oauth)
            if del_resp.status_code == 200:
                print(f"  ✓ Deleted tweet {latest_id}")
            else:
                print(f"  ✗ Could not delete tweet {latest_id}: {del_resp.status_code}")
        else:
            print("  No previous tweets found to delete.")
    else:
        print(f"[WARN] Could not fetch user tweets: {resp.status_code} {resp.text}")


def upload_video(video_path: Path) -> str:
    """Performs Chunked Upload to X API v1.1. Returns media_id string."""
    file_size = video_path.stat().st_size
    print(f"--- Uploading Video: {video_path.name} ({file_size / 1024 / 1024:.2f} MB) ---")

    params = {"command": "INIT", "media_type": "video/mp4", "total_bytes": file_size, "media_category": "tweet_video"}
    resp = requests.post(MEDIA_UPLOAD_URL, auth=oauth, params=params)
    if resp.status_code >= 400:
        print(f"[ERROR] INIT failed: {resp.text}"); sys.exit(1)
    
    media_id = resp.json()["media_id_string"]
    print(f"  INIT success. Media ID: {media_id}")

    with open(video_path, "rb") as f:
        segment_index = 0
        while True:
            chunk = f.read(4 * 1024 * 1024)
            if not chunk: break
            files = {"media": chunk}
            params = {"command": "APPEND", "media_id": media_id, "segment_index": segment_index}
            resp = requests.post(MEDIA_UPLOAD_URL, auth=oauth, params=params, files=files)
            if resp.status_code >= 400:
                print(f"[ERROR] APPEND failed: {resp.text}"); sys.exit(1)
            segment_index += 1

    params = {"command": "FINALIZE", "media_id": media_id}
    resp = requests.post(MEDIA_UPLOAD_URL, auth=oauth, params=params)
    if resp.status_code >= 400:
        print(f"[ERROR] FINALIZE failed: {resp.text}"); sys.exit(1)

    print("  Waiting for X to process video...")
    while True:
        params = {"command": "STATUS", "media_id": media_id}
        resp = requests.get(MEDIA_UPLOAD_URL, auth=oauth, params=params)
        data = resp.json()
        info = data.get("processing_info", {})
        if info.get("state") == "succeeded":
            print("✓ Video processed successfully."); break
        elif info.get("state") == "failed":
            print(f"[ERROR] Processing failed: {info.get('error')}"); sys.exit(1)
        else:
            time.sleep(info.get("check_after_secs", 5))

    return media_id


def post_tweet(text: str, media_id: str):
    """Posts tweet using X API v2."""
    print(f"--- Posting Tweet ---")
    payload = {"text": text, "media": {"media_ids": [media_id]}}
    resp = requests.post(POST_TWEET_URL, auth=oauth, json=payload)
    if resp.status_code == 201:
        print(f"✓ Post success! Tweet ID: {resp.json()['data']['id']}")
    else:
        print(f"[ERROR] Tweet post failed: {resp.status_code} {resp.text}"); sys.exit(1)


# ── Main Orchestration ────────────────────────────────────────────────────────

def build_tweet_text(meta: dict) -> str:
    """Constructs the rich tweet text from metadata."""
    b_cur = meta.get("brent_cur", 0)
    b_prev = meta.get("brent_prev", 0)
    g_cur = meta.get("gas_cur", 0)
    g_prev = meta.get("gas_prev", 0)
    
    b_sym = "▲" if b_cur > b_prev else "▼" if b_cur < b_prev else " "
    g_sym = "▲" if g_cur > g_prev else "▼" if g_cur < g_prev else " "
    
    # 1. Market Line
    line1 = f"Brent ${b_cur:.1f} {b_sym} | Gas, VA ${g_cur:.2f} {g_sym}"
    
    # 2. Camera Line
    camera = meta.get("camera", {})
    jurisdiction = camera.get("jurisdiction", "Virginia")
    if isinstance(jurisdiction, list) and jurisdiction:
        jurisdiction = jurisdiction[0]
    
    line2 = f"online @VaDOTNOVA camera {jurisdiction}"
    
    # 3. Radio Line
    radio_name = meta.get("radio_name", "")
    handle = RADIO_HANDLES.get(radio_name, "")
    if not handle:
        handle = radio_name if radio_name != "NPR_ICE" else "@NPR"
    
    line3 = f"news from {handle}"
    
    return f"{line1}\n{line2}\n{line3}"


def main():
    meta_path = OUTPUT_DIR / "latest_meta.json"
    if not meta_path.exists():
        print("[ERROR] latest_meta.json not found."); sys.exit(1)
    
    with open(meta_path, "r") as f:
        meta = json.load(f)
    
    video_path = Path(meta.get("video_path", ""))
    if not video_path.exists():
        print("[ERROR] Video file not found."); sys.exit(1)

    tweet_text = build_tweet_text(meta)
    print(f"Target Video: {video_path.name}")
    print(f"Tweet Text:\n---\n{tweet_text}\n---")

    # 1. Cleanup: Delete ONLY the last tweet
    user_id = get_my_user_id()
    if user_id:
        delete_latest_tweet(user_id)

    # 2. Upload Video
    media_id = upload_video(video_path)
    
    # 3. Post New Tweet
    post_tweet(tweet_text, media_id)


if __name__ == "__main__":
    main()

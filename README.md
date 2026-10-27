# StoneAge: Automated Media Synthesis & Data Pipeline

**StoneAge** is an automated media pipeline designed to synthesize real-time commodity data, live radio audio streams, and highway infrastructure camera feeds into dynamic video updates for Telegram.

## 🛠 Technical Overview

This project implements a complete automated media lifecycle—from multi-source data ingestion to social media distribution—with zero operational cost and automated daily execution.

### Key Features & Architecture

*   **Real-Time Media Mixing (FFmpeg):** Synthesizes dynamic 60-second video by blending ambient highway audio, live radio streams (Bloomberg Radio, WNYC, NPR), and HLS live video from Virginia Department of Transportation (VDOT) cameras.
*   **Dynamic Data Overlay (Pillow):** Renders real-time Brent Crude Oil and Virginia gasoline price fluctuations directly onto video frames using custom retro typography.
*   **Telegram Channel Distribution:** Automatically maintains and silently updates a single video post in [@barkassepodcast](https://t.me/barkassepodcast) using Telegram Bot API (`editMessageMedia` and `editMessageCaption`).
*   **HTML Rich Formatting:** Formats captions dynamically with underlined localized date (`<u>...</u>`), bold commodity values (`<b>$110.1</b>`), price trend arrows (`▲`/`▼`), and radio source attribution.
*   **Audio Quality Assurance:** Integrates Silero VAD (Voice Activity Detection) for stream validation before recording to ensure high speech quality.
*   **Scheduling:** Scheduled via macOS LaunchAgent (`com.stoneage.daily.plist`) once daily at 11:00 AM EDT.

## 🏗 Stack & Infrastructure

*   **Core Logic:** Python 3.13 / bash
*   **Media Processing:** FFmpeg, Pillow, pydub
*   **Data Sources:** `yfinance` (Brent crude), `cloudscraper` (gas prices), HLS/M3U8 (traffic cameras)
*   **APIs:** Telegram Bot API (channel distribution), Cloudflare R2 (storage backup)
*   **Scheduler:** macOS LaunchAgent

## 🚀 Usage

```bash
# Full generation and publishing cycle
./run_stoneage.sh

# Run publisher only (updates video and caption in channel)
python3 stoneage_telegram.py

# Test/update text caption only without re-uploading video
python3 stoneage_telegram.py --caption-only

# Configure LaunchAgent schedule (e.g. 11:00 AM EDT)
./set_stoneage_schedule.sh HOURS="11" MIN=0 SEC=0
```

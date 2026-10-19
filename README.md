# StoneAge: Automated Media Synthesis & Data Pipeline

**StoneAge** is an automated content engine designed to synthesize real-time market data, live audio streams, and traffic infrastructure feeds into dynamic video updates for Telegram.

## 🛠 Technical Overview

This project showcases a complete media lifecycle—from raw data ingestion to automated social media distribution—built with a focus on reliability and zero operational cost.

### Key Technical Challenges & Solutions:

*   **Real-Time Media Mixing (FFmpeg):** Orchestrates complex multi-track synthesis by blending highway ambient audio, live MP3 radio streams (Bloomberg, WNYC, NPR), and HLS video feeds from VDOT traffic cameras.
*   **Dynamic Data Overlay:** Implements a custom graphics layer using Python (Pillow) to render real-time Brent Crude Oil and Virginia Gas price fluctuations directly onto video frames.
*   **Telegram Channel Distribution (`editMessageMedia`):** Updates a single video post in a Telegram channel in place without creating new notification noise. Falls back to silent delete-and-post (`disable_notification=True`) if the platform requires message recreation.
*   **Fault-Tolerant Audio Processing:** Includes an automated "Preflight & Validation" system for radio streams, using Silero VAD (Voice Activity Detection) to ensure speech quality before recording.

## 🏗 Stack & Infrastructure

*   **Core Logic:** Python 3.x
*   **Media Processing:** FFmpeg (Subprocess orchestration)
*   **Data Sources:** yfinance (Market data), Cloudscraper (Web scraping), HLS/M3U8 (Live video feeds)
*   **APIs:** Telegram Bot API, Cloudflare R2 (Storage fallback)
*   **Scheduling:** macOS LaunchAgent (`com.stoneage.daily.plist`) for precise scheduled execution.

## 📈 Performance & Scalability

The architecture is designed to be lightweight and portable. By offloading media processing to FFmpeg and using Telegram's free Bot API, the bot operates at zero API cost while maintaining continuous automated updates.

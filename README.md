# StoneAge: Automated Media Synthesis & Data Pipeline

**StoneAge** is a high-frequency automated content engine designed to synthesize real-time market data, live audio streams, and traffic infrastructure feeds into dynamic, high-quality video updates for X (Twitter).

## 🛠 Technical Overview

This project showcases a complete media lifecycle—from raw data ingestion to automated social media distribution—built with a focus on reliability and API efficiency.

### Key Technical Challenges & Solutions:

*   **Real-Time Media Mixing (FFmpeg):** Orchestrates complex multi-track synthesis by blending highway ambient audio, live MP3 radio streams (Bloomberg, WNYC, NPR), and HLS video feeds from VDOT traffic cameras.
*   **Dynamic Data Overlay:** Implements a custom graphics layer using Python (Pillow) to render real-time Brent Crude Oil and Virginia Gas price fluctuations directly onto video frames.
*   **Robust X API Integration (Media v1.1 & v2):** Implements a resilient **Chunked Media Upload** protocol. This handles the asynchronous nature of Twitter's video processing, including `INIT`, `APPEND`, `FINALIZE`, and `STATUS` polling to ensure 10MB+ video stability.
*   **Automated Lifecycle Management:** Features an atomic "Delete-and-Post" strategy. The bot programmatically cleans up previous status updates before publishing new ones, maintaining a clean, single-post profile state.
*   **Fault-Tolerant Audio Processing:** Includes an automated "Preflight & Validation" system for radio streams, using Silero VAD (Voice Activity Detection) to ensure audio quality before recording.

## 🏗 Stack & Infrastructure

*   **Core Logic:** Python 3.x
*   **Media Processing:** FFmpeg (Subprocess orchestration)
*   **Data Sources:** yfinance (Market data), Cloudscraper (Web scraping), HLS/M3U8 (Live video feeds)
*   **APIs:** X (Twitter) API v1.1/v2, AWS S3/R2 (Storage fallback)
*   **Scheduling:** Crontab-based automation for precise 9:01 & 14:31 EST execution.

## 📈 Performance & Scalability

The architecture is designed to be lightweight and portable. By offloading heavy media processing to FFmpeg and using a "Pay-as-you-go" API model, the bot operates at a near-zero cost while maintaining 100% uptime on local or cloud-based Unix environments.

# LUMEN

Autonomous daily music video track generator. Mixes drum loops with live radio stream (NPR), overlays video from VDOT (Virginia) traffic cameras, and adds subtitle with camera code.

---

## What It Generates

One track per scheduled run (MP4 or WAV):

- **Drums** — loop from library (time-stretched to 116 BPM)
- **Radio** — live NPR stream (synchronized with drums)
- **Mix** — drums at 0 dB + radio at −10 dB (before mastering)
- **Video** — ~30+ sec recording from random VDOT camera (1280×850, up to 5 retry attempts with different cameras if unavailable)
- **Subtitle** — camera code in format `PRBRCK▶VA64103MON` (bottom of video, 55px)
- **Mastering** — normalization to −3 dB peak + Limiter(threshold=−1.0)
- **R2 Upload** — final MP4 uploaded to Cloudflare R2 storage
- **Webhook Notification** — Make.com webhook triggered with video URL and metadata

---

## Project Structure

```
lumen/
├── lumen_generator.py          # Main generator
├── HomeVideo-Regular.ttf       # Font for subtitles
├── requirements.txt            # Python dependencies
├── README.md                   # This file
│
├── samples/
│   └── full drum/              # Drum loop library
│       └── Bpm{N}_*.wav        # Files MUST contain BPM in name
│
├── private/                    # 🔒 NOT committed to git
│   ├── camera_catalog.csv      # VDOT camera catalog (generated, not committed)
│   ├── camera_pool.json        # Validated cameras (generated, not committed)
│   ├── radio_catalog.csv       # Radio stations catalog (generated, not committed)
│   └── radio_pool.json         # Validated radio stations (generated, not committed)
│
├── streams/
│   ├── lumen_cam_extractor.py       # VDOT API → camera_pool.json (validates connection)
│   ├── make_camera_catalog.py       # camera_pool.json → private/camera_catalog.csv
│   ├── lumen_radio_extractor.py     # Radio Browser API → private/radio_pool.json (connection check)
│   ├── make_radio_catalog.py        # private/radio_pool.json → private/radio_catalog.csv (tag filter)
│   ├── clean_radio_catalog.py       # Regenerate catalog with different tag filters
│   ├── radio_stats.py               # Analyze radio pool by region/country
│   ├── probe_cam.py                 # Utility to check camera resolution
│   ├── radio_tags.md                # Include/exclude tag configuration
│   └── ...                          # Other utilities
│
├── output/
│   ├── *.mp4                   # Finished video tracks
│   ├── radio_raw/              # Archive of raw radio recordings
│   ├── tracks/                 # WAV mixes without video (names as subtitles)
│   ├── old/                    # User folder (not touched by script)
│   └── sample_rotation.json    # Sample rotation state
│
└── .gitignore                  # Git config (output/, private/ excluded)
```

**Important:** The `private/` folder contains generated catalog and pool files that are specific to your setup (API validation results, local camera URLs, etc.). This folder is **never committed to git** — each installation builds its own copy.

---

## Automated Execution (macOS)

Use LaunchAgent for scheduled generator execution:

### Installation

```bash
# 1. Copy plist to LaunchAgents
cp com.lumen.daily.plist ~/Library/LaunchAgents/

# 2. Create logs directory (if doesn't exist)
mkdir -p ~/Library/Logs

# 3. Create .env file with R2 and Make.com credentials
# (see Environment Variables section above)
cp .env.example .env  # if available, or create manually

# 4. Load into launchd
launchctl load ~/Library/LaunchAgents/com.lumen.daily.plist
```

**Note:** The plist uses `/opt/miniconda3/bin/python3` as the interpreter. Adjust this path in the plist if your Python installation is in a different location.

### Automation

Once installed and configured:
- **Runs according to LaunchAgent schedule** configured via `set_lumen_schedule.sh`
- **Generates one track** with fresh drum loop and random VDOT camera
- **Uploads to R2** automatically
- **Notifies Make.com** webhook with video metadata
- **Logs all activity** to `~/Library/Logs/lumen.log` and `lumen.error.log`

No manual intervention needed — set it and forget it.

### Check Status

```bash
# Check if loaded and running
launchctl list | grep lumen

# View real-time logs
tail -f ~/Library/Logs/lumen.log
tail -f ~/Library/Logs/lumen.error.log

# Manually trigger a run (for testing)
launchctl kickstart -k gui/$(id -u)/com.lumen.daily
```

### Stop

```bash
launchctl unload ~/Library/LaunchAgents/com.lumen.daily.plist
```

### Configure Execution Time

Use `set_lumen_schedule.sh` to control when the generator runs:

```bash
# Run at 15:30 (3:30 PM) every day
./set_lumen_schedule.sh HOURS="15" MIN="30" SEC="0"

# Run at multiple times (e.g., 8 AM, 2 PM, 8 PM with 20-sec delay before radio record)
./set_lumen_schedule.sh HOURS="8 14 20" MIN="29" SEC="20"

# Run every hour at minute 1, with 30-second sleep before radio (effective start: :01:30)
./set_lumen_schedule.sh HOURS="0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23" MIN="1" SEC="30"
```

**Parameters:**
- `HOURS=` — space-separated list of hours (0–23)
- `MIN=` — minute (0–59)
- `SEC=` — additional delay in seconds before the generator launches

**Note:** The generator itself has ~30–40 seconds of processing time (drum loading, time-stretch, looping) before radio recording starts. Adjust `SEC=` to control when the first radio frame is captured.

**Important:**
- Seconds are not shown in `launchctl output` — the schedule shows only Hour:Minute
- Actual run time = Hour:Minute + SEC (sleep delay)

### Environment Variables

To send results to Make.com and upload to R2, create `.env` in project root:

```bash
# Optional: Make.com webhook
MAKE_WEBHOOK_URL=https://hook.us2.make.com/...

# Required: R2 (Cloudflare) storage configuration
R2_ENDPOINT=https://...r2.cloudflarestorage.com
R2_BUCKET=...
R2_KEY_ID=...
R2_APP_KEY=...
R2_PUBLIC_URL=https://pub-...r2.dev
```

**Behavior:**
- R2 upload happens automatically after each generation
- Make webhook is optional — if URL is empty, upload still works, webhook is skipped
- If R2 credentials are missing, upload is skipped with message "[notify] R2 not configured"
- If Make.com URL is empty, webhook is skipped without notice

**Webhook payload** (sent to Make.com):
```json
{
  "url": "https://pub-...r2.dev/20260324_bpm116_...mp4",
  "subtitle": "VA64103MON",
  "description": "I-95 / MM 64.1 / NB",
  "jurisdiction": "Fairfax",
  "radio_name": "NPR ICE",
  "radio_countrycode": "US"
}
```

**Note:** `radio_name` is the station name (or "UNKNOWN" if unavailable). `radio_countrycode` is the country code (or empty string ""). Both fields are always present (never None).

---

## Quick Start

### 1. Install Dependencies

#### Python dependencies
```bash
pip install -r requirements.txt
```

#### System dependencies (required)
- **ffmpeg** — for video and radio recording

#### System dependencies (optional)
- **rubberband** (CLI) — required for pyrubberband (drum time-stretch)
  - macOS: `brew install rubberband`
  - Linux: `apt-get install rubberband-cli`

#### Optional Python dependencies
- **silero-vad + torch** — for speech detection during radio validation (validates that streams contain speech, not just music)
  - Install with: `pip install torch silero-vad`
  - If not installed, loudness check still works; speech check is skipped

#### Only for utilities
- **ffprobe** — required only for `streams/probe_cam.py`

### 2. Generate Track

```bash
python3 lumen_generator.py
```

Creates:
- `output/YYYYMMDD_bpm116_drumname_camID.mp4` — final video with subtitle
- `output/tracks/PRBRCK▶VA64103MON.wav` — audio mix (drum + radio)
- `output/radio_raw/YYYYMMDD_HHMMSS_NPR_ICE_Xs.wav` — radio archive

---

## Subtitle Format

`PRBRCK▶{route_code}{cam_id_last_2}{day_abbr}`

Example for camera ID 4485, route "I-95", Monday:
- Route Code from CSV: `I95`
- Last 2 digits of ID: `85`
- Day: `MON`
- **Result:** `PRBRCK▶I9585MON`

Days: MON, THE (Tuesday), WED, THU, FRI, SAT, SUN

---

## Sample Rotation

Drum loops are selected in round-robin order:

1. On first run — all files are randomly shuffled
2. Each run takes the next in queue
3. After successful export, sample is removed from queue
4. When queue exhausted — new shuffle (new cycle)
5. State is stored in `output/sample_rotation.json`

**Important:** sample files **MUST** contain pattern `Bpm{N}_` in name:
- ✅ `Bpm125_Introvert_full.wav` — accepted
- ❌ `Introvert_full.wav` — rejected

---

## Video Parameters

| Parameter | Value |
|-----------|-------|
| Resolution | 1280×850 |
| Duration | 30+ sec (nearest whole number of loop repeats) |
| Video codec | H.264 (libx264, CRF 23) |
| Audio codec | AAC (192 kbps) |
| FPS | Original from camera stream (not normalized) |
| Subtitle size | 55px, color D1D1D1, center aligned, 30px from bottom |
| Crop from top | 130px (scaled from 1280×960 source) |
| Video fallback | Up to 5 retry attempts with different cameras if unavailable |

---

## Configuration

All parameters at the top of `lumen_generator.py`:

```python
TARGET_BPM     = 116           # Target BPM for time-stretch
DURATION_MS    = 30_000        # Track length (ms)
RADIO_URL      = "..."         # NPR stream
RADIO_NAME     = "NPR_ICE"     # For archive naming
VIDEO_TIMEOUT  = 60            # Max video recording time (sec)
```

---

## Updating Camera Catalog

When you need to expand the available camera database or update VDOT data:

### Official Process

```bash
# 1. Download fresh data from VDOT API
python3 streams/lumen_cam_extractor.py

# 2. Transform into working catalog
python3 streams/make_camera_catalog.py
```

### Pipeline

```
VDOT API
  ↓
lumen_cam_extractor.py → private/camera_pool.json (intermediate source of truth: validated cameras)
                      ↓
                      make_camera_catalog.py → private/camera_catalog.csv (runtime subset)
                                            ↓
                                            lumen_generator.py (reads CSV at runtime)
```

**Key point:** generator only reads `private/camera_catalog.csv`, never touches `private/camera_pool.json` directly.

### File Roles

| File | Role | Location |
|------|------|----------|
| `camera_pool.json` | Intermediate source of truth (validated cameras) | `private/` |
| `camera_catalog.csv` | Runtime subset for generator | `private/` |

**Note:** Both files are local only and excluded from git (see `.gitignore`). Each installation builds its own copy via extractors and builders. They should never be committed to the repository.

### Diagnostics (optional)

To check camera availability (not part of main pipeline):

```bash
python3 streams/probe_cam.py <URL>             # single camera resolution
```

---

## Updating Radio Catalog

Three-stage process with separate include/exclude filtering:

### Full Refresh Pipeline

```
Radio Browser API
  ↓
lumen_radio_extractor.py
  (fetches by include-tags from radio_tags.md)
  ↓
private/radio_pool.json
  (raw pool: all stations matching include criteria)
  ↓
make_radio_catalog.py
  (filters pool by exclude-tags from radio_tags.md)
  ↓
private/radio_catalog.csv
  (working catalog: used by lumen_generator.py)
```

### Process

#### 1. Build Pool (monthly/quarterly)
```bash
# Fetch stations from Radio Browser API matching include-tags
python3 streams/lumen_radio_extractor.py
# → creates/updates private/radio_pool.json
```

#### 2. Generate Catalog (after step 1 or tag edit)
```bash
# Apply exclude-tags filter to pool
python3 streams/make_radio_catalog.py
# → creates/updates private/radio_catalog.csv
```

#### 3. Update Catalog Only (tag edit without re-fetching)
```bash
# Re-filter existing pool with new exclude-tags
# Does NOT re-fetch from API, does NOT modify pool
python3 streams/clean_radio_catalog.py
# → updates private/radio_catalog.csv only
```

#### 4. Update Runtime Filters (country/language)
No action needed! Runtime filters (`include_countries`, `exclude_countries`, `include_languages`, `exclude_languages`) are applied automatically when the generator runs:
```bash
# Just edit streams/radio_tags.md and the next run will use new filters
# No need to regenerate CSV or re-fetch from API
# Filters take effect immediately on next generation
```

### File Roles

| File | Role | Uses | Location |
|------|------|------|----------|
| `radio_tags.md` | Include/exclude tags + country/language filters | Configuration | `streams/` |
| `radio_pool.json` | All stations matching include-tags | Extractor → Catalog | `private/` |
| `radio_catalog.csv` | Pool filtered by exclude-tags | Generator | `private/` |

### Filter Sections in radio_tags.md

| Section | Level | Type | Matches | Example |
|---------|-------|------|---------|---------|
| `## include` | Extractor | Include | Station tags | `news`, `talk`, `speech` |
| `## exclude` | Catalog-time | Exclude | Tags OR name (substring) | `music`, `entertainment` |
| `## include_countries` | Runtime | Include (whitelist) | Country codes (exact) | `US`, `GB` |
| `## exclude_countries` | Runtime | Exclude (blacklist) | Country codes (exact) | `CN`, `KP` |
| `## include_languages` | Runtime | Include (whitelist) | Language field (substring) | `english`, `spanish` |
| `## exclude_languages` | Runtime | Exclude (blacklist) | Language field (substring) | `chinese`, `mandarin` |

**Multi-level filtering:**
1. **Extractor** (`lumen_radio_extractor.py`) — fetches stations matching `## include` tags
2. **Catalog-time** (`make_radio_catalog.py`) — filters by `## exclude` tags before CSV export
3. **Runtime** (`lumen_generator.py`) — applies include/exclude filters when loading pool:
   - If `include_countries` defined → accept only these countries
   - If `exclude_countries` defined → reject these countries
   - If `include_languages` defined → accept only these languages
   - If `exclude_languages` defined → reject these languages

**Include vs Exclude:**
- **Include (whitelist):** if defined, ONLY matching items are accepted
- **Exclude (blacklist):** if defined, matching items are rejected
- **Both defined:** include is checked first, then exclude is applied

### Filter Configuration Examples

**Example 1: Only English-speaking US/UK stations**
```
## include_countries
US|GB

## include_languages
english
```

**Example 2: European English news (excluding some countries)**
```
## include_countries
GB|DE|FR|ES|IT|NL|BE|SE|NO|DK

## include_languages
english

## exclude_countries
RU|BY
```

**Example 3: North American news (exclude music-only countries)**
```
## include_countries
US|CA|MX

## exclude_countries
(leave empty - include_countries already specifies whitelist)
```

**Example 4: All news except Chinese and Russian**
```
## include_countries
(leave empty - accept all)

## include_languages
(leave empty - accept all)

## exclude_countries
CN|RU|KP

## exclude_languages
chinese|mandarin|russian
```

### CSV Field Format

The generator reads `radio_catalog.csv` with flexible field name matching and exclusion filtering:
- **Required:** `name`, `url` (must have non-empty values)
- **Optional:** `country`, `countrycode`, `language`, `tags`
- Field names are case-insensitive (`Name`/`name`/`NAME` all work)
- Missing `countrycode` defaults to `"XX"` (unknown)
- NPR fallback uses countrycode `"US"`

**Filtering (during load):**
- If `include_countries` defined → only stations with matching country codes are accepted
- If `exclude_countries` defined → stations with these codes are rejected
- If `include_languages` defined → only stations with matching languages are accepted
- If `exclude_languages` defined → stations with these languages are rejected
- Include filters are applied first (whitelist), then exclude filters (blacklist)

Example CSV format:
```
name,url,country,countrycode,language,tags
NPR ICE,https://npr-ice.streamguys1.com/live.mp3,United States,US,English,news
BBC Radio 4,https://...,United Kingdom,GB,English,talk
```

### Runtime Validation (lumen_generator.py)

Each time generator runs:

**Pre-validation: Load filtered pool**
- Read `radio_catalog.csv` with flexible field name matching
- Apply include/exclude filters from `radio_tags.md`:
  - If `include_countries` defined → accept only these countries
  - If `exclude_countries` defined → reject these countries
  - If `include_languages` defined → accept only these languages
  - If `exclude_languages` defined → reject these languages
- Result: `filtered_pool`
- **If filtered_pool is empty** → skip directly to NPR fallback

**Phase 1: Random filtered pool stations (up to 5 attempts)**
- Only runs if `filtered_pool` is not empty
- Picks random stations from filtered pool (same station may be selected multiple times)

For each attempt:
1. **Connectivity check** — verify ffmpeg can connect (preflight via ffmpeg)
2. **Content validation** — record 15 seconds:
   - Check loudness (dBFS >= -32) — always performed
   - Check speech ratio (>= 65% via Silero VAD) — only if silero-vad/torch installed
3. **Recording** — if validation passes, record full duration
4. **Retry logic** — if validation fails, pick another random station (up to 5 attempts total)

**Phase 2: NPR fallback (if pool empty or all 5 attempts fail)**
- If `filtered_pool` is empty → skip directly to NPR (no phase 1)
- If all 5 random pool attempts fail → try hardcoded NPR stream (RADIO_URL)
- Run same validation checks (connectivity + loudness + optional speech detection)
- If NPR passes → use it
- If NPR fails → **ABORT generation** (no file saved or posted)

**Validation behavior:**
- If silero-vad/torch are **installed** → validates both loudness AND speech
- If silero-vad/torch are **not installed** → validates loudness only (speech check skipped with log message)

**Result:**
- ✅ If any stream passes validation → generate video + audio track
- ❌ If all sources fail → [FATAL] error, generation stops

**Note:** `radio_pool.json` and `radio_catalog.csv` are local-only (never committed). `radio_tags.md` is committed (controls filtering).

---

## Utilities and Debugging

These tools are **not part of the main pipeline**, used for diagnostics and debugging:

### probe_cam.py

Check actual camera resolution:

```bash
python3 streams/probe_cam.py "https://media-sfs8.vdotcameras.com:443/rtplive/NO0001/playlist.m3u8"
```

Output:
```
Resolution: 1280 x 960
Aspect ratio: 1.333
After crop 160px top: 1280 x 800
After crop 80px bottom too: 1280 x 720
```

---

## R2 and Make.com Integration

After each successful generation, the system automatically:

1. **Uploads to Cloudflare R2** — final MP4 stored in cloud with public URL
2. **Sends webhook to Make.com** — notifies automation platform with:
   - `url` — public R2 URL to the video file
   - `subtitle` — camera code (e.g., `VA64103MON`)
   - `description` — camera location (e.g., `I-95 / MM 64.1 / NB`)
   - `jurisdiction` — administrative region (e.g., `Fairfax`)
   - `radio_name` — selected radio station name (or "UNKNOWN" if unavailable)
   - `radio_countrycode` — country code of station (or empty string "")

This enables downstream workflows in Make.com (posting to social media, databases, notifications, etc.).

**Optional behavior:** If R2 credentials are missing, upload is skipped with message "[notify] R2 not configured". If Make.com URL is empty, webhook is not sent but R2 upload still happens.

---

## Mastering

1. Normalization to −3 dB peak (based on maximum amplitude)
2. Limiter with threshold = −1.0 dB (clipping protection)

---

## Dependencies

### Python (in requirements.txt)
- **pydub** — audio processing
- **pedalboard** — mastering (Limiter)
- **numpy** — numerical operations
- **pyrubberband** — time-stretch (R3 quality)
- **Pillow** — PNG subtitle creation

#### Optional (for speech detection)
- **torch** — machine learning framework (required for Silero VAD)
- **silero-vad** — voice activity detection (speech vs music)

#### Optional (for Make.com + R2 integration)
- **python-dotenv** — load environment variables from .env
- **boto3** — AWS S3-compatible uploads to Cloudflare R2
- **requests** — HTTP requests for Make.com webhook

### System
- **ffmpeg** — video and radio recording
- **rubberband** (CLI) — backend for time-stretch

---

## Notes

- **Private data files (`private/`) are never committed to the repository.** These contain API validation results specific to your installation:
  - `camera_catalog.csv` and `camera_pool.json` (VDOT cameras)
  - `radio_catalog.csv` and `radio_pool.json` (Radio Browser stations)
  - Each installation builds its own via extractors
- Configuration files (`streams/radio_tags.md`) **are** committed — these control filtering behavior
- Cameras are loaded from `private/camera_catalog.csv` (built from `private/camera_pool.json`)
- Radio stations are loaded from `private/radio_catalog.csv` (built from `private/radio_pool.json` and filtered by `streams/radio_tags.md`)
- Raw radio is archived in `output/radio_raw/` for analysis
- **If all radio streams fail** (5 pool stations + NPR fallback) — generation is **aborted** with error (no file saved or posted)
- If video recording fails — only WAV is saved
- If audio mastering fails — generation is interrupted
- `output/old/` folder is not touched by script (manual archiving)

---

## Future Plans (GPT recommendation)

When project scales (automation, multiple users, critical data):

### 1. Guardrail on catalog update

```python
# streams/make_camera_catalog.py
if len(camera_pool) < 20:
    raise RuntimeError("Camera pool validation failed: too few cameras")
```

Prevents overwriting `camera_catalog.csv` with empty or corrupted pool.

### 2. Backup before source of truth change

```python
# streams/lumen_cam_extractor.py
import shutil
backup_path = f"{camera_pool_path}.backup.{datetime.now().isoformat()}"
shutil.copy(camera_pool_path, backup_path)
```

Protection against data loss during API or script failure.

### 3. Single entry point for catalog update

```bash
# streams/update_catalog.py
python3 streams/update_catalog.py
```

Instead of manual sequence:
1. `lumen_cam_extractor.py`
2. `make_camera_catalog.py`

Ensures both steps are executed in correct order with guardrails.

---

**Status:** Currently the project is **"stable personal system"**.
After implementing these three points → **"production-ready"**.

---

## License

Closed project for VDOT traffic visualization.

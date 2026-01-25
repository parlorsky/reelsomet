# CLAUDE.md

Instructions for Claude Code when working with this repository.

## Project Overview

Video content toolkit for Instagram Reels:
- Download reels via snapinsta.to
- Generate TTS voiceovers via KIE.ai (ElevenLabs V3)
- Create styled word-by-word animated subtitles
- Extract word timestamps via OpenAI Whisper

## File Organization

```
reelsomet/
├── scripts/           # All Python scripts
│   ├── styled_subtitles.py      # Main subtitle generator
│   ├── kie_tts.py               # TTS via KIE.ai
│   ├── audio_to_word_timestamps.py  # Whisper timestamps
│   ├── background_catalog.py    # Background video cataloger
│   ├── video_analyzer.py        # Frame extraction
│   ├── download_from_html.py    # Instagram downloader
│   ├── instagram_downloader.py  # Core downloader
│   ├── instagram_profile_scraper.py
│   ├── instagram_account_manager.py
│   └── rename_by_popularity.py
├── downloads/         # Output files
│   ├── fonts/         # Montserrat-Bold.ttf
│   ├── music/         # Background music
│   └── backgrounds/   # Background videos + catalog.json
│       ├── catalog.json    # Video metadata catalog
│       ├── thumbnails/     # Auto-generated previews
│       └── frames/         # Extracted frames for analysis
├── input/             # Input scripts and URLs
├── docs/              # Documentation
├── .env               # API keys (not in git)
├── CLAUDE.md          # This file
└── README.md          # Project readme
```

## Core Scripts

### styled_subtitles.py - Main Feature
Creates videos with animated word-by-word subtitles.

```bash
# Basic usage
python scripts/styled_subtitles.py script.txt audio.mp3 -o output.mp4

# Fast parallel rendering (recommended)
python scripts/styled_subtitles.py script.txt audio.mp3 --threads 30 -o output.mp4

# With GPU encoding (NVIDIA)
python scripts/styled_subtitles.py script.txt audio.mp3 --threads 30 --gpu nvenc -o output.mp4
```

**Performance options:**
- `--threads N` - parallel frame rendering (use CPU cores, e.g. 16-30)
- `--gpu nvenc` - NVIDIA GPU encoding
- `--gpu amd` - AMD GPU encoding
- `--gpu intel` - Intel QuickSync encoding

**Speed:** 60-sec video renders in ~30 seconds with `--threads 30`

**Markup syntax:**
- `**word**` - accent (110px, white, glow)
- `*word*` - highlight (88px, yellow)
- `_word_` - muted (58px, gray)
- `[c:color]word[/]` - custom color
- `---` - page break

**Colors:** white, gray, red, green, blue, yellow, orange, purple, pink, cyan, coral, lime, gold, rose

### kie_tts.py - TTS Generation
```bash
python scripts/kie_tts.py "Text" -v Callum -o voice.mp3
python scripts/kie_tts.py --voices  # list voices
```

**Voices:** Adam, Alice, Bill, Brian, Callum, Charlie, Chris, Daniel, Eric, George, Harry, Jessica, Laura, Liam, Lily, Matilda, River, Roger, Sarah, Will

**Emotion tags:** `[whispers]` `[shouts]` `[sad]` `[happy]` `[sarcastic]` `[pause]` `[laughs]` `[sighs]`

### audio_to_word_timestamps.py - Whisper
```bash
python scripts/audio_to_word_timestamps.py audio.mp3 -o timestamps.json
```

### video_analyzer.py - Frame Extraction
```bash
python scripts/video_analyzer.py video.mp4 -o frames -i 2
```

### background_catalog.py - Background Management
Analyzes video backgrounds for automatic selection.

```bash
# Scan all backgrounds and create catalog
python scripts/background_catalog.py scan

# Analyze single video
python scripts/background_catalog.py analyze video.mp4

# Search by criteria
python scripts/background_catalog.py search --mood calm --style lofi
```

**Catalog location:** `downloads/backgrounds/catalog.json`

**Using backgrounds with styled_subtitles:**
```bash
# Use background directory with catalog
python scripts/styled_subtitles.py script.txt audio.mp3 --bg-dir downloads/backgrounds -o output.mp4

# Single background video
python scripts/styled_subtitles.py script.txt audio.mp3 --bg background.mp4 -o output.mp4

# Adjust background effects
--darken 0.65       # darken factor (default: 0.65)
--desaturate 0.25   # desaturate factor (default: 0.25)
```

**Catalog structure:**
- `technical`: duration, resolution, fps, codec
- `visual`: dominant_colors, brightness, contrast, saturation, motion_speed, text_friendly
- `semantic`: style, mood, elements, color_palette, time_of_day
- `timeline`: scene descriptions with timestamps

## Workflow: Create Styled Video

1. Write script in `input/script.txt` with markup
2. Generate TTS:
   ```bash
   python scripts/kie_tts.py input/script.txt -v Callum -o downloads/voice.mp3
   ```
3. Extract timestamps:
   ```bash
   python scripts/audio_to_word_timestamps.py downloads/voice.mp3
   ```
4. Create video:
   ```bash
   python scripts/styled_subtitles.py input/script.txt downloads/voice.mp3 --threads 30 -o downloads/final.mp4
   ```

## Environment

`.env` in project root:
```
OPENAI_API_KEY=sk-...
KIE_API_KEY=...
```

## Key Paths

```
Font: downloads/fonts/Montserrat-Bold.ttf
FFmpeg: imageio_ffmpeg auto-detected
```

## Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

Core: moviepy, pillow, numpy, openai, aiohttp, playwright

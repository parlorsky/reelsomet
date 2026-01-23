# Reelsomet

Instagram video toolkit: download reels, generate TTS voiceovers, create styled word-by-word subtitles.

## Features

- **Instagram Downloader** - Download reels/posts via snapinsta.to with auto-proxy
- **TTS Generation** - KIE.ai ElevenLabs V3 with emotion tags
- **Word Timestamps** - Extract word-level timing via OpenAI Whisper
- **Styled Subtitles** - Dynamic word-by-word video subtitles with custom styling

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Setup

Create `.env` in project root:
```
OPENAI_API_KEY=sk-...
KIE_API_KEY=...
```

## Usage

### Styled Subtitles (Main Feature)

Create videos with animated word-by-word subtitles:

```bash
python scripts/styled_subtitles.py script.txt audio.mp3 -o output.mp4
```

**Script markup syntax:**
```
**word**           - accent (large, white, bold)
*word*             - highlight (medium, yellow)
_word_             - muted (small, gray)
[c:red]word[/]     - custom color (red, cyan, pink, orange, etc.)
[c:FF5500]word[/]  - hex color
---                - page break (clear screen)
```

**Available colors:** white, gray, red, green, blue, yellow, orange, purple, pink, cyan, coral, lime, gold, rose

### TTS Generation

```bash
python scripts/kie_tts.py "Your text here" -v Callum -o voiceover.mp3
python scripts/kie_tts.py script.txt -v Jessica --voices  # list voices
```

**Emotion tags:** `[whispers]` `[shouts]` `[sad]` `[happy]` `[sarcastic]` `[pause]` `[laughs]` `[sighs]`

### Word Timestamps

```bash
python scripts/audio_to_word_timestamps.py audio.mp3 -o timestamps.json
```

### Instagram Download

```bash
python scripts/download_from_html.py urls.txt -o downloads/folder --transcribe
python scripts/download_from_html.py urls.txt --proxy  # with SOCKS5 proxies
```

### Video Frame Analysis

```bash
python scripts/video_analyzer.py video.mp4 -o frames -i 2  # frame every 2 sec
```

## Project Structure

```
reelsomet/
├── scripts/
│   ├── styled_subtitles.py      # Main subtitle generator
│   ├── kie_tts.py               # TTS via KIE.ai
│   ├── audio_to_word_timestamps.py  # Whisper timestamps
│   ├── video_analyzer.py        # Frame extraction
│   ├── download_from_html.py    # Instagram downloader
│   ├── instagram_downloader.py  # Core downloader
│   └── instagram_profile_scraper.py  # Profile scraper
├── input/                       # Input scripts
├── downloads/                   # Output files
│   ├── fonts/                   # Montserrat-Bold.ttf
│   └── music/                   # Background music
├── docs/                        # Documentation
└── CLAUDE.md                    # AI assistant instructions
```

## Example Workflow

1. Write styled script in `input/my_script.txt`
2. Generate voiceover: `python scripts/kie_tts.py input/my_script.txt -v Callum -o downloads/voice.mp3`
3. Extract timestamps: `python scripts/audio_to_word_timestamps.py downloads/voice.mp3`
4. Create video: `python scripts/styled_subtitles.py input/my_script.txt downloads/voice.mp3 -o downloads/final.mp4`

## Dependencies

- **moviepy** - Video editing
- **pillow** - Image processing
- **openai** - Whisper transcription
- **playwright** - Browser automation
- **aiohttp** - Async HTTP

## License

MIT

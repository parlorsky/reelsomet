"""
Audio to Word Timestamps - Extract word-level timing from audio using Whisper API

Использование:
    python scripts/audio_to_word_timestamps.py audio.mp3 -o timestamps.json

Требует OPENAI_API_KEY в .env
"""

import os
import sys
import json
import argparse
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import httpx

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv(Path(__file__).parent.parent / ".env")


def extract_word_timestamps(audio_path: str, language: str = "ru") -> list[dict]:
    """
    Extract word-level timestamps from audio using Whisper API.

    Args:
        audio_path: Path to audio file (mp3, wav, etc.)
        language: Language code (ru, en, etc.)

    Returns:
        List of {word, start, end} dicts
    """
    client = OpenAI(
        timeout=httpx.Timeout(120.0, connect=30.0)
    )

    print(f"Processing: {audio_path}")

    with open(audio_path, "rb") as audio_file:
        # Use verbose_json response format with word timestamps
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["word"]
        )

    # Extract word-level timestamps
    words = []
    if hasattr(response, 'words') and response.words:
        for w in response.words:
            words.append({
                "word": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3)
            })

    return words, response.text


def save_timestamps(words: list[dict], output_path: str):
    """Save word timestamps to JSON."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(words)} word timestamps to {output_path}")


def print_preview(words: list[dict], count: int = 15):
    """Print preview of word timestamps."""
    print(f"\nWord timestamps ({len(words)} total):")
    print("-" * 50)
    for w in words[:count]:
        duration = w['end'] - w['start']
        print(f"  {w['start']:6.2f}s - {w['end']:6.2f}s ({duration:.2f}s): {w['word']}")
    if len(words) > count:
        print(f"  ... и ещё {len(words) - count} слов")


def main():
    parser = argparse.ArgumentParser(description="Extract word timestamps from audio")
    parser.add_argument("audio", help="Path to audio file")
    parser.add_argument("-o", "--output", help="Output JSON file (default: same name + _timestamps.json)")
    parser.add_argument("-l", "--lang", default="ru", help="Language code (ru, en, etc.)")
    parser.add_argument("--preview", type=int, default=15, help="Number of words to preview")
    args = parser.parse_args()

    # Default output path
    if not args.output:
        audio_path = Path(args.audio)
        args.output = str(audio_path.parent / f"{audio_path.stem}_timestamps.json")

    # Extract timestamps
    words, full_text = extract_word_timestamps(args.audio, args.lang)

    if not words:
        print("Warning: No word timestamps returned. Check audio quality.")
        return

    # Print full transcription
    print(f"\nTranscription:\n{full_text}\n")

    # Preview
    print_preview(words, args.preview)

    # Calculate total duration
    if words:
        duration = words[-1]['end']
        wpm = len(words) / (duration / 60)
        print(f"\nDuration: {duration:.1f}s | Words: {len(words)} | WPM: {wpm:.0f}")

    # Save
    save_timestamps(words, args.output)

    return words


if __name__ == "__main__":
    main()

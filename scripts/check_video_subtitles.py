"""
Check rendered video for missing subtitles by extracting frames.
Compares expected words at each timestamp with actual frame content.

Usage:
    python scripts/check_video_subtitles.py video.mp4 script.txt timestamps.json
"""

import sys
import os
import json
import re
import tempfile
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from moviepy import VideoFileClip
except ImportError:
    from moviepy.editor import VideoFileClip

from PIL import Image
import numpy as np


def parse_script_words(script_path: str) -> list:
    """Extract words from styled script with page info."""
    with open(script_path, 'r', encoding='utf-8') as f:
        text = f.read()

    words = []
    page_idx = 0

    parts = re.split(r'\n*---\n*', text)

    for part in parts:
        part = part.strip()
        if not part:
            page_idx += 1
            continue

        pattern = r'(\*\*[^*]+\*\*)|(\*[^*]+\*)|(_[^_]+_)|(\[[^\]]+\][^\[]+\[/\])|(\S+)'
        tokens = re.findall(pattern, part, re.VERBOSE)

        for token_tuple in tokens:
            token = next(t for t in token_tuple if t)

            if token.startswith('**'):
                inner = token[2:-2]
            elif token.startswith('*'):
                inner = token[1:-1]
            elif token.startswith('_'):
                inner = token[1:-1]
            elif token.startswith('['):
                m = re.match(r'\[([^\]]+)\](.+)\[/\]', token)
                inner = m.group(2) if m else token
            else:
                inner = token

            if inner.strip():
                words.append({'text': inner.strip(), 'page': page_idx})

        page_idx += 1

    return words


def check_frame_has_content(frame: np.ndarray, threshold: float = 0.1) -> bool:
    """
    Check if frame has subtitle content (bright pixels in center area).
    Returns True if subtitles likely present.
    """
    h, w = frame.shape[:2]

    # Check center area where subtitles appear (middle 60% vertically, 80% horizontally)
    y1, y2 = int(h * 0.2), int(h * 0.8)
    x1, x2 = int(w * 0.1), int(w * 0.9)

    center = frame[y1:y2, x1:x2]

    # Convert to grayscale if needed
    if len(center.shape) == 3:
        gray = np.mean(center, axis=2)
    else:
        gray = center

    # Count bright pixels (subtitle text is white/bright)
    bright_pixels = np.sum(gray > 200) / gray.size

    return bright_pixels > threshold


def extract_and_check_frames(video_path: str, timestamps: list, script_words: list):
    """
    Extract frames at word timestamps and check for subtitle presence.
    """
    print(f"Loading video: {video_path}")
    clip = VideoFileClip(video_path)
    duration = clip.duration
    print(f"Video duration: {duration:.2f}s")

    # Match words to timestamps
    word_times = []
    for i, ts in enumerate(timestamps):
        if i < len(script_words):
            word_times.append({
                'word': script_words[i]['text'],
                'page': script_words[i]['page'],
                'start': ts['start'],
                'end': ts['end'],
                'ts_word': ts['word']
            })

    print(f"\nChecking {len(word_times)} word timestamps...")
    print("="*70)

    issues = []
    last_good_time = 0

    # Check every second + at each word start
    check_times = set()
    for wt in word_times:
        check_times.add(round(wt['start'], 1))
        check_times.add(round((wt['start'] + wt['end']) / 2, 1))  # midpoint

    # Also check every 2 seconds
    t = 0
    while t < duration:
        check_times.add(round(t, 1))
        t += 2

    check_times = sorted(check_times)

    prev_has_content = True
    first_missing = None

    for t in check_times:
        if t >= duration:
            continue

        try:
            frame = clip.get_frame(t)
            has_content = check_frame_has_content(frame, threshold=0.005)

            # Find what word should be showing at this time
            current_word = None
            for wt in word_times:
                if wt['start'] <= t <= wt['end'] + 0.5:
                    current_word = wt
                    break

            if has_content:
                last_good_time = t
                if first_missing and t - first_missing > 1:
                    # Gap ended
                    print(f"  CONTENT RESUMED at {t:.1f}s")
                first_missing = None
            else:
                if current_word and first_missing is None:
                    first_missing = t
                    print(f"\n! MISSING SUBTITLES at {t:.1f}s")
                    print(f"  Expected: '{current_word['word']}' (page {current_word['page']})")
                    print(f"  TS word: '{current_word['ts_word']}'")
                    print(f"  Last good: {last_good_time:.1f}s")
                    issues.append({
                        'time': t,
                        'expected': current_word['word'],
                        'page': current_word['page'],
                        'last_good': last_good_time
                    })

        except Exception as e:
            print(f"  Error at {t:.1f}s: {e}")

    clip.close()

    print("\n" + "="*70)
    if issues:
        print(f"FOUND {len(issues)} ISSUE(S):")
        for issue in issues:
            print(f"  - {issue['time']:.1f}s: expected '{issue['expected']}' (page {issue['page']})")
        print(f"\nSubtitles likely stop working around {issues[0]['last_good']:.1f}s")
    else:
        print("OK - Subtitles appear throughout the video")

    return issues


def main():
    if len(sys.argv) < 4:
        print("Usage: python check_video_subtitles.py <video.mp4> <script.txt> <timestamps.json>")
        sys.exit(1)

    video_path = sys.argv[1]
    script_path = sys.argv[2]
    timestamps_path = sys.argv[3]

    # Load data
    script_words = parse_script_words(script_path)
    print(f"Script: {len(script_words)} words")

    with open(timestamps_path, 'r', encoding='utf-8') as f:
        timestamps = json.load(f)
    print(f"Timestamps: {len(timestamps)} entries")

    # Check video
    issues = extract_and_check_frames(video_path, timestamps, script_words)

    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())

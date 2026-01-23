"""
Styled Subtitles - Word-by-word subtitles with custom styling markup

Формат разметки:
    **слово**           - акцент (большой, белый, жирный)
    *слово*             - выделение (средний, жёлтый)
    _слово_             - приглушённый (мелкий, серый)
    [c:FF5500]слово[/]  - явный цвет (hex без #)
    [s:120]слово[/]     - явный размер (px)
    [c:red,s:80]слово[/] - комбинация
    ---                 - новая страница (очистка экрана)

Цвета по имени: red, green, blue, yellow, orange, purple, pink, white, gray

Использование:
    python scripts/styled_subtitles.py script.txt audio.mp3 -o output.mp4

Или программно:
    from styled_subtitles import parse_styled_text, create_styled_video
"""

import os
import sys
import re
import json
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip
except ImportError:
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip

# Paths
FONT_PATH = r"D:\insta\reelsomet\downloads\fonts\Montserrat-Bold.ttf"

# Video settings
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Text area - centered layout
TEXT_AREA_X = 60
TEXT_AREA_Y = 700
TEXT_AREA_WIDTH = 960
TEXT_AREA_HEIGHT = 520
CENTER_TEXT = True  # Center text horizontally

# Default styles - MAXIMUM IMPACT for Reels
DEFAULT_SIZE = 72
ACCENT_SIZE = 110  # HUGE impact words
HIGHLIGHT_SIZE = 88
MUTED_SIZE = 58  # Clearly secondary

# Named colors - VIBRANT palette for Reels
COLOR_MAP = {
    'white': (255, 255, 255),
    'gray': (180, 180, 180),  # Brighter gray
    'grey': (180, 180, 180),
    'red': (255, 70, 90),     # Vibrant red
    'green': (50, 255, 130),  # Neon green
    'blue': (80, 160, 255),   # Bright blue
    'yellow': (255, 240, 60), # Bright yellow
    'orange': (255, 140, 40), # Vibrant orange
    'purple': (200, 100, 255),# Bright purple
    'pink': (255, 100, 180),  # Hot pink
    'cyan': (60, 230, 255),   # Electric cyan
    'coral': (255, 120, 100), # Coral/salmon
    'lime': (180, 255, 60),   # Lime green
    'gold': (255, 215, 0),    # Gold
    'rose': (255, 150, 180),  # Soft rose
}


@dataclass
class StyledWord:
    """A word with its styling information."""
    text: str
    color: Tuple[int, int, int] = (255, 255, 255)
    size: int = DEFAULT_SIZE
    style: str = 'normal'  # normal, accent, highlight, muted
    page_break_before: bool = False

    # Timing (filled later from timestamps)
    start: float = 0.0
    end: float = 0.0

    # Position (filled during layout)
    x: float = 0.0
    y: float = 0.0


def parse_color(color_str: str) -> Tuple[int, int, int]:
    """Parse color from hex or name."""
    color_str = color_str.lower().strip()

    # Named color
    if color_str in COLOR_MAP:
        return COLOR_MAP[color_str]

    # Hex color (without #)
    if len(color_str) == 6:
        try:
            r = int(color_str[0:2], 16)
            g = int(color_str[2:4], 16)
            b = int(color_str[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass

    # Hex with #
    if color_str.startswith('#') and len(color_str) == 7:
        return parse_color(color_str[1:])

    return (255, 255, 255)  # default white


def parse_styled_text(text: str) -> List[StyledWord]:
    """
    Parse text with styling markup into list of StyledWord objects.

    Markup:
        **word** - accent (large, white)
        *word*   - highlight (medium, yellow)
        _word_   - muted (small, gray)
        [c:color]word[/] - custom color
        [s:size]word[/]  - custom size
        [c:color,s:size]word[/] - combo
        ---      - page break
    """
    words = []

    # Split into tokens (words and page breaks)
    # First handle page breaks
    parts = re.split(r'\n*---\n*', text)

    for part_idx, part in enumerate(parts):
        if part_idx > 0:
            # Mark first word of new part as page break
            words.append(StyledWord(
                text='',
                page_break_before=True
            ))

        # Process this part
        part = part.strip()
        if not part:
            continue

        # Tokenize while preserving markup
        # Pattern to match styled segments
        pattern = r'''
            (\*\*[^*]+\*\*)           |  # **accent**
            (\*[^*]+\*)               |  # *highlight*
            (_[^_]+_)                 |  # _muted_
            (\[[^\]]+\][^\[]+\[/\])   |  # [style]word[/]
            (\S+)                        # plain word
        '''

        tokens = re.findall(pattern, part, re.VERBOSE)

        for token_tuple in tokens:
            # Find which group matched
            token = next(t for t in token_tuple if t)

            word = None

            # **accent**
            if token.startswith('**') and token.endswith('**'):
                inner = token[2:-2].strip()
                word = StyledWord(
                    text=inner,
                    color=(255, 255, 255),
                    size=ACCENT_SIZE,
                    style='accent'
                )

            # *highlight*
            elif token.startswith('*') and token.endswith('*') and not token.startswith('**'):
                inner = token[1:-1].strip()
                word = StyledWord(
                    text=inner,
                    color=COLOR_MAP['yellow'],
                    size=HIGHLIGHT_SIZE,
                    style='highlight'
                )

            # _muted_
            elif token.startswith('_') and token.endswith('_'):
                inner = token[1:-1].strip()
                word = StyledWord(
                    text=inner,
                    color=COLOR_MAP['gray'],
                    size=MUTED_SIZE,
                    style='muted'
                )

            # [style]word[/]
            elif token.startswith('[') and token.endswith('[/]'):
                match = re.match(r'\[([^\]]+)\](.+)\[/\]', token)
                if match:
                    style_str = match.group(1)
                    inner = match.group(2).strip()

                    # Parse style attributes
                    color = (255, 255, 255)
                    size = DEFAULT_SIZE

                    for attr in style_str.split(','):
                        attr = attr.strip()
                        if attr.startswith('c:'):
                            color = parse_color(attr[2:])
                        elif attr.startswith('s:'):
                            try:
                                size = int(attr[2:])
                            except ValueError:
                                pass

                    word = StyledWord(
                        text=inner,
                        color=color,
                        size=size,
                        style='custom'
                    )

            # Plain word
            else:
                word = StyledWord(
                    text=token.strip(),
                    color=(255, 255, 255),
                    size=DEFAULT_SIZE,
                    style='normal'
                )

            if word and word.text:
                # Handle page break marker
                if words and words[-1].text == '' and words[-1].page_break_before:
                    word.page_break_before = True
                    words.pop()  # Remove empty marker
                words.append(word)

    # Remove any empty words
    words = [w for w in words if w.text]

    return words


def apply_timestamps(words: List[StyledWord], timestamps: List[dict]) -> List[StyledWord]:
    """
    Apply timing from Whisper timestamps to styled words.
    Matches words by text similarity.
    """
    if not timestamps:
        return words

    ts_idx = 0

    for word in words:
        # Find matching timestamp
        word_clean = ''.join(c for c in word.text.lower() if c.isalnum())

        while ts_idx < len(timestamps):
            ts = timestamps[ts_idx]
            ts_clean = ''.join(c for c in ts['word'].lower() if c.isalnum())

            # Check for match (exact or partial)
            if word_clean == ts_clean or word_clean in ts_clean or ts_clean in word_clean:
                word.start = ts['start']
                word.end = ts['end']
                ts_idx += 1
                break
            else:
                # Skip timestamp if no match
                ts_idx += 1

        # If no match found, estimate from previous
        if word.start == 0 and words.index(word) > 0:
            prev = words[words.index(word) - 1]
            word.start = prev.end + 0.05
            word.end = word.start + 0.3

    return words


def layout_words(words: List[StyledWord], font_path: str) -> List[List[StyledWord]]:
    """Layout words into pages based on page breaks and area constraints."""
    # Load fonts for different sizes
    fonts = {}
    for size in range(30, 150, 2):
        fonts[size] = ImageFont.truetype(font_path, size)

    def get_font(size):
        available = sorted(fonts.keys())
        closest = min(available, key=lambda x: abs(x - size))
        return fonts[closest]

    def get_text_size(text, size):
        font = get_font(size)
        temp = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(temp)
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Orphan protection: words that should not appear alone at end of row
    ORPHAN_WORDS = {'от', 'в', 'на', 'с', 'и', 'а', 'к', 'у', 'о', 'за', 'из', 'по', 'до', 'не', 'но', 'же', 'бы'}

    def is_orphan_word(text):
        """Check if word should not appear alone at row end."""
        clean = ''.join(c for c in text.lower() if c.isalnum())
        return clean in ORPHAN_WORDS

    pages = []
    current_page = []
    rows = []  # List of rows, each row is list of words
    current_row = []
    current_row_height = 0
    cursor_x = TEXT_AREA_X
    cursor_y = TEXT_AREA_Y
    padding_x = 20
    padding_y = 25  # Increased vertical padding

    for i, word in enumerate(words):
        # Page break - start new page
        if word.page_break_before:
            # Finish current row
            if current_row:
                rows.append((current_row, current_row_height))
            # Assign Y positions to all rows on this page
            y = TEXT_AREA_Y
            for row_words, row_h in rows:
                for w in row_words:
                    w.y = y
                current_page.extend(row_words)
                y += row_h + padding_y
            if current_page:
                pages.append(current_page)
            # Reset for new page
            current_page = []
            rows = []
            current_row = []
            current_row_height = 0
            cursor_x = TEXT_AREA_X
            cursor_y = TEXT_AREA_Y

        # Get word dimensions - auto-shrink if too wide
        text_w, text_h = get_text_size(word.text, word.size)

        # Auto-shrink words that are too wide for a single line
        original_size = word.size
        while text_w > TEXT_AREA_WIDTH - 40 and word.size > 50:  # Keep minimum 50px
            word.size -= 4
            text_w, text_h = get_text_size(word.text, word.size)

        # Check if fits in current row
        needs_new_row = cursor_x + text_w > TEXT_AREA_X + TEXT_AREA_WIDTH and current_row

        # Orphan protection: if current word is orphan-prone, check scenarios
        if is_orphan_word(word.text) and i + 1 < len(words) and not words[i + 1].page_break_before:
            next_word = words[i + 1]
            next_w, _ = get_text_size(next_word.text, next_word.size)

            if needs_new_row:
                # Word already needs new row - check if it would be alone there
                # If orphan + next word don't fit on new row together, DON'T start new row
                # (keep orphan with previous content instead of being alone)
                if text_w + padding_x + next_w > TEXT_AREA_WIDTH:
                    needs_new_row = False  # Keep on current row with previous words
            else:
                # Word fits on current row - check if next word would fit too
                # If not, and orphan would be alone at row end, keep it with previous row
                remaining_space = TEXT_AREA_X + TEXT_AREA_WIDTH - (cursor_x + text_w + padding_x)
                if remaining_space < next_w:
                    # Next word won't fit after this orphan
                    # Check if starting new row would leave orphan alone
                    if text_w + padding_x + next_w > TEXT_AREA_WIDTH:
                        # Even on new row, orphan would be alone - keep on current row
                        pass  # Don't change needs_new_row, stay on current row

        if needs_new_row:
            # Save current row
            rows.append((current_row, current_row_height))
            cursor_y += current_row_height + padding_y
            # Start new row
            current_row = []
            current_row_height = 0
            cursor_x = TEXT_AREA_X

        # Check if new page needed (vertical overflow)
        total_height = sum(h + padding_y for _, h in rows) + text_h
        if total_height > TEXT_AREA_HEIGHT and rows:
            # Assign Y positions to all rows
            y = TEXT_AREA_Y
            for row_words, row_h in rows:
                for w in row_words:
                    w.y = y
                current_page.extend(row_words)
                y += row_h + padding_y
            pages.append(current_page)
            # Reset for new page
            current_page = []
            rows = []
            current_row = []
            current_row_height = 0
            cursor_x = TEXT_AREA_X
            cursor_y = TEXT_AREA_Y

        # Position word (X only, Y will be set later)
        word.x = cursor_x
        current_row.append(word)
        current_row_height = max(current_row_height, text_h)
        cursor_x += text_w + padding_x

    # Finish last row
    if current_row:
        rows.append((current_row, current_row_height))

    # Assign Y positions to remaining rows and center horizontally
    y = TEXT_AREA_Y
    for row_words, row_h in rows:
        # Calculate row width for centering
        if row_words and CENTER_TEXT:
            last_word = row_words[-1]
            last_w, _ = get_text_size(last_word.text, last_word.size)
            row_width = (last_word.x - TEXT_AREA_X) + last_w
            offset_x = (TEXT_AREA_WIDTH - row_width) // 2
            for w in row_words:
                w.x += offset_x
        for w in row_words:
            w.y = y
        current_page.extend(row_words)
        y += row_h + padding_y

    if current_page:
        pages.append(current_page)

    return pages


def ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def render_frame(t: float, pages: List[List[StyledWord]], fonts: dict, all_words: List[StyledWord] = None) -> np.ndarray:
    """Render frame at time t."""
    img = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Orphan words that should wait for next word
    ORPHAN_WORDS = {'от', 'в', 'на', 'с', 'и', 'а', 'к', 'у', 'о', 'за', 'из', 'по', 'до', 'не', 'но', 'же', 'бы'}

    def is_orphan_word(text):
        clean = ''.join(c for c in text.lower() if c.isalnum())
        return clean in ORPHAN_WORDS

    # Find current page - use the page where the last word that started is located
    current_page_idx = 0
    for i, page in enumerate(pages):
        if page:
            # Check if any word on this page has started
            page_started = any(w.start <= t for w in page)
            if page_started:
                current_page_idx = i

    if current_page_idx >= len(pages):
        return np.array(img)

    page = pages[current_page_idx]

    def get_font(size):
        available = sorted(fonts.keys())
        closest = min(available, key=lambda x: abs(x - size))
        return fonts[closest]

    # Build list of visible words first, then check for orphans
    visible_words = []
    for idx, word in enumerate(page):
        if t < word.start:
            continue

        # Check if this is an orphan word that should wait for next word
        if is_orphan_word(word.text) and idx + 1 < len(page):
            next_word = page[idx + 1]
            # If next word hasn't started yet
            if t < next_word.start:
                # Check if orphan would be alone on its row at this moment
                # Count other visible words on the same row
                same_row_words = [w for w in page[:idx] if t >= w.start and abs(w.y - word.y) <= 10]
                if not same_row_words:
                    # Orphan would be alone on its row - delay until next word appears
                    continue

        visible_words.append(word)

    # First pass: draw glow for accent/highlight/custom words
    glow_img = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)

    for word in visible_words:
        anim_duration = 0.25
        progress = min(1.0, (t - word.start) / anim_duration)
        eased = ease_out_back(progress)

        font = get_font(word.size)
        offset_y = int((1 - eased) * 20)
        x, y = int(word.x), int(word.y + offset_y)

        # Draw glow for accent/highlight/custom colored words
        if word.style in ('accent', 'highlight', 'custom'):
            glow_alpha = int(100 * eased)
            glow_color = (*word.color, glow_alpha)
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    glow_draw.text((x + dx, y + dy), word.text, font=font, fill=glow_color)

    # Apply blur to glow layer
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=12))
    img = Image.alpha_composite(img, glow_img)
    draw = ImageDraw.Draw(img)

    # Second pass: draw actual text
    for word in visible_words:
        anim_duration = 0.25
        progress = min(1.0, (t - word.start) / anim_duration)
        eased = ease_out_back(progress)

        font = get_font(word.size)
        alpha = int(255 * eased)
        color = (*word.color, alpha)

        offset_y = int((1 - eased) * 20)
        x, y = int(word.x), int(word.y + offset_y)

        # Shadow
        shadow_alpha = int(200 * eased)
        draw.text((x + 4, y + 4), word.text, font=font, fill=(0, 0, 0, shadow_alpha))

        # Main text
        draw.text((x, y), word.text, font=font, fill=color)

    return np.array(img)


def create_styled_video(
    script_path: str,
    audio_path: str,
    timestamps_path: str,
    output_path: str,
    background_path: str = None
):
    """Create video with styled subtitles."""

    # Load script
    print(f"Loading script: {script_path}")
    with open(script_path, 'r', encoding='utf-8') as f:
        script_text = f.read()

    # Parse styled text
    words = parse_styled_text(script_text)
    print(f"Parsed {len(words)} styled words")

    # Load timestamps
    print(f"Loading timestamps: {timestamps_path}")
    with open(timestamps_path, 'r', encoding='utf-8') as f:
        timestamps = json.load(f)

    # Apply timestamps
    words = apply_timestamps(words, timestamps)

    # Layout into pages
    pages = layout_words(words, FONT_PATH)
    print(f"Layout: {len(pages)} pages")

    # Preview
    print("\nStyled words preview:")
    for i, w in enumerate(words[:10]):
        print(f"  {w.start:.2f}s [{w.style}] {w.text}")
    if len(words) > 10:
        print(f"  ... and {len(words) - 10} more")

    # Load fonts
    fonts = {}
    for size in range(30, 150, 2):
        fonts[size] = ImageFont.truetype(FONT_PATH, size)

    # Get duration from audio
    audio = AudioFileClip(audio_path)
    duration = audio.duration
    print(f"\nAudio duration: {duration:.1f}s")

    # Create subtitle clip
    def make_frame(t):
        return render_frame(t, pages, fonts)

    subtitle_clip = VideoClip(make_frame, duration=duration).with_fps(FPS)

    # Background
    if background_path and os.path.exists(background_path):
        print(f"Using background: {background_path}")
        bg = VideoFileClip(background_path)
        if bg.duration < duration:
            bg = bg.loop(duration=duration)
        else:
            bg = bg.subclipped(0, duration)
        bg = bg.resized((WIDTH, HEIGHT))
    else:
        bg = ColorClip(size=(WIDTH, HEIGHT), color=(15, 15, 20), duration=duration)

    # Composite
    final = CompositeVideoClip([bg, subtitle_clip])
    final = final.with_audio(audio)

    # Export
    print(f"\nRendering: {output_path}")
    final.write_videofile(
        output_path,
        fps=FPS,
        codec='libx264',
        audio_codec='aac',
        ffmpeg_params=['-crf', '23'],
        logger='bar'
    )

    print(f"Done! {output_path}")
    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create video with styled subtitles")
    parser.add_argument("script", help="Path to styled script file")
    parser.add_argument("audio", help="Path to audio file")
    parser.add_argument("timestamps", nargs="?", help="Path to timestamps JSON")
    parser.add_argument("-o", "--output", help="Output video path")
    parser.add_argument("--bg", dest="background", help="Background video")
    args = parser.parse_args()

    # Defaults
    audio_path = Path(args.audio)
    if not args.timestamps:
        args.timestamps = str(audio_path.parent / f"{audio_path.stem}_timestamps.json")
    if not args.output:
        args.output = str(audio_path.parent / f"{audio_path.stem}_styled.mp4")

    create_styled_video(
        script_path=args.script,
        audio_path=args.audio,
        timestamps_path=args.timestamps,
        output_path=args.output,
        background_path=args.background
    )


if __name__ == "__main__":
    main()

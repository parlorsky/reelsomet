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
import tempfile
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip, concatenate_videoclips
except ImportError:
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip, concatenate_videoclips

# Paths
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads", "fonts", "Montserrat-Bold.ttf")

# Video settings
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Instagram Reels Safe Zone margins
# These areas are covered by Instagram UI (username, likes, comments, etc.)
SAFE_MARGIN_TOP = 250      # Username bar, audio info
SAFE_MARGIN_BOTTOM = 320   # Like, comment, share buttons, captions
SAFE_MARGIN_LEFT = 60      # Left edge
SAFE_MARGIN_RIGHT = 120    # Right side buttons (like, comment, share, save)

# Text area - calculated from safe margins
# Vertical position can be adjusted within safe zone
TEXT_AREA_X = SAFE_MARGIN_LEFT
TEXT_AREA_Y = 700          # Where subtitles start (within safe zone)
TEXT_AREA_WIDTH = WIDTH - SAFE_MARGIN_LEFT - SAFE_MARGIN_RIGHT  # 900px
TEXT_AREA_HEIGHT = (HEIGHT - SAFE_MARGIN_BOTTOM) - TEXT_AREA_Y  # Stop before bottom UI
CENTER_TEXT = True  # Center text horizontally

# Background effects
BG_DARKEN = 0.4           # Darken factor (0=black, 1=original)
BG_DESATURATE = 0.7       # Desaturation (0=original, 1=grayscale)
BG_TRANSITION_DURATION = 0.3  # Crossfade duration between backgrounds

# Text glow settings (enhanced for visibility)
GLOW_RADIUS = 15          # Blur radius for glow
GLOW_INTENSITY = 200      # Alpha for glow (0-255)
GLOW_SPREAD = 3           # How far glow extends (reduced for speed)

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


def normalize_for_match(text: str) -> str:
    """Normalize text for matching: lowercase, alphanumeric, ё→е."""
    text = text.lower().replace('ё', 'е')
    return ''.join(c for c in text if c.isalnum())


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
        word_clean = normalize_for_match(word.text)

        # Skip punctuation-only words (they clean to empty string)
        if not word_clean:
            # Estimate from previous word
            if words.index(word) > 0:
                prev = words[words.index(word) - 1]
                word.start = prev.end
                word.end = prev.end + 0.1
            continue

        while ts_idx < len(timestamps):
            ts = timestamps[ts_idx]
            ts_clean = normalize_for_match(ts['word'])

            # Skip empty timestamp words
            if not ts_clean:
                ts_idx += 1
                continue

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


def render_frame_to_file(args):
    """Render a single frame to file (for parallel processing)."""
    frame_idx, t, pages_data, font_path, output_path, bg_info = args

    # Reload fonts in this process
    fonts = {}
    for size in range(30, 150, 2):
        fonts[size] = ImageFont.truetype(font_path, size)

    # Reconstruct pages from serializable data
    pages = []
    for page_data in pages_data:
        page = []
        for w_data in page_data:
            word = StyledWord(
                text=w_data['text'],
                color=tuple(w_data['color']),
                size=w_data['size'],
                style=w_data['style'],
                start=w_data['start'],
                end=w_data['end'],
                x=w_data['x'],
                y=w_data['y']
            )
            page.append(word)
        pages.append(page)

    # Render subtitle frame (RGBA)
    subtitle_frame = render_frame(t, pages, fonts)

    # Create background - either from video frame or solid color
    if isinstance(bg_info, str) and os.path.exists(bg_info):
        # bg_info is path to background frame
        bg = Image.open(bg_info).convert('RGBA')
    else:
        # bg_info is color tuple
        bg_color = bg_info if isinstance(bg_info, tuple) else (15, 15, 20, 255)
        bg = Image.new('RGBA', (WIDTH, HEIGHT), bg_color)

    # Composite subtitle over background
    subtitle_img = Image.fromarray(subtitle_frame)
    final = Image.alpha_composite(bg, subtitle_img)

    # Convert to RGB (no alpha) and save as PNG
    final_rgb = final.convert('RGB')
    final_rgb.save(output_path, 'PNG')

    return frame_idx


def serialize_pages(pages: List[List['StyledWord']]) -> List[List[dict]]:
    """Convert pages to serializable format for multiprocessing."""
    return [
        [
            {
                'text': w.text,
                'color': list(w.color),
                'size': w.size,
                'style': w.style,
                'start': w.start,
                'end': w.end,
                'x': w.x,
                'y': w.y
            }
            for w in page
        ]
        for page in pages
    ]


def ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def load_background_catalog(backgrounds_dir: str) -> List[dict]:
    """Load background videos from catalog.json."""
    catalog_path = os.path.join(backgrounds_dir, "catalog.json")
    if not os.path.exists(catalog_path):
        return []

    with open(catalog_path, 'r', encoding='utf-8') as f:
        catalog = json.load(f)

    return catalog.get('videos', [])


def process_background_frame(frame: np.ndarray, darken: float = BG_DARKEN, desaturate: float = BG_DESATURATE) -> np.ndarray:
    """Apply darken and desaturation effects to background frame."""
    # Convert to float for processing
    img = frame.astype(np.float32)

    # Desaturate (convert to grayscale and blend)
    if desaturate > 0:
        gray = np.dot(img[..., :3], [0.299, 0.587, 0.114])
        gray = np.stack([gray, gray, gray], axis=-1)
        img[..., :3] = img[..., :3] * (1 - desaturate) + gray * desaturate

    # Darken
    img = img * darken

    return img.clip(0, 255).astype(np.uint8)


def extract_background_frames(bg_videos: List[str], page_times: List[Tuple[float, float]],
                               temp_dir: str, total_frames: int, fps: int = 30,
                               darken: float = BG_DARKEN, desaturate: float = BG_DESATURATE) -> Dict[int, str]:
    """
    Extract background frames for all video frames based on page timing.
    Returns mapping of frame_idx -> background frame path.
    """
    if not bg_videos or not page_times:
        return {}

    print(f"\nExtracting background frames for {total_frames} frames...")

    # Create bg frames subdirectory
    bg_frames_dir = os.path.join(temp_dir, 'bg_frames')
    os.makedirs(bg_frames_dir, exist_ok=True)

    # Build mapping: frame_idx -> page_idx -> video_idx
    def get_page_for_time(t):
        for i, (start, end) in enumerate(page_times):
            if start <= t < end + 0.5:
                return i
        # After last page - use last page's video
        if page_times and t >= page_times[-1][0]:
            return len(page_times) - 1
        return 0

    # Load all background videos once
    clips = {}
    for i, path in enumerate(bg_videos):
        try:
            clips[i] = VideoFileClip(path)
            print(f"  Loaded: {os.path.basename(path)} ({clips[i].duration:.1f}s)")
        except Exception as e:
            print(f"  Warning: Could not load {path}: {e}")

    if not clips:
        return {}

    frame_mapping = {}
    bg_frame_cache = {}  # (video_idx, video_frame) -> path

    # Process frames in batches for progress reporting
    batch_size = 100
    for batch_start in range(0, total_frames, batch_size):
        batch_end = min(batch_start + batch_size, total_frames)

        for frame_idx in range(batch_start, batch_end):
            t = frame_idx / fps
            page_idx = get_page_for_time(t)
            video_idx = page_idx % len(bg_videos)

            if video_idx not in clips:
                # Fallback to first available video
                video_idx = next(iter(clips.keys()))

            clip = clips[video_idx]
            video_t = t % clip.duration
            cache_key = (video_idx, round(video_t * fps))

            if cache_key not in bg_frame_cache:
                # Extract and process frame
                frame = clip.get_frame(video_t)
                frame_img = Image.fromarray(frame)

                # Crop to 9:16 aspect ratio
                src_w, src_h = frame_img.size
                target_ratio = WIDTH / HEIGHT
                src_ratio = src_w / src_h

                if src_ratio > target_ratio:
                    new_w = int(src_h * target_ratio)
                    offset = (src_w - new_w) // 2
                    frame_img = frame_img.crop((offset, 0, offset + new_w, src_h))
                else:
                    new_h = int(src_w / target_ratio)
                    offset = (src_h - new_h) // 2
                    frame_img = frame_img.crop((0, offset, src_w, offset + new_h))

                frame_img = frame_img.resize((WIDTH, HEIGHT), Image.LANCZOS)
                frame_arr = np.array(frame_img)

                # Apply effects
                frame_arr = process_background_frame(frame_arr, darken, desaturate)

                # Save
                bg_frame_path = os.path.join(bg_frames_dir, f'bg_{video_idx}_{cache_key[1]:06d}.png')
                Image.fromarray(frame_arr).save(bg_frame_path, 'PNG')
                bg_frame_cache[cache_key] = bg_frame_path

            frame_mapping[frame_idx] = bg_frame_cache[cache_key]

        # Progress
        progress = 100 * batch_end / total_frames
        print(f"  Extracted {batch_end}/{total_frames} ({progress:.0f}%)", end='\r')

    print(f"\n  Done: {len(bg_frame_cache)} unique background frames")

    # Cleanup
    for clip in clips.values():
        clip.close()

    return frame_mapping


def get_page_times(pages: List[List['StyledWord']]) -> List[Tuple[float, float]]:
    """Get start and end times for each page."""
    page_times = []
    for page in pages:
        if not page:
            continue
        start = min(w.start for w in page)
        end = max(w.end for w in page)
        page_times.append((start, end))
    return page_times


def render_frame(t: float, pages: List[List[StyledWord]], fonts: dict, all_words: List[StyledWord] = None) -> np.ndarray:
    """Render frame at time t with enhanced glow effect."""
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

    # First pass: draw BRIGHT WHITE GLOW for ALL words (optimized)
    glow_img = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)

    for word in visible_words:
        anim_duration = 0.25
        progress = min(1.0, (t - word.start) / anim_duration)
        eased = ease_out_back(progress)

        font = get_font(word.size)
        offset_y = int((1 - eased) * 20)
        x, y = int(word.x), int(word.y + offset_y)

        # Draw WHITE glow - single draw, blur will spread it
        glow_alpha = int(GLOW_INTENSITY * eased)
        glow_color = (255, 255, 255, glow_alpha)

        # Single text draw (blur will create the glow effect)
        glow_draw.text((x, y), word.text, font=font, fill=glow_color)

    # Apply strong blur to create glow effect
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=GLOW_RADIUS))
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

        # Shadow (stronger for dark backgrounds)
        shadow_alpha = int(220 * eased)
        for sx in range(1, 5):
            for sy in range(1, 5):
                draw.text((x + sx, y + sy), word.text, font=font, fill=(0, 0, 0, shadow_alpha // 2))
        draw.text((x + 3, y + 3), word.text, font=font, fill=(0, 0, 0, shadow_alpha))

        # Main text
        draw.text((x, y), word.text, font=font, fill=color)

    return np.array(img)


def get_ffmpeg_path():
    """Get ffmpeg path from imageio_ffmpeg or system."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except:
        return 'ffmpeg'  # Hope it's in PATH


def assemble_video_ffmpeg(
    frames_dir: str,
    audio_path: str,
    output_path: str,
    fps: int = 30,
    codec: str = 'libx264',
    crf: int = 23,
    threads: int = 0,
    gpu: str = None
):
    """Assemble video from frames using ffmpeg directly (much faster than moviepy)."""
    ffmpeg = get_ffmpeg_path()

    # Build ffmpeg command
    cmd = [ffmpeg, '-y']  # -y to overwrite

    # Input: image sequence
    cmd.extend(['-framerate', str(fps)])
    cmd.extend(['-i', os.path.join(frames_dir, 'frame_%06d.png')])

    # Input: audio
    cmd.extend(['-i', audio_path])

    # Video codec settings
    if gpu == 'nvenc':
        cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', str(crf), '-b:v', '0'])
    elif gpu == 'amd':
        cmd.extend(['-c:v', 'h264_amf', '-quality', 'balanced', '-rc', 'vbr_latency', '-qp_i', str(crf), '-qp_p', str(crf)])
    elif gpu == 'intel':
        cmd.extend(['-c:v', 'h264_qsv', '-preset', 'medium', '-global_quality', str(crf)])
    else:
        # CPU encoding
        cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf)])
        if threads > 0:
            cmd.extend(['-threads', str(threads)])

    # Audio codec
    cmd.extend(['-c:a', 'aac', '-b:a', '192k'])

    # Pixel format for compatibility
    cmd.extend(['-pix_fmt', 'yuv420p'])

    # Map streams
    cmd.extend(['-map', '0:v', '-map', '1:a'])

    # Shortest (stop when shortest input ends)
    cmd.extend(['-shortest'])

    # Output
    cmd.append(output_path)

    print(f"Running ffmpeg: {' '.join(cmd[:10])}...")

    # Run ffmpeg
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}")
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")

    return output_path


def detect_gpu_encoder():
    """Auto-detect available GPU encoder."""
    import subprocess
    try:
        # Try NVIDIA first (most common for video work)
        result = subprocess.run(
            ['nvidia-smi'], capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return 'h264_nvenc'
    except:
        pass

    # Fallback order: AMD, Intel, CPU
    return 'libx264'


def get_gpu_codec(gpu_option: str, threads: int = 0) -> tuple:
    """Get codec and ffmpeg params for GPU/CPU encoding."""
    if gpu_option == 'nvenc':
        return 'h264_nvenc', ['-preset', 'p4', '-rc', 'vbr', '-cq', '23', '-b:v', '0']
    elif gpu_option == 'amd':
        return 'h264_amf', ['-quality', 'balanced', '-rc', 'vbr_latency', '-qp_i', '23', '-qp_p', '23']
    elif gpu_option == 'intel':
        return 'h264_qsv', ['-preset', 'medium', '-global_quality', '23']
    elif gpu_option == 'auto':
        codec = detect_gpu_encoder()
        if codec == 'h264_nvenc':
            return 'h264_nvenc', ['-preset', 'p4', '-rc', 'vbr', '-cq', '23', '-b:v', '0']
        # CPU with threads
        params = ['-crf', '23', '-preset', 'fast']
        if threads > 0:
            params.extend(['-threads', str(threads)])
        return 'libx264', params
    else:
        # CPU encoding with threading
        params = ['-crf', '23', '-preset', 'fast']
        if threads > 0:
            params.extend(['-threads', str(threads)])
        return 'libx264', params


def concatenate_with_hook(
    hook_clip: str,
    freeze_clip: str,
    main_video: str,
    output_path: str,
    audio_path: str = None,
    gpu: str = None
):
    """
    Concatenate hook + freeze + main video.
    Audio from main video is replaced with full audio file.
    """
    print(f"\nConcatenating hook + freeze + main...")

    ffmpeg = get_ffmpeg_path()
    temp_dir = os.path.dirname(main_video)
    concat_list = os.path.join(temp_dir, 'concat_list.txt')

    # Create concat list file
    with open(concat_list, 'w') as f:
        f.write(f"file '{os.path.abspath(hook_clip)}'\n")
        f.write(f"file '{os.path.abspath(freeze_clip)}'\n")
        f.write(f"file '{os.path.abspath(main_video)}'\n")

    # First pass: concat videos without audio
    temp_concat = os.path.join(temp_dir, 'temp_concat.mp4')
    cmd = [
        ffmpeg, '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_list,
        '-c:v', 'copy',
        '-an',  # no audio
        temp_concat
    ]
    subprocess.run(cmd, capture_output=True)

    # Second pass: add audio
    codec_params = []
    if gpu == 'nvenc':
        codec_params = ['-c:v', 'h264_nvenc', '-preset', 'p4']
    elif gpu == 'amd':
        codec_params = ['-c:v', 'h264_amf']
    elif gpu == 'intel':
        codec_params = ['-c:v', 'h264_qsv']
    else:
        codec_params = ['-c:v', 'libx264', '-preset', 'fast']

    if audio_path:
        cmd = [
            ffmpeg, '-y',
            '-i', temp_concat,
            '-i', audio_path,
            '-map', '0:v',
            '-map', '1:a',
            '-c:a', 'aac', '-b:a', '192k',
            *codec_params,
            '-shortest',
            output_path
        ]
    else:
        cmd = [ffmpeg, '-y', '-i', temp_concat, '-c', 'copy', output_path]

    subprocess.run(cmd, capture_output=True)

    # Cleanup temp files
    os.remove(concat_list)
    os.remove(temp_concat)

    print(f"  Created: {output_path}")


def prepare_hook_video(
    hook_path: str,
    temp_dir: str,
    hook_duration: float = 0,
    freeze_duration: float = 3.0,
    fps: int = 30
) -> tuple:
    """
    Prepare hook video with freeze frame.
    Returns (hook_clip_path, freeze_clip_path, total_hook_duration).
    """
    print(f"\nPreparing hook video: {hook_path}")

    clip = VideoFileClip(hook_path)
    original_duration = clip.duration

    # Determine hook duration
    if hook_duration <= 0 or hook_duration > original_duration:
        use_duration = original_duration
    else:
        use_duration = hook_duration

    print(f"  Original duration: {original_duration:.2f}s")
    print(f"  Using duration: {use_duration:.2f}s")
    print(f"  Freeze duration: {freeze_duration:.2f}s")

    # Resize to 1080x1920 if needed
    src_w, src_h = clip.size
    target_ratio = WIDTH / HEIGHT
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) > 0.01 or src_w != WIDTH:
        # Need to crop/resize
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            x_offset = (src_w - new_w) // 2
            clip = clip.cropped(x1=x_offset, x2=x_offset + new_w)
        else:
            new_h = int(src_w / target_ratio)
            y_offset = (src_h - new_h) // 2
            clip = clip.cropped(y1=y_offset, y2=y_offset + new_h)
        clip = clip.resized((WIDTH, HEIGHT))

    # Trim to hook duration
    if use_duration < original_duration:
        clip = clip.subclipped(0, use_duration)

    # Save trimmed hook
    hook_clip_path = os.path.join(temp_dir, 'hook_clip.mp4')
    clip.write_videofile(
        hook_clip_path,
        fps=fps,
        codec='libx264',
        audio=False,
        preset='fast',
        logger=None
    )

    # Extract last frame for freeze
    last_frame = clip.get_frame(clip.duration - 0.01)
    clip.close()

    # Create freeze frame video
    freeze_clip_path = os.path.join(temp_dir, 'freeze_clip.mp4')
    freeze_img = Image.fromarray(last_frame)

    # Save freeze frames
    freeze_frames_dir = os.path.join(temp_dir, 'freeze_frames')
    os.makedirs(freeze_frames_dir, exist_ok=True)

    total_freeze_frames = int(freeze_duration * fps)
    for i in range(total_freeze_frames):
        freeze_img.save(os.path.join(freeze_frames_dir, f'frame_{i:06d}.png'))

    # Assemble freeze video with ffmpeg
    ffmpeg_path = get_ffmpeg_path()
    subprocess.run([
        ffmpeg_path, '-y',
        '-framerate', str(fps),
        '-i', os.path.join(freeze_frames_dir, 'frame_%06d.png'),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-preset', 'fast',
        freeze_clip_path
    ], capture_output=True)

    print(f"  Hook clip: {hook_clip_path}")
    print(f"  Freeze clip: {freeze_clip_path}")

    return hook_clip_path, freeze_clip_path, use_duration + freeze_duration


def create_styled_video(
    script_path: str,
    audio_path: str,
    timestamps_path: str,
    output_path: str,
    background_path: str = None,
    backgrounds_dir: str = None,
    darken: float = BG_DARKEN,
    desaturate: float = BG_DESATURATE,
    gpu: str = None,
    threads: int = 0,
    hook_video: str = None,
    hook_duration: float = 0,
    freeze_duration: float = 3.0
):
    """Create video with styled subtitles and dynamic backgrounds."""

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

    # Get page timing for background switching
    page_times = get_page_times(pages)
    print(f"\nPage timings:")
    for i, (start, end) in enumerate(page_times):
        print(f"  Page {i+1}: {start:.2f}s - {end:.2f}s")

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

    total_frames = int(duration * FPS)

    # Parallel frame pre-rendering
    if threads > 1:
        print(f"\nPre-rendering {total_frames} frames with {threads} workers...")

        # Create temp directory for frames
        temp_dir = tempfile.mkdtemp(prefix='styled_frames_')

        try:
            # Serialize pages for multiprocessing
            pages_data = serialize_pages(pages)

            # Load background videos for parallel rendering
            bg_videos = []
            if backgrounds_dir and os.path.exists(backgrounds_dir):
                catalog = load_background_catalog(backgrounds_dir)
                if catalog:
                    print(f"\nLoaded {len(catalog)} backgrounds from catalog")
                    for vid in catalog:
                        if os.path.exists(vid['path']):
                            bg_videos.append(vid['path'])
                            print(f"  - {vid['filename']}")

            # Or use single background
            if not bg_videos and background_path and os.path.exists(background_path):
                bg_videos = [background_path]
                print(f"\nUsing single background: {background_path}")

            # Pre-extract background frames if we have videos
            bg_frame_mapping = {}
            if bg_videos:
                bg_frame_mapping = extract_background_frames(
                    bg_videos, page_times, temp_dir, total_frames, FPS, darken, desaturate
                )

            # Default background color (dark) for frames without video bg
            default_bg_color = (15, 15, 20, 255)

            # Prepare tasks
            tasks = []
            for frame_idx in range(total_frames):
                t = frame_idx / FPS
                frame_path = os.path.join(temp_dir, f'frame_{frame_idx:06d}.png')
                # Use video background frame if available, otherwise solid color
                bg_info = bg_frame_mapping.get(frame_idx, default_bg_color)
                tasks.append((frame_idx, t, pages_data, FONT_PATH, frame_path, bg_info))

            # Render frames in parallel
            completed = 0
            with ProcessPoolExecutor(max_workers=threads) as executor:
                futures = {executor.submit(render_frame_to_file, task): task[0] for task in tasks}
                for future in as_completed(futures):
                    completed += 1
                    if completed % 100 == 0 or completed == total_frames:
                        print(f"  Rendered {completed}/{total_frames} frames ({100*completed/total_frames:.0f}%)")

            # Use ffmpeg directly for fast assembly
            print(f"\nAssembling video with ffmpeg...")

            # If hook video, assemble main to temp, then concat
            if hook_video and os.path.exists(hook_video):
                main_video_path = os.path.join(temp_dir, 'main_video.mp4')
                assemble_video_ffmpeg(
                    frames_dir=temp_dir,
                    audio_path=audio_path,
                    output_path=main_video_path,
                    fps=FPS,
                    crf=23,
                    threads=threads,
                    gpu=gpu
                )

                # Prepare hook with freeze frame
                hook_clip, freeze_clip, hook_total_dur = prepare_hook_video(
                    hook_path=hook_video,
                    temp_dir=temp_dir,
                    hook_duration=hook_duration,
                    freeze_duration=freeze_duration,
                    fps=FPS
                )

                # Concatenate hook + freeze + main
                concatenate_with_hook(
                    hook_clip=hook_clip,
                    freeze_clip=freeze_clip,
                    main_video=main_video_path,
                    output_path=output_path,
                    audio_path=audio_path,
                    gpu=gpu
                )
            else:
                assemble_video_ffmpeg(
                    frames_dir=temp_dir,
                    audio_path=audio_path,
                    output_path=output_path,
                    fps=FPS,
                    crf=23,
                    threads=threads,
                    gpu=gpu
                )

            # Cleanup
            shutil.rmtree(temp_dir)
            print("Cleaned up temp frames")
            print(f"Done! {output_path}")
            return output_path

        except Exception as e:
            # Cleanup on error
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e

    else:
        # Single-threaded (original method)
        temp_dir = None
        frame_cache = {}

        def get_cached_frame(t):
            frame_key = round(t * FPS)
            if frame_key not in frame_cache:
                frame_cache[frame_key] = render_frame(t, pages, fonts)
            return frame_cache[frame_key]

        def make_subtitle_frame(t):
            rgba = get_cached_frame(t)
            return rgba[:, :, :3]

        def make_subtitle_mask(t):
            rgba = get_cached_frame(t)
            return rgba[:, :, 3] / 255.0

        subtitle_clip = VideoClip(make_subtitle_frame, duration=duration).with_fps(FPS)
        subtitle_mask = VideoClip(make_subtitle_mask, duration=duration, is_mask=True).with_fps(FPS)
        subtitle_clip = subtitle_clip.with_mask(subtitle_mask)

    # Load background videos
    bg_clips = []

    # Check for backgrounds directory with catalog
    if backgrounds_dir and os.path.exists(backgrounds_dir):
        catalog = load_background_catalog(backgrounds_dir)
        if catalog:
            print(f"\nLoaded {len(catalog)} backgrounds from catalog")
            for vid in catalog:
                if os.path.exists(vid['path']):
                    bg_clips.append(vid['path'])
                    print(f"  - {vid['filename']}")

    # Or use single background
    if not bg_clips and background_path and os.path.exists(background_path):
        bg_clips = [background_path]

    # Create background with page-based switching
    if bg_clips:
        print(f"\nCreating dynamic background with {len(bg_clips)} videos...")

        # Function to get current background index based on time
        def get_bg_index(t):
            for i, (start, end) in enumerate(page_times):
                if start <= t < end + 0.5:  # Small buffer
                    return i % len(bg_clips)
            return 0

        # Load all background clips with pre-applied effects
        loaded_bgs = []
        for bg_path in bg_clips:
            try:
                clip = VideoFileClip(bg_path)
                # Resize to fit
                clip = clip.resized((WIDTH, HEIGHT))

                # Pre-apply darken and desaturate effects
                def apply_effects(frame, d=darken, ds=desaturate):
                    return process_background_frame(frame, darken=d, desaturate=ds)

                clip = clip.image_transform(apply_effects)
                loaded_bgs.append(clip)
                print(f"    Processed: {os.path.basename(bg_path)}")
            except Exception as e:
                print(f"  Warning: Could not load {bg_path}: {e}")

        if not loaded_bgs:
            loaded_bgs = [ColorClip(size=(WIDTH, HEIGHT), color=(15, 15, 20), duration=1)]

        # Create composite background that switches with pages
        bg_frame_cache = {}

        def make_bg_frame(t):
            bg_idx = get_bg_index(t)
            clip = loaded_bgs[bg_idx % len(loaded_bgs)]

            # Get frame from clip (loop if needed)
            clip_t = t % clip.duration

            # Cache key
            cache_key = (bg_idx, round(clip_t * FPS))
            if cache_key not in bg_frame_cache:
                bg_frame_cache[cache_key] = clip.get_frame(clip_t)
            return bg_frame_cache[cache_key]

        bg = VideoClip(make_bg_frame, duration=duration).with_fps(FPS)

    else:
        # Fallback to solid color
        print("\nUsing solid color background")
        bg = ColorClip(size=(WIDTH, HEIGHT), color=(15, 15, 20), duration=duration)

    # Composite
    final = CompositeVideoClip([bg, subtitle_clip])
    final = final.with_audio(audio)

    # Export with GPU or CPU encoding
    codec, ffmpeg_params = get_gpu_codec(gpu, threads)
    print(f"\nRendering: {output_path}")
    print(f"Encoder: {codec}" + (f" (threads: {threads})" if threads > 0 else ""))

    final.write_videofile(
        output_path,
        fps=FPS,
        codec=codec,
        audio_codec='aac',
        ffmpeg_params=ffmpeg_params,
        logger='bar'
    )

    # Cleanup temp directory
    if threads > 1 and temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
        print("Cleaned up temp frames")

    print(f"Done! {output_path}")
    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Create video with styled subtitles")
    parser.add_argument("script", help="Path to styled script file")
    parser.add_argument("audio", help="Path to audio file")
    parser.add_argument("timestamps", nargs="?", help="Path to timestamps JSON")
    parser.add_argument("-o", "--output", help="Output video path")
    parser.add_argument("--bg", dest="background", help="Single background video")
    parser.add_argument("--bg-dir", dest="backgrounds_dir", help="Directory with background videos (uses catalog.json)")
    parser.add_argument("--darken", type=float, default=BG_DARKEN, help=f"Darken factor 0-1 (default: {BG_DARKEN})")
    parser.add_argument("--desaturate", type=float, default=BG_DESATURATE, help=f"Desaturate factor 0-1 (default: {BG_DESATURATE})")
    parser.add_argument("--gpu", choices=['nvenc', 'amd', 'intel', 'auto'], default=None,
                        help="Use GPU encoding: nvenc (NVIDIA), amd, intel, or auto-detect")
    parser.add_argument("--threads", type=int, default=0,
                        help="CPU threads for encoding (0=auto, default: 0)")
    parser.add_argument("--hook", dest="hook_video", help="Path to hook video (plays first)")
    parser.add_argument("--hook-duration", type=float, default=0,
                        help="Duration of hook video to use (0=full video)")
    parser.add_argument("--freeze-duration", type=float, default=3.0,
                        help="Duration of freeze frame after hook (default: 3.0)")
    args = parser.parse_args()

    # Defaults
    audio_path = Path(args.audio)
    if not args.timestamps:
        args.timestamps = str(audio_path.parent / f"{audio_path.stem}_timestamps.json")
    if not args.output:
        args.output = str(audio_path.parent / f"{audio_path.stem}_styled.mp4")

    # Default backgrounds directory
    if not args.backgrounds_dir and not args.background:
        default_bg_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads", "backgrounds")
        if os.path.exists(os.path.join(default_bg_dir, "catalog.json")):
            args.backgrounds_dir = default_bg_dir

    create_styled_video(
        script_path=args.script,
        audio_path=args.audio,
        timestamps_path=args.timestamps,
        output_path=args.output,
        background_path=args.background,
        backgrounds_dir=args.backgrounds_dir,
        darken=args.darken,
        desaturate=args.desaturate,
        gpu=args.gpu,
        threads=args.threads,
        hook_video=args.hook_video,
        hook_duration=args.hook_duration,
        freeze_duration=args.freeze_duration
    )


if __name__ == "__main__":
    main()

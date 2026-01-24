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


def create_styled_video(
    script_path: str,
    audio_path: str,
    timestamps_path: str,
    output_path: str,
    background_path: str = None,
    backgrounds_dir: str = None,
    darken: float = BG_DARKEN,
    desaturate: float = BG_DESATURATE
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

    # Create subtitle clip with alpha channel (cached for performance)
    frame_cache = {}

    def get_cached_frame(t):
        # Round to frame time for caching
        frame_key = round(t * FPS)
        if frame_key not in frame_cache:
            frame_cache[frame_key] = render_frame(t, pages, fonts)
        return frame_cache[frame_key]

    def make_subtitle_frame(t):
        rgba = get_cached_frame(t)
        return rgba[:, :, :3]  # RGB only

    def make_subtitle_mask(t):
        rgba = get_cached_frame(t)
        return rgba[:, :, 3] / 255.0  # Alpha as grayscale 0-1

    subtitle_clip = VideoClip(make_subtitle_frame, duration=duration).set_fps(FPS)
    subtitle_mask = VideoClip(make_subtitle_mask, duration=duration, ismask=True).set_fps(FPS)
    subtitle_clip = subtitle_clip.set_mask(subtitle_mask)

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
                clip = clip.resize((WIDTH, HEIGHT))

                # Pre-apply darken and desaturate effects using fl_image
                def apply_effects(frame, d=darken, ds=desaturate):
                    return process_background_frame(frame, darken=d, desaturate=ds)

                clip = clip.fl_image(apply_effects)
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

        bg = VideoClip(make_bg_frame, duration=duration).set_fps(FPS)

    else:
        # Fallback to solid color
        print("\nUsing solid color background")
        bg = ColorClip(size=(WIDTH, HEIGHT), color=(15, 15, 20), duration=duration)

    # Composite
    final = CompositeVideoClip([bg, subtitle_clip])
    final = final.set_audio(audio)

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
    parser.add_argument("--bg", dest="background", help="Single background video")
    parser.add_argument("--bg-dir", dest="backgrounds_dir", help="Directory with background videos (uses catalog.json)")
    parser.add_argument("--darken", type=float, default=BG_DARKEN, help=f"Darken factor 0-1 (default: {BG_DARKEN})")
    parser.add_argument("--desaturate", type=float, default=BG_DESATURATE, help=f"Desaturate factor 0-1 (default: {BG_DESATURATE})")
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
        desaturate=args.desaturate
    )


if __name__ == "__main__":
    main()

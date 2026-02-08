"""
Styled Subtitles - Word-by-word subtitles with custom styling markup

Формат разметки:
    **слово**           - акцент (большой, белый, жирный)
    *слово*             - выделение (средний, жёлтый)
    _слово_             - приглушённый (мелкий, серый)
    [c:FF5500]слово[/]  - явный цвет (hex без #)
    [s:120]слово[/]     - явный размер (px)
    [c:red,s:80]слово[/] - комбинация
    [img:filename.jpg]  - вставка изображения с эффектом pop (default)
    [img:filename.jpg:slide_left]  - вставка с эффектом slide слева
    [img:filename.jpg:slide_right] - вставка с эффектом slide справа
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
    from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip, ImageClip, concatenate_videoclips
except ImportError:
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ColorClip, VideoClip, ImageClip, concatenate_videoclips

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

# Image overlay settings
IMAGE_MAX_WIDTH = 420  # Max width for overlay images (px)
IMAGE_MAX_HEIGHT = 380  # Max height for overlay images (px)
IMAGE_AREA_Y = 450  # Y position for images center (above text area which starts at 700)
IMAGE_CORNER_RADIUS = 16  # Rounded corners
IMAGE_SHADOW_OFFSET = 6  # Shadow offset
IMAGE_SHADOW_BLUR = 12  # Shadow blur radius

# Pop effect settings (no drift - static after pop-in)
POP_DURATION = 0.20  # Duration of pop-in animation
POP_OVERSHOOT = 1.05  # Scale overshoot (105%) - subtle bounce
DRIFT_SPEED = 0.0  # No zoom drift (was 0.002)
FADE_OUT_DURATION = 0.15  # Fade out duration
SLIDE_DURATION = 0.35  # Duration of slide-in animation
VALID_EFFECTS = {'pop', 'slide_left', 'slide_right'}

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


@dataclass
class ImageOverlay:
    """An image overlay with timing and effect information."""
    filename: str  # Image filename (relative to images/ or absolute)
    page_idx: int = 0  # Which page this image belongs to
    effect: str = "pop"  # Animation effect: pop, slide_left, slide_right

    # Timing (filled from page timing)
    start: float = 0.0
    end: float = 0.0

    # Position and size (calculated during layout)
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    # Loaded image (PIL Image, filled during rendering)
    _image: Optional[Image.Image] = field(default=None, repr=False)


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


def parse_styled_text(text: str) -> Tuple[List[StyledWord], List[ImageOverlay]]:
    """
    Parse text with styling markup into list of StyledWord objects and ImageOverlay objects.

    Markup:
        **word** - accent (large, white)
        *word*   - highlight (medium, yellow)
        _word_   - muted (small, gray)
        [c:color]word[/] - custom color
        [s:size]word[/]  - custom size
        [c:color,s:size]word[/] - combo
        [img:filename.jpg] - image overlay (pop effect)
        [img:filename.jpg:effect] - image with effect (pop/slide_left/slide_right)
        ---      - page break
    """
    words = []
    images = []
    current_page_idx = 0

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
            current_page_idx += 1

        # Process this part
        part = part.strip()
        if not part:
            continue

        # Tokenize while preserving markup
        # Pattern to match styled segments (added image pattern)
        pattern = r'''
            (\[img:[^\]]+\])          |  # [img:filename]
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

            # [img:filename] or [img:filename:effect]
            if token.startswith('[img:') and token.endswith(']'):
                img_content = token[5:-1].strip()
                # Parse optional effect: [img:file.jpg:slide_left]
                parts = img_content.rsplit(':', 1)
                if len(parts) == 2 and parts[1] in VALID_EFFECTS:
                    filename = parts[0].strip()
                    effect = parts[1].strip()
                else:
                    filename = img_content
                    effect = "pop"
                images.append(ImageOverlay(
                    filename=filename,
                    page_idx=current_page_idx,
                    effect=effect
                ))
                continue  # Don't add as word

            # **accent**
            elif token.startswith('**') and token.endswith('**'):
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

    return words, images


def normalize_for_match(text: str) -> str:
    """Normalize text for matching: lowercase, alphanumeric, ё→е."""
    text = text.lower().replace('ё', 'е')
    return ''.join(c for c in text if c.isalnum())


def apply_timestamps(words: List[StyledWord], timestamps: List[dict]) -> List[StyledWord]:
    """
    Apply timing from Whisper timestamps to styled words.
    Matches words by text similarity with lookahead to handle mismatches.
    """
    if not timestamps:
        return words

    ts_idx = 0
    MAX_LOOKAHEAD = 10  # Max timestamps to look ahead for a match

    for word_idx, word in enumerate(words):
        # Find matching timestamp
        word_clean = normalize_for_match(word.text)

        # Skip punctuation-only words (they clean to empty string)
        if not word_clean:
            # Estimate from previous word
            if word_idx > 0:
                prev = words[word_idx - 1]
                word.start = prev.end
                word.end = prev.end + 0.1
            continue

        # Search for match with limited lookahead
        found = False
        search_start = ts_idx
        search_end = min(ts_idx + MAX_LOOKAHEAD, len(timestamps))

        for search_idx in range(search_start, search_end):
            ts = timestamps[search_idx]
            ts_clean = normalize_for_match(ts['word'])

            # Skip empty timestamp words
            if not ts_clean:
                continue

            # Check for match (exact or partial)
            if word_clean == ts_clean or word_clean in ts_clean or ts_clean in word_clean:
                word.start = ts['start']
                word.end = ts['end']
                ts_idx = search_idx + 1  # Move past this timestamp
                found = True
                break

        # If no match found, estimate from previous word
        if not found:
            if word_idx > 0:
                prev = words[word_idx - 1]
                word.start = prev.end + 0.05
                word.end = word.start + 0.3
            # Don't advance ts_idx - keep looking from same position

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
    if len(args) == 6:
        frame_idx, t, pages_data, font_path, output_path, bg_info = args
        images_data = None
    else:
        frame_idx, t, pages_data, font_path, output_path, bg_info, images_data = args

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

    # Reconstruct images from serializable data
    images = None
    if images_data:
        images = []
        for img_data in images_data:
            img_overlay = ImageOverlay(
                filename=img_data['filename'],
                page_idx=img_data['page_idx'],
                effect=img_data.get('effect', 'pop'),
                start=img_data['start'],
                end=img_data['end'],
                x=img_data['x'],
                y=img_data['y'],
                width=img_data['width'],
                height=img_data['height']
            )
            # Load image from cached path
            if img_data.get('cached_path') and os.path.exists(img_data['cached_path']):
                img_overlay._image = Image.open(img_data['cached_path']).convert('RGBA')
            images.append(img_overlay)

    # Render subtitle frame (RGBA)
    subtitle_frame = render_frame(t, pages, fonts, images=images)

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


def serialize_images(images: List['ImageOverlay'], temp_dir: str) -> List[dict]:
    """Convert images to serializable format for multiprocessing.
    Saves images to temp files and returns paths."""
    if not images:
        return None

    result = []
    for i, img in enumerate(images):
        # Save image to temp file for workers to load
        cached_path = None
        if img._image:
            cached_path = os.path.join(temp_dir, f'img_cache_{i}.png')
            img._image.save(cached_path, 'PNG')

        result.append({
            'filename': img.filename,
            'page_idx': img.page_idx,
            'effect': img.effect,
            'start': img.start,
            'end': img.end,
            'x': img.x,
            'y': img.y,
            'width': img.width,
            'height': img.height,
            'cached_path': cached_path
        })
    return result


def ease_out_back(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_out_elastic(t: float) -> float:
    """Elastic ease-out for bouncy pop effect."""
    if t == 0 or t == 1:
        return t
    p = 0.3
    s = p / 4
    return pow(2, -10 * t) * math.sin((t - s) * (2 * math.pi) / p) + 1


def load_and_prepare_image(image_path: str, max_width: int = IMAGE_MAX_WIDTH,
                           max_height: int = IMAGE_MAX_HEIGHT) -> Optional[Image.Image]:
    """Load image and prepare it with rounded corners and shadow."""
    if not os.path.exists(image_path):
        print(f"  Warning: Image not found: {image_path}")
        return None

    try:
        img = Image.open(image_path).convert('RGBA')

        # Resize to fit max dimensions while preserving aspect ratio
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Add rounded corners
        img = add_rounded_corners(img, IMAGE_CORNER_RADIUS)

        return img
    except Exception as e:
        print(f"  Warning: Could not load image {image_path}: {e}")
        return None


def add_rounded_corners(img: Image.Image, radius: int) -> Image.Image:
    """Add rounded corners to image."""
    # Create mask for rounded corners
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)

    # Apply mask
    result = img.copy()
    result.putalpha(mask)

    return result


def create_image_with_shadow(img: Image.Image, shadow_offset: int = IMAGE_SHADOW_OFFSET,
                             shadow_blur: int = IMAGE_SHADOW_BLUR) -> Image.Image:
    """Create image with drop shadow for depth."""
    # Calculate canvas size (image + shadow space)
    padding = shadow_blur * 2 + shadow_offset
    canvas_size = (img.width + padding * 2, img.height + padding * 2)

    # Create shadow
    shadow = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    shadow_layer = Image.new('RGBA', img.size, (0, 0, 0, 180))

    # Apply rounded corners to shadow
    shadow_layer = add_rounded_corners(shadow_layer, IMAGE_CORNER_RADIUS)

    # Paste shadow offset
    shadow.paste(shadow_layer, (padding + shadow_offset, padding + shadow_offset))

    # Blur shadow
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=shadow_blur))

    # Paste original image
    shadow.paste(img, (padding, padding), img)

    return shadow


def render_image_pop_drift(img: Image.Image, t: float, start: float, end: float,
                           center_x: float, center_y: float) -> Optional[Tuple[Image.Image, int, int]]:
    """
    Render image with pop_drift effect.
    Returns (processed_image, x, y) or None if not visible.

    Effect:
    - Pop in: Quick scale from 0 to 108% then settle to 100% (0.18s)
    - Drift: Slow continuous zoom while visible (0.2% per frame)
    - Fade out: Quick alpha fade (0.12s)
    """
    if t < start or t > end + FADE_OUT_DURATION:
        return None

    # Calculate animation phases
    time_in = t - start
    duration = end - start

    # Phase 1: Pop in (0 to POP_DURATION)
    if time_in < POP_DURATION:
        progress = time_in / POP_DURATION
        # Use elastic ease for bouncy pop
        eased = ease_out_elastic(progress)
        scale = eased * POP_OVERSHOOT
        if progress > 0.7:
            # Settle from overshoot to 1.0
            settle_progress = (progress - 0.7) / 0.3
            scale = POP_OVERSHOOT - (POP_OVERSHOOT - 1.0) * settle_progress
        alpha = min(255, int(255 * progress * 2))  # Quick fade in

    # Phase 2: Drift (POP_DURATION to end)
    elif t <= end:
        drift_time = time_in - POP_DURATION
        # Continuous slow zoom
        scale = 1.0 + drift_time * DRIFT_SPEED * FPS
        alpha = 255

    # Phase 3: Fade out (end to end + FADE_OUT_DURATION)
    else:
        fade_progress = (t - end) / FADE_OUT_DURATION
        scale = 1.0 + (duration - POP_DURATION) * DRIFT_SPEED * FPS
        alpha = int(255 * (1 - fade_progress))

    if alpha <= 0:
        return None

    # Apply scale
    new_width = int(img.width * scale)
    new_height = int(img.height * scale)

    if new_width <= 0 or new_height <= 0:
        return None

    scaled = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Apply alpha
    if alpha < 255:
        # Modify alpha channel
        r, g, b, a = scaled.split()
        a = a.point(lambda x: int(x * alpha / 255))
        scaled = Image.merge('RGBA', (r, g, b, a))

    # Calculate position (centered)
    x = int(center_x - new_width / 2)
    y = int(center_y - new_height / 2)

    return scaled, x, y


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out for smooth deceleration."""
    return 1 - pow(1 - t, 3)


def render_image_slide(img: Image.Image, t: float, start: float, end: float,
                       center_x: float, center_y: float,
                       direction: str = "left") -> Optional[Tuple[Image.Image, int, int]]:
    """
    Render image with slide effect.
    Returns (processed_image, x, y) or None if not visible.

    Effect:
    - Slide in from left/right edge to center (SLIDE_DURATION)
    - Static while page is visible
    - Fade out at page end (FADE_OUT_DURATION)
    """
    if t < start or t > end + FADE_OUT_DURATION:
        return None

    time_in = t - start
    alpha = 255

    # Calculate X offset for slide
    if direction == "left":
        off_screen_x = -img.width  # Start fully off-screen left
    else:
        off_screen_x = WIDTH + img.width  # Start fully off-screen right

    target_x = int(center_x - img.width / 2)

    # Phase 1: Slide in (0 to SLIDE_DURATION)
    if time_in < SLIDE_DURATION:
        progress = time_in / SLIDE_DURATION
        eased = ease_out_cubic(progress)
        x = int(off_screen_x + (target_x - off_screen_x) * eased)
        alpha = min(255, int(255 * progress * 3))  # Quick fade in

    # Phase 2: Static (SLIDE_DURATION to end)
    elif t <= end:
        x = target_x

    # Phase 3: Fade out (end to end + FADE_OUT_DURATION)
    else:
        fade_progress = (t - end) / FADE_OUT_DURATION
        x = target_x
        alpha = int(255 * (1 - fade_progress))

    if alpha <= 0:
        return None

    y = int(center_y - img.height / 2)

    # Apply alpha
    if alpha < 255:
        result = img.copy()
        r, g, b, a = result.split()
        a = a.point(lambda v: int(v * alpha / 255))
        result = Image.merge('RGBA', (r, g, b, a))
        return result, x, y

    return img, x, y


def render_image_effect(img: Image.Image, t: float, start: float, end: float,
                        center_x: float, center_y: float,
                        effect: str = "pop") -> Optional[Tuple[Image.Image, int, int]]:
    """Dispatch to the correct render function based on effect type."""
    if effect == "slide_left":
        return render_image_slide(img, t, start, end, center_x, center_y, direction="left")
    elif effect == "slide_right":
        return render_image_slide(img, t, start, end, center_x, center_y, direction="right")
    else:  # pop (default)
        return render_image_pop_drift(img, t, start, end, center_x, center_y)


def prepare_images_for_pages(images: List[ImageOverlay], page_times: List[Tuple[float, float]],
                             script_dir: str) -> List[ImageOverlay]:
    """Load images and assign timing based on page times."""
    # Get project root (parent of script_dir or where input/ is)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for img_overlay in images:
        # Find image file
        if os.path.isabs(img_overlay.filename):
            image_path = img_overlay.filename
        else:
            image_path = None
            # Search paths in priority order
            search_paths = [
                os.path.join(project_root, 'input', 'images', img_overlay.filename),
                os.path.join(script_dir, 'images', img_overlay.filename),
                os.path.join(script_dir, img_overlay.filename),
                os.path.join(project_root, 'downloads', 'images', img_overlay.filename),
            ]
            for path in search_paths:
                if os.path.exists(path):
                    image_path = path
                    break
            if not image_path:
                image_path = search_paths[0]  # Default for error message

        # Load and prepare image
        img = load_and_prepare_image(image_path)
        if img:
            # Add shadow
            img = create_image_with_shadow(img)
            img_overlay._image = img
            img_overlay.width = img.width
            img_overlay.height = img.height

            # Calculate center position (above text area)
            img_overlay.x = WIDTH // 2
            # Center image at IMAGE_AREA_Y (safe zone above text)
            img_overlay.y = IMAGE_AREA_Y

            # Set timing from page
            if img_overlay.page_idx < len(page_times):
                start, end = page_times[img_overlay.page_idx]
                img_overlay.start = start
                img_overlay.end = end
            else:
                print(f"  Warning: Image page_idx {img_overlay.page_idx} out of range")

            print(f"  Loaded image: {img_overlay.filename} ({img.width}x{img.height}) for page {img_overlay.page_idx + 1}")
        else:
            print(f"  Warning: Could not load image: {img_overlay.filename}")

    return [img for img in images if img._image is not None]


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


def render_frame(t: float, pages: List[List[StyledWord]], fonts: dict,
                 all_words: List[StyledWord] = None, images: List[ImageOverlay] = None) -> np.ndarray:
    """Render frame at time t with enhanced glow effect and image overlays."""
    img = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Render images first (behind text)
    if images:
        for img_overlay in images:
            if img_overlay._image is None:
                continue
            result = render_image_effect(
                img_overlay._image, t,
                img_overlay.start, img_overlay.end,
                img_overlay.x, img_overlay.y,
                img_overlay.effect
            )
            if result:
                rendered_img, x, y = result
                # Paste image onto frame
                img.paste(rendered_img, (x, y), rendered_img)

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


def _create_marker_icon(size=72):
    """Create a light bulb emoji PNG for timeline CTA marker."""
    import tempfile
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    rendered = False
    for font_path in [r"C:\Windows\Fonts\seguiemj.ttf",
                      "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"]:
        try:
            font = ImageFont.truetype(font_path, int(size * 0.85))
            bbox = font.getbbox("\U0001F4A1")  # 💡
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (size - tw) // 2
            y = (size - th) // 2 - bbox[1]
            draw.text((x, y), "\U0001F4A1", font=font, embedded_color=True)
            rendered = True
            break
        except Exception:
            continue

    if not rendered:
        # Fallback: yellow circle with bulb shape
        cx, cy = size // 2, size // 2
        r = size // 2 - 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 50, 230))

    path = os.path.join(tempfile.gettempdir(), 'bloom_marker_progress.png')
    img.save(path)
    return path


def _load_font(size):
    """Load Montserrat-Bold at given size, with fallbacks."""
    from PIL import ImageFont
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'downloads', 'fonts')
    for fp in [os.path.join(base, 'Montserrat-Bold.ttf'),
               os.path.join(base, 'RussoOne-Regular.ttf'),
               r"C:\Windows\Fonts\arialbd.ttf"]:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _create_cta_image(segments, padding_x=40, padding_y=24):
    """Create styled CTA overlay PNG with per-line color/size.

    Args:
        segments: list of {text, color, size} dicts  -OR-  plain str (legacy).
    Returns:
        (path, width, height)
    """
    import tempfile
    from PIL import Image, ImageDraw

    # Legacy: plain string → white lines at 40px
    if isinstance(segments, str):
        segments = [{"text": ln, "color": (255, 255, 255), "size": 40}
                    for ln in segments.split('\n')]

    line_spacing = 12
    fonts, widths, heights = [], [], []
    for seg in segments:
        f = _load_font(seg.get("size", 40))
        fonts.append(f)
        bbox = f.getbbox(seg["text"])
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])

    max_w = max(widths)
    total_h = sum(heights) + line_spacing * (len(segments) - 1)
    img_w = max_w + padding_x * 2
    img_h = total_h + padding_y * 2

    img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, img_w - 1, img_h - 1],
                           radius=22, fill=(0, 0, 0, 180))

    y = padding_y
    for i, seg in enumerate(segments):
        lw = widths[i]
        x = (img_w - lw) // 2
        color = tuple(seg.get("color", (255, 255, 255))) + (255,)
        draw.text((x, y), seg["text"], fill=color, font=fonts[i])
        y += heights[i] + line_spacing

    name = f'bloom_cta_{abs(hash(str(segments))) % 100000}.png'
    path = os.path.join(tempfile.gettempdir(), name)
    img.save(path)
    return path, img_w, img_h


def render_countdown_video(
    duration: float = 5.0,
    output_path: str = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> str:
    """
    Render a countdown timer video (5.00→0.00) with beep audio.

    Picks one of several visually distinct themes at random:
      neon_glow, rgb_glitch, minimal, fire, progress_ring, matrix
    """
    import tempfile
    import wave
    import math
    import random
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    if output_path is None:
        output_path = os.path.join(tempfile.gettempdir(), 'bloom_countdown.mp4')

    ffmpeg = get_ffmpeg_path()
    temp_dir = tempfile.mkdtemp(prefix='bloom_cd_')
    dur = duration
    total_frames = int(dur * fps)

    # ---- Load a valid font ----
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'downloads', 'fonts')
    font_path = None
    for f in [os.path.join(fonts_dir, 'Montserrat-Bold.ttf'),
              os.path.join(fonts_dir, 'BebasNeue-Regular.ttf'),
              os.path.join(fonts_dir, 'RussoOne-Regular.ttf')]:
        if os.path.exists(f):
            try:
                ImageFont.truetype(f, 40)
                font_path = f
                break
            except Exception:
                pass

    def _mk_font(sz):
        if font_path:
            return ImageFont.truetype(font_path, sz)
        return _load_font(sz)

    # ---- Pick theme ----
    THEMES = ['neon_glow', 'rgb_glitch', 'minimal', 'fire', 'progress_ring', 'matrix']
    theme = random.choice(THEMES)

    # Beep pitch (always randomized)
    beep_base = random.choice([660, 770, 880, 990, 1100])
    beep_final = beep_base + random.randint(300, 600)

    print(f"Countdown theme: {theme}, beep={beep_base}Hz")

    # ---- Generate beep audio as WAV ----
    sample_rate = 44100
    total_samples = int(dur * sample_rate)
    audio_data = np.zeros(total_samples, dtype=np.float32)
    for sec in range(int(dur) + 1):
        s0 = int(sec * sample_rate)
        if sec < int(dur):
            bd, fr, vol = 0.08, beep_base, 0.6
        else:
            bd, fr, vol = 0.25, beep_final, 0.8
        n = int(bd * sample_rate)
        tt = np.arange(n, dtype=np.float32) / sample_rate
        beep_sig = np.sin(2 * np.pi * fr * tt) * vol * np.exp(-tt * 10)
        e = min(s0 + n, total_samples)
        audio_data[s0:e] = beep_sig[:e - s0]

    wav_path = os.path.join(temp_dir, 'beeps.wav')
    pcm = (audio_data * 32767).astype(np.int16)
    with wave.open(wav_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())

    # ---- Helper: lerp color ----
    def _lerp(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * max(0, min(1, t))) for i in range(3))

    # =================================================================
    # THEME DEFINITIONS — each defines render_frame(fi) -> PIL Image
    # =================================================================

    if theme == 'neon_glow':
        # Bright neon glow on black, color shifts cyan→magenta→white
        font_main = _mk_font(200)
        font_label = _mk_font(34)
        glow_r = 16
        pad = glow_r * 3
        c_phases = [(0, 255, 255), (255, 0, 255), (255, 255, 255)]

        def _color(rem):
            if rem > dur * 0.5:
                return c_phases[0]
            elif rem > dur * 0.15:
                return _lerp(c_phases[0], c_phases[1], 1.0 - (rem - dur*0.15)/(dur*0.35))
            else:
                return _lerp(c_phases[1], c_phases[2], 1.0 - rem/(dur*0.15))

        bg_bytes = b'\x00' * (width * 3) * height

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            text = f"{int(rem)}.{int((rem - int(rem)) * 100) % 100:02d}"
            color = _color(rem)
            # pulse
            frac = t - math.floor(t)
            pulse = 1.0 + 0.15 * max(0, 1 - frac / 0.15) if frac < 0.15 else 1.0

            bbox = font_main.getbbox(text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cw, ch = tw + pad*2, th + pad*2 + 60

            canvas = Image.new('RGB', (cw, ch), (0, 0, 0))
            d = ImageDraw.Draw(canvas)
            gx, gy = (cw-tw)//2, (ch-60-th)//2 - bbox[1]
            # Double glow: inner + outer
            d.text((gx, gy), text, fill=color, font=font_main)
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=glow_r))
            d2 = ImageDraw.Draw(canvas)
            d2.text((gx, gy), text, fill=color, font=font_main)
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=glow_r // 3))
            d3 = ImageDraw.Draw(canvas)
            d3.text((gx, gy), text, fill=(255, 255, 255), font=font_main)
            # label
            lb = font_label.getbbox("BLOOM")
            d3.text(((cw - lb[2] + lb[0]) // 2, (ch-60-th)//2 + th + 14),
                    "BLOOM", fill=(color[0]//2, color[1]//2, color[2]//2), font=font_label)

            if abs(pulse - 1.0) > 0.01:
                canvas = canvas.resize((int(cw*pulse), int(ch*pulse)), Image.LANCZOS)

            frame = Image.frombytes('RGB', (width, height), bg_bytes)
            frame.paste(canvas, ((width-canvas.width)//2, (height-canvas.height)//2 - 80))

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height), (255,255,255)), a * 0.8)
            return frame

    elif theme == 'rgb_glitch':
        # RGB channel offset glitch — red/green/blue separated
        font_main = _mk_font(190)
        font_label = _mk_font(30)
        bg_bytes = b'\x00' * (width * 3) * height

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            text = f"{int(rem)}.{int((rem - int(rem)) * 100) % 100:02d}"
            # Glitch offset — bigger as time runs out
            glitch = int(6 + (1 - rem / dur) * 14)
            jitter = random.randint(-3, 3) if (fi % 3 == 0) else 0

            bbox = font_main.getbbox(text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cx, cy = (width - tw) // 2, (height - th) // 2 - 80 - bbox[1]

            frame = Image.new('RGB', (width, height), (0, 0, 0))
            # Draw each channel offset
            for ch_idx, (color, dx, dy) in enumerate([
                ((255, 0, 0), -glitch + jitter, -2),
                ((0, 255, 0), 0, 0),
                ((0, 80, 255), glitch - jitter, 2),
            ]):
                layer = Image.new('RGB', (width, height), (0, 0, 0))
                ld = ImageDraw.Draw(layer)
                ld.text((cx + dx, cy + dy), text, fill=color, font=font_main)
                frame = Image.composite(
                    Image.new('RGB', (width, height), (255,255,255)),
                    frame,
                    layer.convert('L')
                ) if ch_idx > 0 else layer
            # Merge: add channels
            r_layer = Image.new('RGB', (width, height), (0,0,0))
            g_layer = Image.new('RGB', (width, height), (0,0,0))
            b_layer = Image.new('RGB', (width, height), (0,0,0))
            for layer, color, dx, dy in [
                (r_layer, (255,0,0), -glitch+jitter, -2),
                (g_layer, (0,255,0), 0, 0),
                (b_layer, (0,80,255), glitch-jitter, 2),
            ]:
                ImageDraw.Draw(layer).text((cx+dx, cy+dy), text, fill=color, font=font_main)

            r_arr = np.array(r_layer)
            g_arr = np.array(g_layer)
            b_arr = np.array(b_layer)
            merged = np.clip(r_arr.astype(int) + g_arr.astype(int) + b_arr.astype(int), 0, 255).astype(np.uint8)
            frame = Image.fromarray(merged)

            # Label
            ld = ImageDraw.Draw(frame)
            lb = font_label.getbbox("BLOOM")
            ld.text(((width - lb[2] + lb[0]) // 2, cy + th + bbox[1] + 20),
                    "BLOOM", fill=(100, 100, 100), font=font_label)

            # Scanline effect — every other row darkened
            if fi % 2 == 0:
                arr = np.array(frame)
                arr[::3, :, :] = (arr[::3, :, :] * 0.7).astype(np.uint8)
                frame = Image.fromarray(arr)

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height), (255,255,255)), a * 0.8)
            return frame

    elif theme == 'minimal':
        # Clean white on dark gray, thin, no glow, big whole seconds
        font_big = _mk_font(280)
        font_small = _mk_font(80)
        font_label = _mk_font(28)
        bg_color = (18, 18, 22)
        bg_bytes = bytes(bg_color) * (width * height)

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            secs = int(rem)
            centis = int((rem - secs) * 100) % 100

            frame = Image.frombytes('RGB', (width, height), bg_bytes)
            d = ImageDraw.Draw(frame)

            # Big second number
            big_text = str(secs)
            bb = font_big.getbbox(big_text)
            bw, bh = bb[2] - bb[0], bb[3] - bb[1]
            bx = (width - bw) // 2
            by = height // 2 - bh - 20 - bb[1]
            # Fade color: white → dim red
            bright = int(180 + 75 * (rem / dur))
            txt_color = (bright, bright, bright) if rem > 1.0 else (255, int(80 * rem), int(40 * rem))
            d.text((bx, by), big_text, fill=txt_color, font=font_big)

            # Small centiseconds
            small_text = f".{centis:02d}"
            sb = font_small.getbbox(small_text)
            sw = sb[2] - sb[0]
            sx = (width - sw) // 2
            sy = by + bh + bb[1] + 8
            d.text((sx, sy), small_text, fill=(120, 120, 120), font=font_small)

            # Thin progress line at bottom
            line_y = height - 200
            line_w = int(width * 0.7)
            line_x = (width - line_w) // 2
            progress = rem / dur
            d.rectangle([line_x, line_y, line_x + line_w, line_y + 4], fill=(50, 50, 50))
            d.rectangle([line_x, line_y, line_x + int(line_w * progress), line_y + 4], fill=txt_color)

            # Label
            lb = font_label.getbbox("BLOOM")
            d.text(((width - lb[2] + lb[0]) // 2, line_y + 20),
                   "BLOOM", fill=(60, 60, 60), font=font_label)

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height), (255,255,255)), a * 0.7)
            return frame

    elif theme == 'fire':
        # Orange/red hot countdown, heavy glow, dark red background
        font_main = _mk_font(200)
        font_label = _mk_font(34)
        glow_r = 20
        pad = glow_r * 3
        bg_color = (15, 2, 2)
        bg_bytes = bytes(bg_color) * (width * height)

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            text = f"{int(rem)}.{int((rem - int(rem)) * 100) % 100:02d}"
            # Fire color: orange → bright yellow → white-hot
            heat = 1.0 - rem / dur
            color = _lerp((255, 80, 0), (255, 255, 100), heat)
            # Flicker
            flicker = random.uniform(0.85, 1.0)
            color = tuple(int(c * flicker) for c in color)
            # pulse
            frac = t - math.floor(t)
            pulse = 1.0 + 0.12 * max(0, 1 - frac / 0.15) if frac < 0.15 else 1.0

            bbox = font_main.getbbox(text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cw, ch = tw + pad*2, th + pad*2 + 60

            canvas = Image.new('RGB', (cw, ch), bg_color)
            d = ImageDraw.Draw(canvas)
            gx, gy = (cw-tw)//2, (ch-60-th)//2 - bbox[1]
            d.text((gx, gy), text, fill=color, font=font_main)
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=glow_r))
            d2 = ImageDraw.Draw(canvas)
            d2.text((gx, gy), text, fill=(255, 255, min(255, int(200 * heat + 55))), font=font_main)
            # label
            lb = font_label.getbbox("BLOOM")
            d2.text(((cw - lb[2] + lb[0]) // 2, (ch-60-th)//2 + th + 14),
                    "BLOOM", fill=(color[0]//3, color[1]//3, 0), font=font_label)

            if abs(pulse - 1.0) > 0.01:
                canvas = canvas.resize((int(cw*pulse), int(ch*pulse)), Image.LANCZOS)

            frame = Image.frombytes('RGB', (width, height), bg_bytes)
            frame.paste(canvas, ((width-canvas.width)//2, (height-canvas.height)//2 - 80))

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height), (255,200,50)), a * 0.8)
            return frame

    elif theme == 'progress_ring':
        # Circular progress ring around the number
        font_main = _mk_font(160)
        font_label = _mk_font(30)
        ring_color = random.choice([(0, 200, 255), (0, 255, 130), (255, 100, 200), (255, 200, 0)])
        ring_radius = 260
        ring_width = 14
        bg_bytes = b'\x00' * (width * 3) * height

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            text = f"{int(rem)}.{int((rem - int(rem)) * 100) % 100:02d}"
            progress = rem / dur

            frame = Image.frombytes('RGB', (width, height), bg_bytes)
            d = ImageDraw.Draw(frame)

            # Ring arc
            cx_r, cy_r = width // 2, height // 2 - 80
            arc_box = [cx_r - ring_radius, cy_r - ring_radius,
                       cx_r + ring_radius, cy_r + ring_radius]
            # Background ring (dark)
            d.arc(arc_box, 0, 360, fill=(40, 40, 40), width=ring_width)
            # Progress arc (colored) — from top (-90°)
            sweep = int(360 * progress)
            if sweep > 0:
                d.arc(arc_box, -90, -90 + sweep, fill=ring_color, width=ring_width)

            # Dot at end of arc
            angle_rad = math.radians(-90 + sweep)
            dot_x = cx_r + int(ring_radius * math.cos(angle_rad))
            dot_y = cy_r + int(ring_radius * math.sin(angle_rad))
            d.ellipse([dot_x - 10, dot_y - 10, dot_x + 10, dot_y + 10], fill=ring_color)

            # Text centered
            bbox = font_main.getbbox(text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = (width - tw) // 2
            ty = cy_r - th // 2 - bbox[1]
            d.text((tx, ty), text, fill=(255, 255, 255), font=font_main)

            # Label below ring
            lb = font_label.getbbox("BLOOM")
            d.text(((width - lb[2] + lb[0]) // 2, cy_r + ring_radius + 30),
                   "BLOOM", fill=(ring_color[0]//2, ring_color[1]//2, ring_color[2]//2),
                   font=font_label)

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height),
                                    (ring_color[0], ring_color[1], ring_color[2])), a * 0.5)
            return frame

    elif theme == 'matrix':
        # Green "Matrix" rain with countdown
        font_main = _mk_font(200)
        font_label = _mk_font(30)
        font_rain = _mk_font(18)
        rain_chars = "01アイウエオカキクケコ"
        # Init rain columns
        n_cols = width // 20
        rain_y = [random.randint(-height, 0) for _ in range(n_cols)]
        rain_speed = [random.randint(8, 25) for _ in range(n_cols)]
        bg_bytes = b'\x00' * (width * 3) * height

        def render_frame(fi):
            t = fi / fps
            rem = max(0.0, dur - t)
            text = f"{int(rem)}.{int((rem - int(rem)) * 100) % 100:02d}"

            frame = Image.frombytes('RGB', (width, height), bg_bytes)
            d = ImageDraw.Draw(frame)

            # Rain
            for col in range(n_cols):
                rain_y[col] += rain_speed[col]
                if rain_y[col] > height + 200:
                    rain_y[col] = random.randint(-400, -20)
                    rain_speed[col] = random.randint(8, 25)
                x = col * 20
                for row in range(12):
                    ry = rain_y[col] - row * 22
                    if 0 <= ry < height:
                        brightness = max(30, 200 - row * 18)
                        ch_char = random.choice(rain_chars) if random.random() < 0.1 else rain_chars[row % len(rain_chars)]
                        d.text((x, ry), ch_char, fill=(0, brightness, 0), font=font_rain)

            # Countdown text with glow
            bbox = font_main.getbbox(text)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cx_t = (width - tw) // 2
            cy_t = (height - th) // 2 - 80 - bbox[1]
            # Dark box behind text for readability
            margin = 30
            d.rectangle([cx_t - margin, cy_t + bbox[1] - margin,
                         cx_t + tw + margin, cy_t + bbox[1] + th + margin],
                        fill=(0, 10, 0))
            # Green glow
            heat = 1.0 - rem / dur
            green_val = int(180 + 75 * heat)
            d.text((cx_t, cy_t), text, fill=(0, green_val, 0), font=font_main)

            # Label
            lb = font_label.getbbox("BLOOM")
            d.text(((width - lb[2] + lb[0]) // 2, cy_t + th + bbox[1] + 20),
                   "BLOOM", fill=(0, 80, 0), font=font_label)

            if rem < 0.1:
                a = 1.0 - rem / 0.1
                frame = Image.blend(frame, Image.new('RGB', (width, height), (0,255,0)), a * 0.5)
            return frame

    # =================================================================
    # RENDER LOOP — pipe frames to ffmpeg
    # =================================================================
    cmd = [
        ffmpeg, '-y',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        '-s', f'{width}x{height}', '-r', str(fps),
        '-i', 'pipe:0',
        '-i', wav_path,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for fi in range(total_frames):
        frame = render_frame(fi)
        try:
            proc.stdin.write(frame.tobytes())
        except BrokenPipeError:
            break

    proc.stdin.close()
    _, stderr_data = proc.communicate()

    if proc.returncode != 0:
        err = stderr_data.decode('utf-8', errors='replace') if stderr_data else 'unknown'
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise RuntimeError(f"Countdown render failed: {err[-500:]}")

    try:
        os.remove(wav_path)
        os.rmdir(temp_dir)
    except OSError:
        pass

    print(f"Countdown rendered ({theme}): {output_path}")
    return output_path


def _create_glow_cta_image(text, font_size=36, glow_color=(255, 200, 0),
                           text_color=(255, 255, 255), glow_radius=8, padding=24):
    """Create text PNG with glowing aura effect."""
    import tempfile
    from PIL import Image, ImageDraw, ImageFilter

    font = _load_font(font_size)
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    extra = glow_radius * 3
    img_w = tw + padding * 2 + extra * 2
    img_h = th + padding * 2 + extra * 2

    # Glow layer: text in glow color, blurred
    glow = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx = (img_w - tw) // 2
    gy = (img_h - th) // 2 - bbox[1]
    gd.text((gx, gy), text, fill=glow_color + (220,), font=font)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=glow_radius))

    # Bright core glow (tighter, brighter)
    core = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    cd.text((gx, gy), text, fill=(255, 255, 200, 180), font=font)
    core = core.filter(ImageFilter.GaussianBlur(radius=glow_radius // 3))

    # Crisp text on top
    txt = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    td.text((gx, gy), text, fill=text_color + (255,), font=font)

    result = Image.alpha_composite(glow, core)
    result = Image.alpha_composite(result, txt)

    path = os.path.join(tempfile.gettempdir(), 'bloom_glow_cta.png')
    result.save(path)
    return path, img_w, img_h


# Always-visible glow text
_GLOW_TEXT = "Тебя ждёт бесплатный подарок"

# CTA markers shown at timeline milestones
_DEFAULT_CTA_MARKERS = [
    {
        "position": 0.25,
        "always": False,
        "segments": [
            {"text": "Бесплатный бот",       "color": (0, 230, 160),  "size": 52},
            {"text": "спасающий отношения",   "color": (255, 255, 255), "size": 44},
            {"text": "Ссылка в шапке профиля ↑", "color": (255, 215, 0), "size": 40},
        ],
    },
    {
        "position": 0.50,
        "always": False,
        "segments": [
            {"text": "Подпишись!",            "color": (255, 255, 255), "size": 48},
        ],
    },
]


def _create_cat_icon(size=64):
    """Create a small cat emoji PNG for progress bar indicator."""
    import tempfile
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    rendered = False
    for font_path in [r"C:\Windows\Fonts\seguiemj.ttf",
                      "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"]:
        try:
            font = ImageFont.truetype(font_path, int(size * 0.8))
            bbox = font.getbbox("\U0001F431")
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (size - tw) // 2
            y = (size - th) // 2 - bbox[1]
            draw.text((x, y), "\U0001F431", font=font, embedded_color=True)
            rendered = True
            break
        except Exception:
            continue

    if not rendered:
        # Fallback: simple white cat face
        cx, cy = size // 2, size // 2 + 2
        r = size // 3
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 200))
        ear = r // 2
        draw.polygon([(cx - r, cy - r + 2), (cx - ear, cy - r - ear), (cx, cy - r + 2)],
                     fill=(255, 255, 255, 200))
        draw.polygon([(cx, cy - r + 2), (cx + ear, cy - r - ear), (cx + r, cy - r + 2)],
                     fill=(255, 255, 255, 200))
        er = max(1, r // 4)
        draw.ellipse([cx - r // 2 - er, cy - er, cx - r // 2 + er, cy + er], fill=(0, 0, 0, 200))
        draw.ellipse([cx + r // 2 - er, cy - er, cx + r // 2 + er, cy + er], fill=(0, 0, 0, 200))

    path = os.path.join(tempfile.gettempdir(), 'bloom_cat_progress.png')
    img.save(path)
    return path


def post_process_video(
    video_path: str,
    output_path: str = None,
    music_path: str = None,
    music_volume: float = 0.12,
    progress_bar: bool = False,
    progress_bar_color: str = "FFFFFF",
    progress_bar_height: int = 4,
    cta_always: bool = True,
    gpu: str = None,
    threads: int = 0,
):
    """
    Apply post-processing: background music and/or progress bar.
    Re-encodes only when needed; copies video stream when only adding music.
    """
    ffmpeg = get_ffmpeg_path()

    # Get video duration via ffmpeg -i (works without ffprobe)
    result = subprocess.run(
        [ffmpeg, '-i', video_path],
        capture_output=True, text=True
    )
    duration = 0.0
    for line in result.stderr.split('\n'):
        if 'Duration:' in line:
            # Parse "Duration: HH:MM:SS.ms"
            import re as _re
            m = _re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', line)
            if m:
                h, mi, s, ms = m.groups()
                duration = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 100
                break
    if duration <= 0:
        raise RuntimeError(f"Could not detect video duration: {video_path}")

    if not output_path:
        output_path = video_path

    needs_reencode = progress_bar  # Progress bar requires video re-encode
    temp_output = video_path + '.postproc.mp4'

    # Generate icons and CTA images for progress bar
    cat_icon_path = None
    marker_icon_path = None
    glow_path = None
    glow_w = glow_h = 0
    cta_images = []  # list of (path, width, height)
    temp_files = []  # track all temp files for cleanup
    cta_markers = None

    if progress_bar:
        cat_icon_path = _create_cat_icon(size=64)
        temp_files.append(cat_icon_path)
        # CTA markers with styled text overlays
        cta_markers = _DEFAULT_CTA_MARKERS
        marker_icon_path = _create_marker_icon(size=72)
        temp_files.append(marker_icon_path)
        for m in cta_markers:
            segs = m.get("segments", m.get("text", ""))
            cta_path, cta_w, cta_h = _create_cta_image(segs)
            cta_images.append({"path": cta_path, "w": cta_w, "h": cta_h,
                               "always": m.get("always", False)})
            temp_files.append(cta_path)

    cmd = [ffmpeg, '-y']

    # Input 0: video
    cmd.extend(['-i', video_path])
    next_input = 1

    # Input (optional): music
    music_idx = None
    if music_path:
        cmd.extend(['-i', music_path])
        music_idx = next_input
        next_input += 1

    # Input (optional): cat icon
    cat_idx = None
    if cat_icon_path:
        cmd.extend(['-i', cat_icon_path])
        cat_idx = next_input
        next_input += 1

    # Input (optional): marker icons — one per CTA marker
    marker_indices = []
    if marker_icon_path and cta_markers:
        for _ in cta_markers:
            cmd.extend(['-i', marker_icon_path])
            marker_indices.append(next_input)
            next_input += 1

    # Input (optional): CTA text images
    cta_indices = []
    for cta in cta_images:
        cmd.extend(['-i', cta["path"]])
        cta_indices.append(next_input)
        next_input += 1

    # Build filter_complex
    fc_parts = []
    v_out = '0:v'
    a_out = '0:a'

    # Progress bar: track line + cat + markers + CTA text
    if progress_bar and cat_idx is not None:
        # Position: 75% from bottom = 25% from top of video
        track_h = 4
        cat_size = 64
        bar_y = int(1920 * 0.25)  # 480px from top
        track_y = bar_y + cat_size // 2 - track_h // 2
        cat_y = bar_y

        # Track line (bg + filled portion)
        fc_parts.append(
            f"[0:v]"
            f"drawbox=x=0:y={track_y}:w=iw:h={track_h}:color=FFFFFF@0.15:t=fill,"
            f"drawbox=x=0:y={track_y}:w='t/{duration:.3f}*iw':h={track_h}:color=FFFFFF@0.5:t=fill"
            f"[track]"
        )

        # Cat spinning + crawling along straight line
        last_v = 'track'
        cat_rot_size = 91  # ceil(64 * sqrt(2)) — room for rotation
        fc_parts.append(
            f"[{cat_idx}:v]format=rgba,"
            f"rotate=2*PI*t:fillcolor=black@0:ow={cat_rot_size}:oh={cat_rot_size}"
            f"[cat_spin]"
        )
        cat_center_y = bar_y + cat_size // 2
        cat_overlay_y = cat_center_y - cat_rot_size // 2
        fc_parts.append(
            f"[{last_v}][cat_spin]"
            f"overlay=x='t/{duration:.3f}*(W-overlay_w)':y={cat_overlay_y}:eof_action=repeat"
            f"[v_cat]"
        )
        last_v = 'v_cat'

        # Marker overlays: ❗ at each CTA position, bobbing up/down
        for i, (m_idx, marker) in enumerate(zip(marker_indices, cta_markers)):
            pos = marker["position"]
            # x: centered on the timeline position
            mx = f"{pos}*W-overlay_w/2"
            # y: above the track, bobbing with sin()
            marker_base_y = bar_y - 80  # above the cat (marker is 72px)
            my = f"{marker_base_y}+6*sin(5*t)"
            lbl = f'v_mk{i}'
            fc_parts.append(
                f"[{last_v}][{m_idx}:v]"
                f"overlay=x='{mx}':y='{my}':eof_action=repeat"
                f"[{lbl}]"
            )
            last_v = lbl

        # CTA text overlays — shown temporarily when cat reaches position
        # CTAs never overlap (different timestamps), so each gets same y area
        cta_area_y = bar_y - 80 - 16  # above markers area
        for i, (c_idx, cta, marker) in enumerate(
                zip(cta_indices, cta_images, cta_markers)):
            pos = marker["position"]
            cx = "(W-overlay_w)/2"
            cy = cta_area_y - 10 - cta["h"]  # right above markers
            lbl = f'v_ct{i}'
            t_start = duration * pos
            t_end = t_start + 4.0
            fc_parts.append(
                f"[{last_v}][{c_idx}:v]"
                f"overlay=x='{cx}':y={cy}"
                f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
                f":eof_action=repeat"
                f"[{lbl}]"
            )
            last_v = lbl

        v_out = f'[{last_v}]'

    # Audio: mix voice + music
    if music_path and music_idx is not None:
        fc_parts.append(
            f"[0:a]volume=1.0[voice];"
            f"[{music_idx}:a]volume={music_volume},aloop=loop=-1:size=2e+09[music];"
            f"[voice][music]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        a_out = '[aout]'

    if not fc_parts:
        for f in temp_files:
            if f and os.path.exists(f):
                os.unlink(f)
        return video_path  # Nothing to do

    cmd.extend(['-filter_complex', ';'.join(fc_parts)])
    cmd.extend(['-map', v_out, '-map', a_out])

    # Video codec
    if needs_reencode:
        if gpu == 'nvenc':
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', '23', '-b:v', '0'])
        elif gpu == 'amd':
            cmd.extend(['-c:v', 'h264_amf', '-quality', 'balanced'])
        elif gpu == 'intel':
            cmd.extend(['-c:v', 'h264_qsv', '-preset', 'medium', '-global_quality', '23'])
        else:
            cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '23'])
            if threads > 0:
                cmd.extend(['-threads', str(threads)])
        cmd.extend(['-pix_fmt', 'yuv420p'])
    elif not progress_bar:
        # No video re-encode needed (only audio filter)
        cmd.extend(['-c:v', 'copy'])

    # Audio codec
    cmd.extend(['-c:a', 'aac', '-b:a', '192k'])

    cmd.append(temp_output)

    print(f"Post-processing: music={bool(music_path)}, progress_bar={progress_bar}, cat={bool(cat_icon_path)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp files
    for f in temp_files:
        if f and os.path.exists(f):
            try:
                os.unlink(f)
            except OSError:
                pass

    if proc.returncode != 0:
        print(f"Post-process ffmpeg error: {proc.stderr[:500]}")
        raise RuntimeError(f"Post-processing failed: {proc.stderr[:500]}")

    # Replace original or move to output
    if os.path.exists(temp_output):
        if output_path == video_path:
            os.replace(temp_output, video_path)
        else:
            shutil.move(temp_output, output_path)
        print(f"Post-processed: {output_path}")
    else:
        raise RuntimeError("Post-processing produced no output file")

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
    hook_duration: float = 0,
    freeze_duration: float = 0,
    gpu: str = None
):
    """
    Concatenate hook + freeze + main video.
    Audio is delayed by hook+freeze duration so it starts with main content.
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

    # Second pass: add audio with delay for hook+freeze
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
        # Calculate audio delay (hook + freeze duration)
        audio_delay_ms = int((hook_duration + freeze_duration) * 1000)
        print(f"  Audio delay: {audio_delay_ms}ms")

        cmd = [
            ffmpeg, '-y',
            '-i', temp_concat,
            '-i', audio_path,
            '-map', '0:v',
            '-map', '1:a',
            '-c:a', 'aac', '-b:a', '192k',
            '-af', f'adelay={audio_delay_ms}|{audio_delay_ms}',  # delay audio
            *codec_params,
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
    freeze_duration: float = 3.0,
    hook_as_bg: bool = False,
    hook_intro: bool = False
):
    """Create video with styled subtitles and dynamic backgrounds."""

    # Load script
    print(f"Loading script: {script_path}")
    with open(script_path, 'r', encoding='utf-8') as f:
        script_text = f.read()

    # Parse styled text
    words, images = parse_styled_text(script_text)
    print(f"Parsed {len(words)} styled words")
    if images:
        print(f"Found {len(images)} image overlays")

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

    # Prepare images with timing
    if images:
        script_dir = os.path.dirname(os.path.abspath(script_path))
        images = prepare_images_for_pages(images, page_times, script_dir)
        print(f"\nPrepared {len(images)} images for rendering")

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

    # === HOOK INTRO MODE ===
    # Hook plays with original audio, then freeze frame with subtitles page 1, then backgrounds
    if hook_intro and hook_video and os.path.exists(hook_video) and threads > 1:
        print(f"\n=== HOOK INTRO MODE ===")
        temp_dir = tempfile.mkdtemp(prefix='hook_intro_')

        try:
            # Load hook video
            hook_clip = VideoFileClip(hook_video)
            hook_dur = hook_clip.duration
            print(f"Hook video: {hook_dur:.1f}s")

            # Get page 1 timing (subtitles for freeze frame)
            page1_start, page1_end = page_times[0] if page_times else (0, 5)
            page1_duration = page1_end - page1_start + 0.5  # Small buffer
            print(f"Page 1: {page1_start:.2f}s - {page1_end:.2f}s (duration: {page1_duration:.1f}s)")

            # Create darkened freeze frame from last hook frame
            print(f"\nCreating freeze frame...")
            last_frame = hook_clip.get_frame(hook_dur - 0.01)
            # Darken the frame
            darkened = (last_frame * (1 - darken)).astype(np.uint8)

            # Render subtitles for page 0 on freeze frame
            print(f"Rendering page 1 subtitles on freeze frame...")
            freeze_frames_dir = os.path.join(temp_dir, 'freeze_frames')
            os.makedirs(freeze_frames_dir, exist_ok=True)

            # Only use page 0 for freeze frame
            freeze_pages = [pages[0]]
            page1_frames = int(page1_duration * FPS)

            # Prepare darkened background image (resize to target resolution)
            bg_pil = Image.fromarray(darkened).convert('RGBA')
            bg_pil = bg_pil.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

            # Get images for page 0 (freeze frame)
            freeze_images = [img for img in images if img.page_idx == 0] if images else []

            # Render freeze frames with subtitles
            for frame_idx in range(page1_frames):
                t = frame_idx / FPS
                subtitle_frame = render_frame(t, freeze_pages, fonts, images=freeze_images)

                # Combine darkened background with subtitle
                sub_img = Image.fromarray(subtitle_frame)
                combined = Image.alpha_composite(bg_pil.copy(), sub_img)

                frame_path = os.path.join(freeze_frames_dir, f'frame_{frame_idx:06d}.png')
                combined.save(frame_path)

                if (frame_idx + 1) % 50 == 0 or frame_idx == page1_frames - 1:
                    print(f"  Freeze frames: {frame_idx + 1}/{page1_frames}")

            # Assemble freeze video with page 1 audio
            freeze_video_path = os.path.join(temp_dir, 'freeze_with_subs.mp4')
            page1_audio_path = os.path.join(temp_dir, 'page1_audio.mp3')

            # Extract page 1 audio (0 to page1_end)
            ffmpeg = get_ffmpeg_path()
            cmd = [
                ffmpeg, '-y',
                '-i', audio_path,
                '-ss', '0',
                '-t', str(page1_duration),
                '-c:a', 'libmp3lame', '-q:a', '2',
                page1_audio_path
            ]
            subprocess.run(cmd, capture_output=True)

            # Assemble freeze video
            assemble_video_ffmpeg(
                frames_dir=freeze_frames_dir,
                audio_path=page1_audio_path,
                output_path=freeze_video_path,
                fps=FPS,
                crf=23,
                threads=threads,
                gpu=gpu
            )

            # Now render main video (pages 2+) with backgrounds
            print(f"\nRendering main video (pages 2+)...")
            main_frames_dir = os.path.join(temp_dir, 'main_frames')
            os.makedirs(main_frames_dir, exist_ok=True)

            # Calculate timing - main video audio starts at page1_duration
            main_start_time = page1_duration
            main_duration = duration - main_start_time
            main_total_frames = int(main_duration * FPS)

            # Load backgrounds
            bg_videos = []
            if backgrounds_dir and os.path.exists(backgrounds_dir):
                catalog = load_background_catalog(backgrounds_dir)
                if catalog:
                    print(f"Loaded {len(catalog)} backgrounds")
                    for vid in catalog:
                        if os.path.exists(vid['path']):
                            bg_videos.append(vid['path'])

            # Create page times for main video (offset by main_start_time)
            # Skip page 0 since it's on freeze frame
            main_page_times = [(max(0, s - main_start_time), max(0, e - main_start_time))
                               for s, e in page_times[1:]]

            # Extract background frames for main video
            bg_frame_mapping = {}
            if bg_videos and main_page_times:
                bg_frame_mapping = extract_background_frames(
                    bg_videos, main_page_times, main_frames_dir, main_total_frames, FPS, darken, desaturate
                )

            default_bg_color = (15, 15, 20, 255)

            # Serialize only pages[1:] for main video (skip page 0 which is on freeze)
            main_pages = pages[1:]
            main_pages_data = serialize_pages(main_pages)

            # Get images for pages 1+ and serialize
            main_images = [img for img in images if img.page_idx > 0] if images else []
            main_images_data = serialize_images(main_images, main_frames_dir) if main_images else None

            # Prepare tasks for main video rendering
            tasks = []
            for frame_idx in range(main_total_frames):
                # Time in original audio timeline
                t = main_start_time + frame_idx / FPS
                frame_path = os.path.join(main_frames_dir, f'frame_{frame_idx:06d}.png')
                bg_info = bg_frame_mapping.get(frame_idx, default_bg_color)
                tasks.append((frame_idx, t, main_pages_data, FONT_PATH, frame_path, bg_info, main_images_data))

            # Render main frames in parallel
            completed = 0
            with ProcessPoolExecutor(max_workers=threads) as executor:
                futures = {executor.submit(render_frame_to_file, task): task[0] for task in tasks}
                for future in as_completed(futures):
                    completed += 1
                    if completed % 100 == 0 or completed == main_total_frames:
                        print(f"  Main frames: {completed}/{main_total_frames} ({100*completed/main_total_frames:.0f}%)")

            # Extract main audio (from page1_end to end)
            main_audio_path = os.path.join(temp_dir, 'main_audio.mp3')
            cmd = [
                ffmpeg, '-y',
                '-i', audio_path,
                '-ss', str(main_start_time),
                '-c:a', 'libmp3lame', '-q:a', '2',
                main_audio_path
            ]
            subprocess.run(cmd, capture_output=True)

            # Assemble main video
            main_video_path = os.path.join(temp_dir, 'main_with_subs.mp4')
            assemble_video_ffmpeg(
                frames_dir=main_frames_dir,
                audio_path=main_audio_path,
                output_path=main_video_path,
                fps=FPS,
                crf=23,
                threads=threads,
                gpu=gpu
            )

            # Final concatenation using moviepy for proper audio handling
            print(f"\nConcatenating final video with moviepy...")

            # Load all clips
            hook_for_concat = VideoFileClip(hook_video)
            # Resize hook to match our frame size
            hook_for_concat = hook_for_concat.resized((WIDTH, HEIGHT))

            freeze_for_concat = VideoFileClip(freeze_video_path)
            main_for_concat = VideoFileClip(main_video_path)

            print(f"  Hook: {hook_for_concat.duration:.1f}s (with original audio)")
            print(f"  Freeze: {freeze_for_concat.duration:.1f}s (with TTS page 1)")
            print(f"  Main: {main_for_concat.duration:.1f}s (with TTS rest)")

            # Concatenate all clips
            final = concatenate_videoclips([hook_for_concat, freeze_for_concat, main_for_concat])
            print(f"  Final: {final.duration:.1f}s")

            # Write final video
            final.write_videofile(
                output_path,
                fps=FPS,
                codec='libx264',
                audio_codec='aac',
                preset='fast',
                threads=threads if threads > 0 else None
            )

            # Cleanup
            hook_for_concat.close()
            freeze_for_concat.close()
            main_for_concat.close()
            final.close()

            print(f"\nDone! {output_path}")
            hook_clip.close()
            audio.close()
            return

        finally:
            # Cleanup
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # Parallel frame pre-rendering
    if threads > 1:
        print(f"\nPre-rendering {total_frames} frames with {threads} workers...")

        # Create temp directory for frames
        temp_dir = tempfile.mkdtemp(prefix='styled_frames_')

        try:
            # Serialize pages for multiprocessing
            pages_data = serialize_pages(pages)

            # Serialize images for multiprocessing
            images_data = serialize_images(images, temp_dir) if images else None

            # Load background videos for parallel rendering
            bg_videos = []

            # If hook_as_bg, prepare hook+freeze as first background
            hook_bg_path = None
            if hook_as_bg and hook_video and os.path.exists(hook_video):
                print(f"\nPreparing hook as first background...")
                # Create combined hook+freeze video
                hook_clip = VideoFileClip(hook_video)
                hook_orig_dur = hook_clip.duration
                use_hook_dur = hook_duration if hook_duration > 0 else hook_orig_dur
                use_hook_dur = min(use_hook_dur, hook_orig_dur)

                # Get first page duration to determine needed length
                first_page_end = page_times[0][1] if page_times else 5.0
                needed_duration = first_page_end + 0.5  # Small buffer

                print(f"  Hook video: {hook_orig_dur:.1f}s, using: {use_hook_dur:.1f}s")
                print(f"  First page ends at: {first_page_end:.1f}s")

                # If hook is shorter than needed, we'll need freeze
                if use_hook_dur < needed_duration:
                    freeze_needed = needed_duration - use_hook_dur
                    print(f"  Adding freeze frame: {freeze_needed:.1f}s")
                else:
                    freeze_needed = 0

                # Trim hook to duration
                if use_hook_dur < hook_orig_dur:
                    hook_clip = hook_clip.subclipped(0, use_hook_dur)

                # Create freeze frame if needed
                if freeze_needed > 0:
                    last_frame = hook_clip.get_frame(hook_clip.duration - 0.01)
                    freeze_clip = ImageClip(last_frame).with_duration(freeze_needed + freeze_duration)
                    # Concatenate hook + freeze
                    combined = concatenate_videoclips([hook_clip, freeze_clip])
                else:
                    combined = hook_clip

                # Save combined hook+freeze as first background
                hook_bg_path = os.path.join(temp_dir, 'hook_as_bg.mp4')
                combined.write_videofile(
                    hook_bg_path,
                    fps=FPS,
                    codec='libx264',
                    audio=False,
                    preset='ultrafast',
                    logger=None
                )
                combined.close()
                hook_clip.close()

                bg_videos.append(hook_bg_path)
                print(f"  Hook background ready: {combined.duration:.1f}s total")

            if backgrounds_dir and os.path.exists(backgrounds_dir):
                catalog = load_background_catalog(backgrounds_dir)
                if catalog:
                    print(f"\nLoaded {len(catalog)} backgrounds from catalog")
                    for vid in catalog:
                        if os.path.exists(vid['path']):
                            bg_videos.append(vid['path'])
                            print(f"  - {vid['filename']}")

            # Or use single background (if no hook_as_bg and no catalog)
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
                tasks.append((frame_idx, t, pages_data, FONT_PATH, frame_path, bg_info, images_data))

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

            # If hook video (prepend mode, not hook_as_bg), assemble main to temp, then concat
            if hook_video and os.path.exists(hook_video) and not hook_as_bg:
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
                    hook_duration=hook_duration if hook_duration > 0 else hook_total_dur - freeze_duration,
                    freeze_duration=freeze_duration,
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
                frame_cache[frame_key] = render_frame(t, pages, fonts, images=images)
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
    parser.add_argument("--hook-as-bg", action="store_true",
                        help="Use hook as first background (subtitles ON hook) instead of prepending")
    parser.add_argument("--hook-intro", action="store_true",
                        help="Hook plays with original audio, then freeze frame with subtitles page 1, then backgrounds")
    parser.add_argument("--music", dest="music_path", default=None,
                        help="Path to background music file (mixed at low volume under voiceover)")
    parser.add_argument("--music-volume", type=float, default=0.12,
                        help="Music volume relative to voice (default: 0.12 = 12%%)")
    parser.add_argument("--progress-bar", action="store_true",
                        help="Add thin progress bar at top of video")
    parser.add_argument("--cta-always", action="store_true", default=True,
                        help="Show bio CTA always (default). Use --no-cta-always to show at 25%%")
    parser.add_argument("--no-cta-always", dest="cta_always", action="store_false",
                        help="Show bio CTA only when cat reaches 25%%")
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
        freeze_duration=args.freeze_duration,
        hook_as_bg=args.hook_as_bg,
        hook_intro=args.hook_intro
    )

    # Post-processing: music + progress bar
    if args.music_path or args.progress_bar:
        post_process_video(
            video_path=args.output,
            music_path=args.music_path,
            music_volume=args.music_volume,
            progress_bar=args.progress_bar,
            cta_always=args.cta_always,
            gpu=args.gpu,
            threads=args.threads,
        )


if __name__ == "__main__":
    main()

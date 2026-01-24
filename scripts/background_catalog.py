#!/usr/bin/env python3
"""
Background Video Catalog Generator

Analyzes video files to create searchable metadata for background selection.
Extracts technical info, visual properties, and generates thumbnails.
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image
import cv2
from sklearn.cluster import KMeans

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
BACKGROUNDS_DIR = PROJECT_ROOT / "downloads" / "backgrounds"
THUMBNAILS_DIR = BACKGROUNDS_DIR / "thumbnails"


def get_video_info(video_path: str) -> dict:
    """Extract technical info using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None

    data = json.loads(result.stdout)

    # Find video stream
    video_stream = None
    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'video':
            video_stream = stream
            break

    if not video_stream:
        return None

    width = video_stream.get('width', 0)
    height = video_stream.get('height', 0)

    # Determine orientation
    if height > width:
        orientation = 'vertical'
    elif width > height:
        orientation = 'horizontal'
    else:
        orientation = 'square'

    # Parse frame rate
    fps_str = video_stream.get('r_frame_rate', '30/1')
    if '/' in fps_str:
        num, denom = fps_str.split('/')
        fps = int(num) / int(denom) if int(denom) != 0 else 30
    else:
        fps = float(fps_str)

    return {
        'duration': float(data['format'].get('duration', 0)),
        'resolution': [width, height],
        'fps': int(fps),
        'orientation': orientation,
        'codec': video_stream.get('codec_name', 'unknown'),
        'file_size_mb': round(int(data['format'].get('size', 0)) / (1024 * 1024), 2)
    }


def extract_frames(video_path: str, num_frames: int = 5) -> list:
    """Extract frames at regular intervals using OpenCV."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0

    frames = []
    # Calculate timestamps at regular intervals (avoiding first/last 0.5s)
    start_time = min(0.5, duration * 0.1)
    end_time = max(duration - 0.5, duration * 0.9)

    if num_frames == 1:
        timestamps = [duration / 2]
    else:
        timestamps = np.linspace(start_time, end_time, num_frames)

    for ts in timestamps:
        frame_num = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if ret:
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append({
                'timestamp': round(ts, 2),
                'frame': frame_rgb
            })

    cap.release()
    return frames


def analyze_colors(frame: np.ndarray, n_colors: int = 3) -> list:
    """Extract dominant colors using k-means clustering."""
    # Resize for faster processing
    small = cv2.resize(frame, (100, 100))
    pixels = small.reshape(-1, 3)

    # K-means clustering
    kmeans = KMeans(n_clusters=n_colors, n_init=10, random_state=42)
    kmeans.fit(pixels)

    # Get colors sorted by frequency
    colors = kmeans.cluster_centers_.astype(int)
    labels, counts = np.unique(kmeans.labels_, return_counts=True)
    sorted_idx = np.argsort(-counts)

    hex_colors = []
    for idx in sorted_idx:
        r, g, b = colors[idx]
        hex_colors.append('#{:02x}{:02x}{:02x}'.format(r, g, b))

    return hex_colors


def analyze_brightness(frame: np.ndarray) -> float:
    """Calculate average brightness (0-1 scale)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    return round(np.mean(gray) / 255.0, 2)


def analyze_contrast(frame: np.ndarray) -> float:
    """Calculate contrast based on luminance std deviation."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    contrast = np.std(gray) / 128.0
    return round(min(contrast, 1.0), 2)


def analyze_saturation(frame: np.ndarray) -> float:
    """Calculate average saturation (0-1 scale)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    saturation = np.mean(hsv[:, :, 1]) / 255.0
    return round(saturation, 2)


def analyze_motion(frames: list) -> str:
    """Estimate motion speed by comparing consecutive frames."""
    if len(frames) < 2:
        return 'unknown'

    motion_scores = []
    for i in range(len(frames) - 1):
        frame1 = frames[i]['frame']
        frame2 = frames[i + 1]['frame']

        # Convert to grayscale and resize for faster comparison
        gray1 = cv2.cvtColor(cv2.resize(frame1, (160, 90)), cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(cv2.resize(frame2, (160, 90)), cv2.COLOR_RGB2GRAY)

        # Calculate absolute difference
        diff = np.abs(gray1.astype(float) - gray2.astype(float))
        motion_score = np.mean(diff) / 255.0
        motion_scores.append(motion_score)

    avg_motion = np.mean(motion_scores)

    if avg_motion < 0.02:
        return 'static'
    elif avg_motion < 0.06:
        return 'slow'
    elif avg_motion < 0.15:
        return 'medium'
    else:
        return 'fast'


def infer_style(colors: list, brightness: float, saturation: float) -> list:
    """Infer visual style from color analysis."""
    styles = []

    # Analyze color palette
    avg_color = np.mean([
        [int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)]
        for c in colors
    ], axis=0)

    # Dark with purple/blue tones = lofi or cyberpunk
    if brightness < 0.35:
        if any(int(c[5:7], 16) > int(c[1:3], 16) for c in colors):  # More blue than red
            styles.append('lofi')
        if saturation > 0.5 and any(int(c[3:5], 16) < 100 for c in colors):
            styles.append('cyberpunk')

    # Warm, muted colors = vintage
    if saturation < 0.4 and avg_color[0] > avg_color[2]:  # Red > Blue
        styles.append('vintage')

    # High saturation, vibrant = neon
    if saturation > 0.6 and brightness > 0.3:
        styles.append('neon')

    # Low saturation, neutral = minimal
    if saturation < 0.25:
        styles.append('minimal')

    # Green tones = nature
    if avg_color[1] > max(avg_color[0], avg_color[2]):
        styles.append('nature')

    # Fallback
    if not styles:
        if brightness < 0.4:
            styles.append('cinematic')
        else:
            styles.append('abstract')

    return styles[:2]  # Return top 2 styles


def infer_mood(brightness: float, saturation: float, motion: str, colors: list) -> list:
    """Infer mood from visual properties."""
    moods = []

    # Brightness-based moods
    if brightness < 0.3:
        moods.append('dark')
        moods.append('mysterious')
    elif brightness < 0.5:
        moods.append('calm')
    else:
        moods.append('energetic')

    # Motion-based moods
    if motion == 'static' or motion == 'slow':
        if 'calm' not in moods:
            moods.append('calm')
        moods.append('cozy')
    elif motion == 'fast':
        if 'energetic' not in moods:
            moods.append('energetic')

    # Saturation-based moods
    if saturation < 0.3:
        moods.append('melancholic')
    elif saturation > 0.6:
        moods.append('vibrant')

    # Color-based moods
    for color in colors:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        # Warm colors (red/orange/yellow)
        if r > 180 and g < 150 and b < 150:
            if 'romantic' not in moods:
                moods.append('romantic')
        # Cool colors (blue/purple)
        if b > max(r, g) and brightness < 0.4:
            if 'sad' not in moods:
                moods.append('sad')

    return moods[:3]  # Return top 3 moods


def is_text_friendly(brightness: float, contrast: float, motion: str) -> bool:
    """Determine if video is suitable for text overlay."""
    # Good for text: not too bright/dark, decent contrast, not too fast
    brightness_ok = 0.15 < brightness < 0.7
    contrast_ok = contrast > 0.15
    motion_ok = motion in ['static', 'slow', 'medium']

    return bool(brightness_ok and contrast_ok and motion_ok)


def generate_thumbnail(video_path: str, output_path: str, timestamp: float = None) -> bool:
    """Generate thumbnail at specified timestamp."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if timestamp is None:
        # Use middle of video
        timestamp = (total_frames / fps) / 2

    frame_num = int(timestamp * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return False

    # Resize to thumbnail size (maintain aspect ratio, max 480px wide)
    height, width = frame.shape[:2]
    scale = 480 / width
    new_size = (480, int(height * scale))
    thumbnail = cv2.resize(frame, new_size)

    # Save as JPEG
    cv2.imwrite(output_path, thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return True


def analyze_video(video_path: str, generate_thumb: bool = True) -> dict:
    """Perform full analysis on a single video file."""
    video_path = str(video_path)
    filename = os.path.basename(video_path)

    print(f"  Analyzing: {filename}")

    # Get technical info
    print("    - Extracting technical info...")
    tech_info = get_video_info(video_path)
    if not tech_info:
        print(f"    ERROR: Could not read video info")
        return None

    # Extract frames
    print("    - Extracting frames...")
    frames = extract_frames(video_path, num_frames=5)
    if not frames:
        print(f"    ERROR: Could not extract frames")
        return None

    # Analyze first frame for primary color analysis
    primary_frame = frames[len(frames) // 2]['frame']  # Use middle frame

    # Color analysis
    print("    - Analyzing colors...")
    dominant_colors = analyze_colors(primary_frame)
    brightness = analyze_brightness(primary_frame)
    contrast = analyze_contrast(primary_frame)
    saturation = analyze_saturation(primary_frame)

    # Motion analysis
    print("    - Analyzing motion...")
    motion_speed = analyze_motion(frames)

    # Infer style and mood
    print("    - Inferring style and mood...")
    styles = infer_style(dominant_colors, brightness, saturation)
    moods = infer_mood(brightness, saturation, motion_speed, dominant_colors)
    text_friendly = is_text_friendly(brightness, contrast, motion_speed)

    # Generate thumbnail
    thumbnail_path = None
    if generate_thumb:
        print("    - Generating thumbnail...")
        THUMBNAILS_DIR.mkdir(exist_ok=True)
        thumb_filename = Path(filename).stem + '.jpg'
        thumb_path = THUMBNAILS_DIR / thumb_filename
        if generate_thumbnail(video_path, str(thumb_path), frames[2]['timestamp']):
            thumbnail_path = f"thumbnails/{thumb_filename}"

    return {
        'filename': filename,
        'path': video_path,
        'technical': tech_info,
        'visual': {
            'dominant_colors': dominant_colors,
            'brightness': brightness,
            'contrast': contrast,
            'saturation': saturation,
            'motion_speed': motion_speed
        },
        'tags': {
            'style': styles,
            'mood': moods,
            'text_friendly': text_friendly
        },
        'thumbnail': thumbnail_path,
        'analyzed_at': datetime.now().isoformat()
    }


def scan_backgrounds(backgrounds_dir: str = None) -> dict:
    """Scan all videos in backgrounds directory and create catalog."""
    if backgrounds_dir is None:
        backgrounds_dir = BACKGROUNDS_DIR
    else:
        backgrounds_dir = Path(backgrounds_dir)

    print(f"\nScanning: {backgrounds_dir}")

    # Find all MP4 files
    video_files = list(backgrounds_dir.glob("*.mp4"))
    print(f"Found {len(video_files)} video files\n")

    catalog = {
        'version': '1.0',
        'last_updated': datetime.now().isoformat(),
        'videos': []
    }

    for video_path in sorted(video_files):
        result = analyze_video(video_path)
        if result:
            catalog['videos'].append(result)
            print(f"    Done: {result['tags']['style']} / {result['tags']['mood']}\n")

    return catalog


def save_catalog(catalog: dict, output_path: str = None):
    """Save catalog to JSON file."""
    if output_path is None:
        output_path = BACKGROUNDS_DIR / 'catalog.json'

    with open(output_path, 'w') as f:
        json.dump(catalog, f, indent=2)

    print(f"\nCatalog saved to: {output_path}")
    print(f"Total videos cataloged: {len(catalog['videos'])}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Background Video Catalog Generator')
    parser.add_argument('command', nargs='?', default='scan',
                       choices=['scan', 'analyze', 'search'],
                       help='Command to run')
    parser.add_argument('path', nargs='?', help='Video path for analyze command')
    parser.add_argument('--mood', help='Filter by mood')
    parser.add_argument('--style', help='Filter by style')
    parser.add_argument('--brightness', help='Filter by brightness (dark/medium/bright)')
    parser.add_argument('-o', '--output', help='Output path for catalog')

    args = parser.parse_args()

    if args.command == 'scan':
        catalog = scan_backgrounds()
        save_catalog(catalog, args.output)

    elif args.command == 'analyze':
        if not args.path:
            print("Error: Please provide video path")
            sys.exit(1)
        result = analyze_video(args.path)
        if result:
            print(json.dumps(result, indent=2))

    elif args.command == 'search':
        catalog_path = BACKGROUNDS_DIR / 'catalog.json'
        if not catalog_path.exists():
            print("Error: No catalog found. Run 'scan' first.")
            sys.exit(1)

        with open(catalog_path) as f:
            catalog = json.load(f)

        results = []
        for video in catalog['videos']:
            match = True
            if args.mood and args.mood not in video['tags']['mood']:
                match = False
            if args.style and args.style not in video['tags']['style']:
                match = False
            if args.brightness:
                b = video['visual']['brightness']
                if args.brightness == 'dark' and b >= 0.35:
                    match = False
                elif args.brightness == 'medium' and (b < 0.35 or b > 0.65):
                    match = False
                elif args.brightness == 'bright' and b <= 0.65:
                    match = False

            if match:
                results.append(video)

        print(f"Found {len(results)} matching videos:")
        for v in results:
            print(f"  - {v['filename']}: {v['tags']['style']} / {v['tags']['mood']}")


if __name__ == '__main__':
    main()

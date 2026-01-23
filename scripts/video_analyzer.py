"""
Video Frame Extractor for Claude Analysis
Extracts frames from video for visual analysis
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path

# ffmpeg path from imageio_ffmpeg
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"  # fallback


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds"""
    cmd = [
        FFMPEG, "-i", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr

    import re
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", output)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return 0


def extract_frames(
    video_path: str,
    output_dir: str,
    interval: float = 3.0,
    max_frames: int = 0
) -> list[str]:
    """
    Extract frames from video

    Args:
        video_path: path to video
        output_dir: folder for frames
        interval: interval between frames in seconds
        max_frames: maximum number of frames (0 = no limit)

    Returns:
        list of paths to saved frames
    """
    video_path = os.path.abspath(video_path)
    output_dir = os.path.abspath(output_dir)

    if not os.path.exists(video_path):
        print(f"Error: video not found: {video_path}")
        return []

    os.makedirs(output_dir, exist_ok=True)

    # Get duration
    duration = get_video_duration(video_path)
    print(f"Video duration: {duration:.1f} sec ({duration/60:.1f} min)")

    # Adjust interval if too many frames
    if max_frames > 0:
        estimated_frames = duration / interval
        if estimated_frames > max_frames:
            interval = duration / max_frames
            print(f"Adjusting interval to {interval:.1f} sec (max {max_frames} frames)")

    # Extract frames
    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")

    cmd = [
        FFMPEG,
        "-i", video_path,
        "-vf", f"fps=1/{interval}",  # 1 frame every N seconds
        "-q:v", "2",  # quality (2 = high)
        "-y",  # overwrite
        output_pattern
    ]

    print(f"Extracting frames every {interval:.1f} sec...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}")
        return []

    # Collect file list
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    frame_paths = [str(f) for f in frames]

    print(f"Extracted {len(frame_paths)} frames to {output_dir}")

    # Create timecodes file
    timecodes_file = os.path.join(output_dir, "timecodes.txt")
    with open(timecodes_file, "w", encoding="utf-8") as f:
        f.write(f"Video: {video_path}\n")
        f.write(f"Duration: {duration:.1f} sec\n")
        f.write(f"Interval: {interval:.1f} sec\n")
        f.write(f"Frames: {len(frame_paths)}\n\n")
        for i, frame_path in enumerate(frame_paths):
            timestamp = i * interval
            mins = int(timestamp // 60)
            secs = timestamp % 60
            f.write(f"{Path(frame_path).name}: {mins:02d}:{secs:05.2f}\n")

    print(f"Timecodes saved to {timecodes_file}")

    return frame_paths


def main():
    parser = argparse.ArgumentParser(description="Extract video frames for analysis")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("-o", "--output", default="frames", help="Folder for frames (default: frames)")
    parser.add_argument("-i", "--interval", type=float, default=3.0, help="Interval between frames in seconds (default: 3)")
    parser.add_argument("-m", "--max-frames", type=int, default=0, help="Max frames (0 = no limit)")

    args = parser.parse_args()

    frames = extract_frames(
        args.video,
        args.output,
        interval=args.interval,
        max_frames=args.max_frames
    )

    if frames:
        print(f"\nDone! Ask Claude to analyze frames:")
        print(f"  'Analyze frames in {args.output}'")


if __name__ == "__main__":
    main()

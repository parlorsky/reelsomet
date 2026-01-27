"""
Bloom Video Production DAG.

Automated pipeline: ideas → scripts → TTS → timestamps → render → deliver.
Runs up to 3 video pipelines in parallel.

Usage:
    # As CLI
    python scripts/bloom_dag.py --count 5 --format story

    # As module (from bot)
    from bloom_dag import run_dag
    results = await run_dag(count=5, format="story", on_progress=callback)
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from llm_client import chat_json

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
OUTPUT_DIR = PROJECT_ROOT / "output"
DATA_DIR = PROJECT_ROOT / "data"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
CATALOG_FILE = PROJECT_ROOT / "input" / "scripts_catalog.json"
DRAFT_FILE = PROJECT_ROOT / "input" / "scripts_catalog_draft.json"
LOG_FILE = DATA_DIR / "dag_log.json"
BG_CATALOG = PROJECT_ROOT / "input" / "backgrounds" / "catalog.json"
BG_DIR = PROJECT_ROOT / "input" / "backgrounds"

MAX_PARALLEL = 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DagItem:
    id: int
    status: str = "pending"  # pending|idea|script|tts|timestamps|markup|rendering|done|failed
    title: str = ""
    format: str = "story"
    hook_type: Optional[str] = None
    idea: Optional[dict] = None
    script: Optional[dict] = None
    files: dict = field(default_factory=lambda: {
        "markup": None, "audio": None, "timestamps": None, "video": None, "bg_dir": None
    })
    instagram_caption: str = ""
    plain_text: str = ""
    error: Optional[str] = None
    timings: dict = field(default_factory=dict)


@dataclass
class DagRun:
    id: str = ""
    status: str = "pending"  # pending|running|completed|failed
    requested_count: int = 0
    format: str = "story"
    items: list = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


# ---------------------------------------------------------------------------
# ID management
# ---------------------------------------------------------------------------

def get_next_id() -> int:
    """Get next available script ID from catalogs."""
    max_id = 0
    for path in [CATALOG_FILE, DRAFT_FILE]:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("scripts", []) or data.get("drafts", []) or []
            for entry in entries:
                max_id = max(max_id, entry.get("id", 0))
    return max_id + 1


# ---------------------------------------------------------------------------
# DAG steps
# ---------------------------------------------------------------------------

async def step_generate_ideas(count: int, fmt: str) -> list:
    """Step 1: Generate video ideas via LLM."""
    prompt = (
        f"Сгенерируй {count} идей для видео Bloom.\n"
        f"Формат: {fmt}.\n"
        f"Разнообразие: разные хук-формулы, эмоции, герои, боли.\n"
        f"Верни JSON массив из {count} объектов."
    )
    ideas = await chat_json(prompt, scope="ideas", timeout=180)
    if isinstance(ideas, dict):
        ideas = [ideas]
    return ideas[:count]


async def step_generate_script(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 2: Generate full script from idea via LLM."""
    item.status = "script"
    item.timings["script_start"] = _now()
    if on_progress:
        await on_progress(item.id, "script", f"📝 Пишу сценарий: {item.title}")

    prompt = (
        f"Напиши сценарий по этой идее:\n"
        f"{json.dumps(item.idea, ensure_ascii=False, indent=2)}\n\n"
        f"Верни JSON с полями: format, title, hook_type, mood, tags, voice, "
        f"duration_target, source, image, script_text, plain_text, instagram_caption."
    )
    script = await chat_json(prompt, scope="scripts", timeout=180)
    item.script = script
    item.title = script.get("title", item.title)
    item.plain_text = script.get("plain_text", "")
    item.instagram_caption = script.get("instagram_caption", "")
    item.format = script.get("format", item.format)
    item.hook_type = script.get("hook_type", item.hook_type)
    item.timings["script_done"] = _now()


async def step_generate_tts(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 3: Generate TTS audio via kie_tts.py."""
    item.status = "tts"
    item.timings["tts_start"] = _now()
    if on_progress:
        await on_progress(item.id, "tts", f"🎙 Озвучиваю: {item.title}")

    audio_path = str(DOWNLOADS_DIR / f"bloom_{item.id}_audio.mp3")

    # Write plain text to temp file (handles long texts)
    txt_path = str(DOWNLOADS_DIR / f"bloom_{item.id}_tts_input.txt")
    Path(txt_path).write_text(item.plain_text, encoding="utf-8")

    cmd = [
        sys.executable, str(SCRIPTS_DIR / "kie_tts.py"),
        txt_path,
        "-v", item.script.get("voice", "Callum"),
        "-o", audio_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"TTS failed: {stderr.decode()}")

    item.files["audio"] = audio_path
    # Clean up temp file
    Path(txt_path).unlink(missing_ok=True)
    item.timings["tts_done"] = _now()


async def step_extract_timestamps(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 4: Extract word timestamps via Whisper."""
    item.status = "timestamps"
    item.timings["ts_start"] = _now()
    if on_progress:
        await on_progress(item.id, "timestamps", f"⏱ Таймстампы: {item.title}")

    ts_path = str(DOWNLOADS_DIR / f"bloom_{item.id}_timestamps.json")
    cmd = [
        sys.executable, str(SCRIPTS_DIR / "audio_to_word_timestamps.py"),
        item.files["audio"],
        "-o", ts_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Timestamps failed: {stderr.decode()}")

    item.files["timestamps"] = ts_path
    item.timings["ts_done"] = _now()


async def step_write_markup(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 5: Write markup file from script_text."""
    item.status = "markup"
    markup_path = str(DOWNLOADS_DIR / f"bloom_{item.id}_markup.txt")
    script_text = item.script.get("script_text", "")
    Path(markup_path).write_text(script_text, encoding="utf-8")
    item.files["markup"] = markup_path


async def step_select_backgrounds(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 5.5: Use LLM to select relevant backgrounds per page."""
    item.timings["bg_start"] = _now()
    if on_progress:
        await on_progress(item.id, "backgrounds", f"🎨 Подбираю фоны: {item.title}")

    # Read background catalog
    if not BG_CATALOG.exists():
        return  # No catalog — renderer will use default round-robin

    bg_catalog = json.loads(BG_CATALOG.read_text(encoding="utf-8"))
    videos = bg_catalog.get("videos", [])
    if not videos:
        return

    # Build compact catalog summary for LLM
    bg_summary = []
    for v in videos:
        bg_summary.append({
            "filename": v["filename"],
            "mood": v.get("semantic", {}).get("mood", []),
            "themes": v.get("semantic", {}).get("themes", []),
            "style": v.get("semantic", {}).get("style", ""),
            "keywords_ru": v.get("keywords_ru", []),
            "brightness": v.get("visual", {}).get("brightness", ""),
        })

    # Count pages in script
    script_text = item.script.get("script_text", "")
    pages = [p.strip() for p in script_text.split("---") if p.strip()]
    page_count = len(pages)

    # Build compact page descriptions
    page_descriptions = []
    for i, page in enumerate(pages):
        # Strip markup tags for cleaner description
        clean = page.replace("[/]", "")
        clean = re.sub(r"\[(?:c|s|img):[^\]]*\]", "", clean)
        clean = clean.replace("**", "").replace("*", "").replace("_", "")
        clean = clean.strip()[:100]
        page_descriptions.append(f"Page {i+1}: {clean}")

    prompt = (
        f"У меня {page_count} страниц видео-скрипта. Подбери для каждой страницы "
        f"наиболее подходящий фон из каталога.\n\n"
        f"Страницы:\n" + "\n".join(page_descriptions) + "\n\n"
        f"Каталог фонов:\n{json.dumps(bg_summary, ensure_ascii=False)}\n\n"
        f"Верни JSON массив из {page_count} строк — filename фона для каждой страницы по порядку.\n"
        f"Пример: [\"file1.mp4\", \"file2.mp4\", \"file1.mp4\"]\n"
        f"Выбирай фоны по настроению и теме страницы. Можно повторять."
    )

    try:
        bg_selection = await chat_json(prompt, scope="general", timeout=120)
        if isinstance(bg_selection, list) and len(bg_selection) >= page_count:
            # Create temp directory with symlinks/copies in the right order
            temp_bg_dir = Path(tempfile.mkdtemp(prefix="bloom_bg_"))

            for i, bg_file in enumerate(bg_selection[:page_count]):
                src = BG_DIR / bg_file
                if src.exists():
                    # Name files so they sort in order: 000_file.mp4, 001_file.mp4, ...
                    dst = temp_bg_dir / f"{i:03d}_{bg_file}"
                    shutil.copy2(str(src), str(dst))

            item.files["bg_dir"] = str(temp_bg_dir)
            item.timings["bg_done"] = _now()
            return
    except Exception as e:
        logger.warning(f"Background selection failed for #{item.id}, using default: {e}")

    item.timings["bg_done"] = _now()


async def step_render_video(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 6: Render video via styled_subtitles.py."""
    item.status = "rendering"
    item.timings["render_start"] = _now()
    if on_progress:
        await on_progress(item.id, "rendering", f"🎬 Рендерю: {item.title}")

    video_path = str(OUTPUT_DIR / f"bloom_{item.id}_final.mp4")

    # Use LLM-selected backgrounds if available, otherwise default catalog
    bg_dir = item.files.get("bg_dir") or str(BG_DIR)

    cmd = [
        sys.executable, str(SCRIPTS_DIR / "styled_subtitles.py"),
        item.files["markup"],
        item.files["audio"],
        item.files["timestamps"],
        "--bg-dir", bg_dir,
        "--threads", "20",
        "-o", video_path,
    ]

    # Book format: add hook
    if item.format == "book":
        hook_id = item.script.get("hook_id", "bloom_sad_girl")
        hook_path = PROJECT_ROOT / "input" / "hooks" / f"{hook_id}.mp4"
        if hook_path.exists():
            cmd.extend(["--hook", str(hook_path), "--hook-intro"])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Render failed: {stderr.decode()[-500:]}")

    item.files["video"] = video_path
    item.timings["render_done"] = _now()


async def step_log_result(item: DagItem, run: DagRun) -> None:
    """Step 7: Log result to JSON."""
    item.status = "done"
    item.timings["done_at"] = _now()

    # Update scripts catalog
    _update_catalog(item)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def process_item(
    item: DagItem,
    run: DagRun,
    sem: asyncio.Semaphore,
    on_progress: Optional[Callable] = None,
) -> None:
    """Process a single video item through the full pipeline."""
    async with sem:
        try:
            await step_generate_script(item, on_progress)
            await step_generate_tts(item, on_progress)
            await step_extract_timestamps(item, on_progress)
            await step_write_markup(item, on_progress)
            await step_select_backgrounds(item, on_progress)
            await step_render_video(item, on_progress)
            # Clean up temp bg directory
            if item.files.get("bg_dir") and Path(item.files["bg_dir"]).exists():
                shutil.rmtree(item.files["bg_dir"], ignore_errors=True)
                item.files["bg_dir"] = None
            await step_log_result(item, run)
            if on_progress:
                await on_progress(item.id, "done", f"✅ Готово: {item.title}")
        except Exception as e:
            item.status = "failed"
            item.error = str(e)
            item.timings["failed_at"] = _now()
            if on_progress:
                await on_progress(item.id, "failed", f"❌ Ошибка ({item.title}): {e}")


async def run_dag(
    count: int = 5,
    format: str = "story",
    on_progress: Optional[Callable] = None,
) -> DagRun:
    """Run the full DAG pipeline.

    Args:
        count: Number of videos to generate.
        format: Video format ("story", "book", "mix").
        on_progress: Async callback(item_id, step, message).

    Returns:
        DagRun with all items and results.
    """
    # Ensure directories exist
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    DOWNLOADS_DIR.mkdir(exist_ok=True)

    run = DagRun(
        id=f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        status="running",
        requested_count=count,
        format=format,
        started_at=_now(),
    )

    # Step 1: Generate ideas
    if on_progress:
        await on_progress(0, "ideas", f"💡 Генерирую {count} идей ({format})...")

    ideas = await step_generate_ideas(count, format)

    # Assign IDs and create items
    next_id = get_next_id()
    for i, idea in enumerate(ideas):
        item = DagItem(
            id=next_id + i,
            status="idea",
            title=idea.get("title", f"Video {next_id + i}"),
            format=idea.get("format", format),
            hook_type=idea.get("hook_type"),
            idea=idea,
        )
        item.timings["idea_at"] = _now()
        run.items.append(item)

    if on_progress:
        titles = ", ".join(item.title for item in run.items)
        await on_progress(0, "ideas_done", f"💡 Идеи готовы: {titles}")

    # Steps 2-7: Process items in parallel (max 3)
    sem = asyncio.Semaphore(MAX_PARALLEL)
    await asyncio.gather(*[
        process_item(item, run, sem, on_progress)
        for item in run.items
    ])

    # Finalize
    run.finished_at = _now()
    failed = sum(1 for item in run.items if item.status == "failed")
    run.status = "completed" if failed == 0 else ("failed" if failed == len(run.items) else "partial")

    # Save log
    _save_log(run)

    return run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _save_log(run: DagRun) -> None:
    """Append run to dag_log.json."""
    log_data = {"runs": []}
    if LOG_FILE.exists():
        try:
            log_data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    run_dict = {
        "id": run.id,
        "status": run.status,
        "format": run.format,
        "requested_count": run.requested_count,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "items": [],
    }
    for item in run.items:
        run_dict["items"].append({
            "id": item.id,
            "status": item.status,
            "title": item.title,
            "format": item.format,
            "hook_type": item.hook_type,
            "files": item.files,
            "instagram_caption": item.instagram_caption,
            "error": item.error,
            "timings": item.timings,
        })

    log_data["runs"].append(run_dict)
    LOG_FILE.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_catalog(item: DagItem) -> None:
    """Add completed item to scripts_catalog.json."""
    catalog = {"version": "1.0", "description": "Одобренные сценарии для производства", "paths": {}, "scripts": []}
    if CATALOG_FILE.exists():
        try:
            catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    entry = {
        "id": item.id,
        "format": item.format,
        "status": "produced",
        "title": item.title,
        "hook_type": item.hook_type,
        "voice": item.script.get("voice", "Callum") if item.script else "Callum",
        "mood": item.script.get("mood") if item.script else None,
        "tags": item.script.get("tags", []) if item.script else [],
        "audio_file": item.files.get("audio"),
        "timestamps_file": item.files.get("timestamps"),
        "output_file": item.files.get("video"),
        "plain_text": item.plain_text,
        "instagram_caption": item.instagram_caption,
        "produced_at": _now(),
    }

    # Book-specific
    if item.format == "book" and item.script:
        entry["source"] = item.script.get("source")
        entry["image"] = item.script.get("image")
        entry["hook_id"] = item.script.get("hook_id", "bloom_sad_girl")

    catalog.setdefault("scripts", []).append(entry)
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bloom Video Production DAG")
    parser.add_argument("--count", "-n", type=int, default=5, help="Number of videos to generate")
    parser.add_argument("--format", "-f", type=str, default="story", choices=["story", "book", "mix"],
                        help="Video format")
    args = parser.parse_args()

    async def cli_progress(item_id, step, message):
        print(f"  [{item_id}] {message}")

    print(f"Starting DAG: {args.count} videos, format={args.format}")
    run = await run_dag(count=args.count, format=args.format, on_progress=cli_progress)

    print(f"\nDAG {run.status}:")
    for item in run.items:
        status_icon = "✅" if item.status == "done" else "❌"
        print(f"  {status_icon} #{item.id} {item.title} → {item.files.get('video', 'N/A')}")
        if item.error:
            print(f"     Error: {item.error}")

    print(f"\nLog saved to: {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())

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
import random
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
HOOKS_CATALOG = PROJECT_ROOT / "input" / "hooks" / "catalog.json"
HOOKS_DIR = PROJECT_ROOT / "input" / "hooks"
MUSIC_DIR = PROJECT_ROOT / "downloads" / "music"

MAX_PARALLEL = 3
VALID_FORMATS = {"story", "book", "micro", "challenge", "contrast", "debate", "mix"}


def _load_hook_info(hook_id: str) -> Optional[dict]:
    """Load hook metadata from catalog by ID."""
    if not HOOKS_CATALOG.exists():
        return None
    try:
        data = json.loads(HOOKS_CATALOG.read_text(encoding="utf-8"))
        for hook in data.get("hooks", []):
            if hook["id"] == hook_id:
                return hook
    except Exception:
        pass
    return None


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
    tts_text: str = ""
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

def _get_existing_titles_and_topics() -> list:
    """Collect titles/topics from log and catalogs to avoid repetition."""
    existing = []
    # From dag_log
    if LOG_FILE.exists():
        try:
            log_data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            for run in log_data.get("runs", []):
                for item in run.get("items", []):
                    if item.get("title"):
                        existing.append(item["title"])
        except Exception:
            pass
    # From catalogs
    for path in [CATALOG_FILE, DRAFT_FILE]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries = data.get("scripts", []) or data.get("drafts", []) or []
                for entry in entries:
                    if entry.get("title"):
                        existing.append(entry["title"])
            except Exception:
                pass
    return existing


def _get_existing_sources() -> list:
    """Collect book/author sources already used to avoid repeating the same works."""
    sources = []
    # From catalog
    if CATALOG_FILE.exists():
        try:
            data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
            for entry in data.get("scripts", []):
                if entry.get("source"):
                    sources.append(entry["source"])
        except Exception:
            pass
    # From draft
    if DRAFT_FILE.exists():
        try:
            data = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
            for entry in data.get("drafts", data.get("scripts", [])):
                if entry.get("source"):
                    sources.append(entry["source"])
        except Exception:
            pass
    # From dag_log
    if LOG_FILE.exists():
        try:
            log_data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            for run in log_data.get("runs", []):
                for item in run.get("items", []):
                    if item.get("source"):
                        sources.append(item["source"])
        except Exception:
            pass
    return sources


async def step_generate_ideas(count: int, fmt: str, hook_id: Optional[str] = None, extra_context: Optional[str] = None) -> list:
    """Step 1: Generate video ideas via LLM."""
    existing = _get_existing_titles_and_topics()
    existing_sources = _get_existing_sources()

    avoid_block = ""
    if existing:
        avoid_list = "\n".join(f"- {t}" for t in existing[-30:])  # last 30
        avoid_block = (
            f"\n\nУЖЕ БЫЛИ СДЕЛАНЫ эти видео (НЕ ПОВТОРЯЙ их идеи, темы, углы):\n"
            f"{avoid_list}\n"
            f"Придумай НОВЫЕ, непохожие идеи.\n"
        )

    # Deduplicate sources
    unique_sources = list(dict.fromkeys(s for s in existing_sources if len(s) < 200))
    if unique_sources:
        sources_list = "\n".join(f"- {s}" for s in unique_sources[-30:])
        avoid_block += (
            f"\n\nУЖЕ ИСПОЛЬЗОВАННЫЕ произведения/авторы/книги (НЕ ПОВТОРЯЙ):\n"
            f"{sources_list}\n"
            f"Используй ДРУГИХ авторов и ДРУГИЕ книги/исследования.\n"
        )

    hook_block = ""
    if hook_id:
        hook_info = _load_hook_info(hook_id)
        if hook_info:
            hook_text = hook_info.get("hook_text", "")
            hook_mood = ", ".join(hook_info.get("mood", []))
            hook_suitable = ", ".join(hook_info.get("suitable_for", []))
            hook_block = (
                f"\n\nВСЕ видео должны использовать ОДИН КОНКРЕТНЫЙ хук-видео: {hook_id}\n"
                f"Текст хука: «{hook_text}»\n"
                f"Настроение хука: {hook_mood}\n"
                f"Подходит для тем: {hook_suitable}\n"
                f"Каждая идея должна ПОДХВАТЫВАТЬ смысл этого хука.\n"
                f"В поле hook_id укажи: \"{hook_id}\"\n"
            )

    # Format-specific constraints for idea generation
    fmt_constraints = {
        "micro": (
            "Формат: Micro (7-15 сек, 3-4 страницы МАКСИМУМ).\n"
            "Один факт/инсайт + эмоция. Максимальный вирусный потенциал.\n"
            "Хук = шокирующая цифра или вопрос. Payoff к 7-й секунде.\n"
            "CTA = share trigger ('отправь партнёру'). БЕЗ Bloom CTA.\n"
        ),
        "challenge": (
            "Формат: Challenge (15-20 сек, 5-6 страниц).\n"
            "Конкретное задание + 'попробуй сегодня'. Actionable, saveable.\n"
            "Хук = прямая команда или вопрос.\n"
            "Задание должно быть КОНКРЕТНЫМ и выполнимым сегодня вечером.\n"
            "CTA = 'попробуй сегодня вечером' / 'сохрани'.\n"
        ),
        "contrast": (
            "Формат: Contrast (15-25 сек, 5-7 страниц).\n"
            "До/После БЕЗ книги и авторитета. Чистая эмоциональная история.\n"
            "Начинается с РЕЗУЛЬТАТА ('после'), затем флешбэк к 'до'.\n"
            "БЕЗ книг, БЕЗ авторов, БЕЗ Bloom. Engagement-only.\n"
        ),
        "debate": (
            "Формат: Debate (15-25 сек, 5-7 страниц).\n"
            "Провокация + 'а ты как думаешь?' Генерирует комментарии.\n"
            "Поляризующий вопрос как хук. Две стороны представлены.\n"
            "Ответ НЕ дан — зритель решает сам.\n"
            "CTA = 'напиши в комменты'.\n"
        ),
        "story": (
            "Формат: Story (20-30 сек, 6-8 страниц).\n"
            "Сторителлинг. Начинается с КУЛЬМИНАЦИИ (не экспозиция).\n"
            "Open loop → боль → поворот → развязка + CTA.\n"
        ),
        "book": (
            "Формат: Book (20-30 сек, 6-8 страниц).\n"
            "Цитата из книги + хук-видео.\n"
            "Интро подхватывает смысл хука (НЕ имя автора!).\n"
            "Автор + книга + цитата + применение + CTA.\n"
        ),
        "mix": (
            "Формат: Микс — чередуй форматы: micro, challenge, contrast, debate, story, book.\n"
            "Каждая идея должна быть ДРУГОГО формата. Максимальное разнообразие.\n"
        ),
    }

    fmt_block = fmt_constraints.get(fmt, fmt_constraints["story"])

    prompt = (
        f"Сгенерируй {count} идей для видео Bloom (приложение для отношений).\n"
        f"{fmt_block}\n"
        f"КРИТИЧЕСКИ ВАЖНО — ХУК (первая фраза видео):\n"
        f"Хук должен ОСТАНОВИТЬ скролл за 1 секунду. Правила:\n"
        f"• Максимум 6-8 слов. Короче = лучше.\n"
        f"• От первого лица: «Я», «Мой», «Мы» — НЕ «Люди», «Многие».\n"
        f"• Конкретика: имена, числа, детали — НЕ абстракции.\n"
        f"• Открытая петля: зритель ДОЛЖЕН узнать что дальше.\n"
        f"• Эмоциональный триггер: боль, шок, зависть, страх, любопытство.\n\n"
        f"5 формул хуков (чередуй!):\n"
        f"1. ВЫЕБОНЫ (триггер статуса): «Мой парень делает мне сюрприз каждый день»\n"
        f"2. ВОЛШЕБНАЯ ТАБЛЕТКА (1 действие → результат): «Одна фраза спасла наш брак»\n"
        f"3. ЗАПРЕТНЫЙ ПЛОД (скрытая правда): «Психологи это скрывают, но 80% пар...»\n"
        f"4. КОНТРАСТ (до/после): «Год назад мы не разговаривали. Сейчас не можем замолчать»\n"
        f"5. СТРАХ/FOMO: «Если ты не делаешь это — твои отношения умирают»\n\n"
        f"ПЛОХИЕ хуки (НЕ ДЕЛАЙ ТАК):\n"
        f"• «Отношения — это важно» — скучно, абстрактно\n"
        f"• «Многие пары сталкиваются с проблемами» — банально\n"
        f"• «Как улучшить отношения» — звучит как лекция\n\n"
        f"Каждая идея: title, concept, hook_type (status_trigger/magic_pill/"
        f"forbidden_fruit/contrast/fomo), hook_text (ТОЧНЫЙ текст хука — 6-8 слов), mood, tags.\n"
        f"Разнообразие: разные формулы хуков, разные эмоции, разные боли.\n"
        f"Верни JSON массив из {count} объектов."
        f"{hook_block}"
        f"{avoid_block}"
    )

    if extra_context:
        prompt += (
            f"\n\nАНАЛИТИКА ЭФФЕКТИВНОСТИ (используй для вдохновения):\n"
            f"{extra_context}\n"
            f"Генерируй идеи, вдохновлённые успешными темами и форматами из аналитики.\n"
        )

    ideas = await chat_json(prompt, scope="ideas", timeout=180)
    if isinstance(ideas, dict):
        ideas = [ideas]
    return ideas[:count]


def _format_duration(fmt: str) -> str:
    """Return target duration string for a given format."""
    return {
        "micro": "7-15 секунд (max 15!)",
        "challenge": "15-20 секунд",
        "contrast": "15-25 секунд",
        "debate": "15-25 секунд",
        "story": "20-30 секунд",
        "book": "20-30 секунд",
    }.get(fmt, "20-30 секунд")


async def step_generate_script(item: DagItem, on_progress: Optional[Callable] = None, hook_id: Optional[str] = None, extra_context: Optional[str] = None) -> None:
    """Step 2: Generate full script from idea via LLM."""
    item.status = "script"
    item.timings["script_start"] = _now()
    if on_progress:
        await on_progress(item.id, "script", f"📝 Пишу сценарий: {item.title}")

    hook_context = ""
    if hook_id:
        hook_info = _load_hook_info(hook_id)
        if hook_info:
            hook_context = (
                f"\n\nВидео начнётся с хук-видео (id: {hook_id}).\n"
                f"Текст хука: «{hook_info.get('hook_text', '')}»\n"
                f"Intro (Page 1 скрипта) должен подхватывать смысл этого хука.\n"
                f"В поле hook_id укажи: \"{hook_id}\"\n"
            )

    fmt = item.format or "story"

    # Format-specific script structure instructions
    _fmt_instructions = {
        "micro": (
            "\n\nФОРМАТ: Micro (7-15 сек, 3-4 страницы МАКСИМУМ)\n"
            "Структура script_text:\n"
            "Page 1 (ХУК): МАКСИМУМ 5-8 слов! Шокирующая цифра или вопрос.\n"
            "Page 2-3: Один факт/инсайт + эмоциональный удар.\n"
            "Page 3-4 (CTA): Share trigger — 'отправь партнёру', 'сохрани'.\n"
            "ЗАПРЕТ: НЕ упоминай Bloom. Только engagement CTA.\n"
        ),
        "challenge": (
            "\n\nФОРМАТ: Challenge (15-20 сек, 5-6 страниц)\n"
            "Структура script_text:\n"
            "Page 1 (ХУК): Прямая команда или вопрос. 5-8 слов.\n"
            "Pages 2-3: Почему это важно. Боль/проблема.\n"
            "Pages 4-5: КОНКРЕТНОЕ задание — выполнимо сегодня вечером.\n"
            "Page 6 (CTA): 'Попробуй сегодня вечером' / 'Сохрани и попробуй'.\n"
        ),
        "contrast": (
            "\n\nФОРМАТ: Contrast (15-25 сек, 5-7 страниц)\n"
            "Структура script_text:\n"
            "Page 1 (ХУК): РЕЗУЛЬТАТ ('после'). 5-8 слов. Контраст.\n"
            "Pages 2-3: Флешбэк к 'до'. Боль, детали, имена.\n"
            "Pages 4-5: Поворотный момент. Что изменилось.\n"
            "Pages 6-7: Эмоциональная развязка + CTA (engagement-only).\n"
            "ЗАПРЕТ: БЕЗ книг, БЕЗ авторов, БЕЗ Bloom.\n"
        ),
        "debate": (
            "\n\nФОРМАТ: Debate (15-25 сек, 5-7 страниц)\n"
            "Структура script_text:\n"
            "Page 1 (ХУК): Поляризующий вопрос. 5-8 слов.\n"
            "Pages 2-3: Сторона 1 — аргумент ЗА.\n"
            "Pages 4-5: Сторона 2 — аргумент ПРОТИВ.\n"
            "Pages 6-7: НЕ давай ответ. 'А ты как думаешь?' + CTA 'напиши в комменты'.\n"
        ),
        "story": (
            "\n\nФОРМАТ: Story (20-30 сек, 6-8 страниц)\n"
            "Структура script_text:\n"
            "Page 1 (ХУК): МАКСИМУМ 5-8 слов! Короткая фраза, бьёт в лоб.\n"
            "  Пример: **Она** сказала *«уходи»* — и я **ушёл**\n"
            "  Пример: **Одна** привычка. Наш *брак* — **спасён.**\n"
            "Pages 2-3 (setup): Ситуация. Детали. Имена. 2-3 строки.\n"
            "Pages 4-6 (story): Эмоциональная история с поворотами.\n"
            "  Конкретные детали: диалоги в [c:lime]«кавычках»[/], имена, места.\n"
            "Pages 7-8 (CTA): Поворот + CTA (engagement или Bloom).\n"
        ),
        "book": (
            "\n\nФОРМАТ: Book (20-30 сек, 6-8 страниц + хук-видео)\n"
            "Структура script_text:\n"
            "Page 1 (intro): Подхватывает смысл хука. 1-2 строки.\n"
            "Page 2: [img:обложка.jpg] + автор + книга\n"
            "Page 3: Цитата [c:gold]«текст»[/]\n"
            "Pages 4-6: Развитие мысли, применение к ситуации\n"
            "Pages 7-8: Решение + CTA.\n"
        ),
    }

    fmt_instructions = _fmt_instructions.get(fmt, _fmt_instructions["story"])

    prompt = (
        f"Напиши сценарий по этой идее:\n"
        f"{json.dumps(item.idea, ensure_ascii=False, indent=2)}\n"
        f"{fmt_instructions}\n"
        f"УДЕРЖАНИЕ — ГЛАВНЫЙ ПРИОРИТЕТ:\n"
        f"• Page 1 = ХУК. Максимум 5-8 слов. Одна мысль. Шок, боль, интрига.\n"
        f"• Каждая страница заканчивается открытой петлёй — зритель ОБЯЗАН листать дальше.\n"
        f"• Никаких длинных предложений. Каждая строка — удар.\n"
        f"• Используй styled markup: **акцент**, *выделение*, _приглушённое_,\n"
        f"  [c:color]цвет[/], [img:file.jpg], --- (разделитель страниц).\n"
        f"• plain_text — тот же текст без markup (для TTS).\n"
        f"• Длительность: {_format_duration(fmt)}. НЕ растягивай!\n\n"
        f"Верни JSON с полями: format, title, hook_id, hook_type, mood, tags, voice, "
        f"duration_target, source, image, script_text, plain_text, instagram_caption."
        f"{hook_context}"
    )

    if extra_context:
        prompt += (
            f"\n\nАНАЛИТИКА ЭФФЕКТИВНОСТИ (учитывай при написании сценария):\n"
            f"{extra_context}\n"
            f"Ориентируйся на стиль и темы успешных скриптов из аналитики.\n"
        )

    script = await chat_json(prompt, scope="scripts", timeout=180)
    item.script = script
    item.title = script.get("title", item.title)
    item.plain_text = script.get("plain_text", "")
    item.instagram_caption = script.get("instagram_caption", "")
    item.format = script.get("format", item.format)
    item.hook_type = script.get("hook_type", item.hook_type)
    # If specific hook was selected, ensure hook_id is set in the script
    if hook_id:
        item.script["hook_id"] = hook_id
    item.timings["script_done"] = _now()


async def step_inject_tts_tags(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 2.5: Inject ElevenLabs v3 audio tags into plain text for expressive TTS."""
    if on_progress:
        await on_progress(item.id, "tts_tags", f"🎭 Добавляю эмоции: {item.title}")

    if not item.plain_text:
        return

    fmt = item.format or "story"
    mood = (item.script or {}).get("mood", "")
    hook_type = item.hook_type or ""

    prompt = (
        f"Добавь ElevenLabs v3 audio tags в текст для озвучки.\n\n"
        f"ТЕКСТ:\n{item.plain_text}\n\n"
        f"КОНТЕКСТ: формат={fmt}, настроение={mood}, тип хука={hook_type}\n\n"
        f"ПРАВИЛА:\n"
        f"1. НЕ МЕНЯЙ слова — только добавляй теги в квадратных скобках.\n"
        f"2. НЕ удаляй и НЕ переставляй слова.\n"
        f"3. Теги ставятся ПЕРЕД фразой, на которую влияют.\n"
        f"4. Используй РАЗНООБРАЗНЫЕ теги, не повторяй один и тот же.\n"
        f"5. Следуй эмоциональной арке текста.\n\n"
        f"ДОСТУПНЫЕ ТЕГИ:\n"
        f"Эмоции: [sad] [happy] [angry] [excited] [nervous] [sarcastic] [curious] [wistful]\n"
        f"Подача: [whispers] [shouts] [softly] [gently] [calm] [dramatic]\n"
        f"Реакции: [laughs] [sighs] [gasps] [sniffles] [breathes] [clears throat]\n"
        f"Темп: [pause] [hesitates] [rushed] [slows down] [deliberate]\n"
        f"Стиль: [dramatic tone] [matter-of-fact] [reflective] [serious tone]\n\n"
        f"ПАТТЕРН ДЛЯ ВИДЕО:\n"
        f"• Хук (начало): [dramatic] или [whispers] или [serious tone] — зависит от контекста\n"
        f"• Боль/проблема: [sad] [softly] [pause]\n"
        f"• Поворот: [pause] [excited] или [gasps]\n"
        f"• Развязка/CTA: [calm] [gently] или [happy]\n\n"
        f"Верни ТОЛЬКО текст с тегами, без объяснений, без кавычек, без markdown."
    )

    try:
        from llm_client import chat
        result = await chat(prompt, scope="general", timeout=90)
        result = result.strip()
        # Sanity check: result should contain at least one tag and roughly the same words
        if "[" in result and len(result) > len(item.plain_text) * 0.5:
            item.tts_text = result
            logger.info(f"TTS tags injected for #{item.id}: {len(result)} chars (was {len(item.plain_text)})")
        else:
            logger.warning(f"TTS tag injection returned suspicious result for #{item.id}, using plain text")
            item.tts_text = item.plain_text
    except Exception as e:
        logger.warning(f"TTS tag injection failed for #{item.id}, using plain text: {e}")
        item.tts_text = item.plain_text


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
        "-v", item.script.get("voice", "EiNlNiXeDU1pqqOPrYMO"),
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


AUDIO_SPEED = 1.1  # Final audio speed multiplier


async def step_speedup_audio(item: DagItem, on_progress: Optional[Callable] = None) -> None:
    """Step 3.5: Speed up TTS audio by AUDIO_SPEED factor."""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    src = item.files["audio"]
    dst = src.replace("_audio.mp3", "_audio_fast.mp3")

    cmd = [
        ffmpeg, "-y", "-i", src,
        "-filter:a", f"atempo={AUDIO_SPEED}",
        "-vn", dst,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Audio speedup failed for #{item.id}, using original: {stderr.decode()[-200:]}")
        return

    # Replace original with sped-up version
    Path(src).unlink(missing_ok=True)
    Path(dst).rename(src)
    logger.info(f"Audio #{item.id} sped up to {AUDIO_SPEED}x")


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
        "--speed", "1.0",  # audio already sped up, no additional speedup
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
            # Create temp directory with copies in the right order + catalog.json
            temp_bg_dir = Path(tempfile.mkdtemp(prefix="bloom_bg_"))
            catalog_videos = []

            for i, bg_file in enumerate(bg_selection[:page_count]):
                src = BG_DIR / bg_file
                if src.exists():
                    dst_name = f"{i:03d}_{bg_file}"
                    dst = temp_bg_dir / dst_name
                    shutil.copy2(str(src), str(dst))
                    # Find original catalog entry for metadata
                    orig = next((v for v in videos if v["filename"] == bg_file), {})
                    catalog_videos.append({
                        "filename": dst_name,
                        "path": str(dst),
                        "technical": orig.get("technical", {}),
                        "visual": orig.get("visual", {}),
                        "semantic": orig.get("semantic", {}),
                    })

            # Write catalog.json so styled_subtitles.py can find backgrounds
            catalog_data = {"version": "1.0", "videos": catalog_videos}
            (temp_bg_dir / "catalog.json").write_text(
                json.dumps(catalog_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            item.files["bg_dir"] = str(temp_bg_dir)
            item.timings["bg_done"] = _now()
            return
    except Exception as e:
        logger.warning(f"Background selection failed for #{item.id}, using default: {e}")

    item.timings["bg_done"] = _now()


async def step_render_video(item: DagItem, on_progress: Optional[Callable] = None,
                            cta_always: bool = True, countdown_path: Optional[str] = None) -> None:
    """Step 6: Render video via styled_subtitles.py. Optionally prepend countdown."""
    item.status = "rendering"
    item.timings["render_start"] = _now()
    if on_progress:
        await on_progress(item.id, "rendering", f"🎬 Рендерю: {item.title}")

    video_path = str(OUTPUT_DIR / f"bloom_{item.id}_final.mp4")
    # If countdown, render main content to temp file first
    main_path = video_path if not countdown_path else str(OUTPUT_DIR / f"bloom_{item.id}_main.mp4")

    # Use LLM-selected backgrounds if available, otherwise default catalog
    bg_dir = item.files.get("bg_dir") or str(BG_DIR)

    cmd = [
        sys.executable, str(SCRIPTS_DIR / "styled_subtitles.py"),
        item.files["markup"],
        item.files["audio"],
        item.files["timestamps"],
        "--bg-dir", bg_dir,
        "--threads", "20",
        "--progress-bar",
        "-o", main_path,
    ]

    # CTA display mode
    if not cta_always:
        cmd.append("--no-cta-always")

    # Add background music if available
    music_files = list(MUSIC_DIR.glob("*.mp3")) if MUSIC_DIR.exists() else []
    if music_files:
        music_file = random.choice(music_files)
        cmd.extend(["--music", str(music_file), "--music-volume", "0.12"])

    # Add hook if specified in script (from bank or LLM) — skip if countdown mode
    if not countdown_path:
        script_hook_id = item.script.get("hook_id") if item.script else None
        if script_hook_id:
            hook_path = HOOKS_DIR / f"{script_hook_id}.mp4"
            if hook_path.exists():
                cmd.extend(["--hook", str(hook_path), "--hook-intro"])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Render failed: {stderr.decode()[-500:]}")

    # Prepend countdown if requested
    if countdown_path and os.path.exists(countdown_path):
        if on_progress:
            await on_progress(item.id, "rendering", f"⏱ Добавляю таймер: {item.title}")
        await _prepend_countdown(countdown_path, main_path, video_path)
        try:
            os.remove(main_path)
        except OSError:
            pass

    item.files["video"] = video_path
    item.timings["render_done"] = _now()


async def _prepend_countdown(countdown_path: str, main_path: str, output_path: str) -> None:
    """Concatenate countdown video + main video using ffmpeg concat demuxer."""
    from styled_subtitles import get_ffmpeg_path
    ffmpeg = get_ffmpeg_path()

    concat_list = output_path + ".concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        f.write(f"file '{countdown_path.replace(os.sep, '/')}'\n")
        f.write(f"file '{main_path.replace(os.sep, '/')}'\n")

    # Always re-encode to avoid freeze at concat boundary
    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-r", "30",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Countdown concat failed: {stderr.decode()[-300:]}")

    try:
        os.remove(concat_list)
    except OSError:
        pass


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
    on_item_done: Optional[Callable] = None,
    hook_id: Optional[str] = None,
    cta_always: bool = True,
    countdown_path: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> None:
    """Process a single video item through the full pipeline."""
    async with sem:
        try:
            await step_generate_script(item, on_progress, hook_id=hook_id, extra_context=extra_context)
            await step_generate_tts(item, on_progress)
            await step_speedup_audio(item, on_progress)
            await step_extract_timestamps(item, on_progress)
            await step_write_markup(item, on_progress)
            await step_select_backgrounds(item, on_progress)
            await step_render_video(item, on_progress, cta_always=cta_always,
                                    countdown_path=countdown_path)
            # Clean up temp bg directory
            if item.files.get("bg_dir") and Path(item.files["bg_dir"]).exists():
                shutil.rmtree(item.files["bg_dir"], ignore_errors=True)
                item.files["bg_dir"] = None
            await step_log_result(item, run)
            if on_progress:
                await on_progress(item.id, "done", f"✅ Готово: {item.title}")
            # Deliver immediately
            if on_item_done:
                await on_item_done(item)
        except Exception as e:
            item.status = "failed"
            item.error = str(e)
            item.timings["failed_at"] = _now()
            if on_progress:
                await on_progress(item.id, "failed", f"❌ Ошибка ({item.title}): {e}")


async def run_dag(
    count: int = 5,
    format: str = "story",
    hook_id: Optional[str] = None,
    on_progress: Optional[Callable] = None,
    on_item_done: Optional[Callable] = None,
    cta_always: bool = True,
    extra_context: Optional[str] = None,
) -> DagRun:
    """Run the full DAG pipeline.

    Args:
        count: Number of videos to generate.
        format: Video format ("story", "book", "micro", "challenge", "contrast", "debate", "mix").
        hook_id: Specific hook ID from bank (None = auto-generate).
        on_progress: Async callback(item_id, step, message).
        on_item_done: Async callback(item) — called immediately when a video is ready.
        extra_context: Optional analytics/insights text to guide LLM generation.

    Returns:
        DagRun with all items and results.
    """
    if format not in VALID_FORMATS:
        raise ValueError(f"Unknown format '{format}'. Valid: {', '.join(sorted(VALID_FORMATS))}")

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

    # Pre-generate countdown video if requested (unique random style each time)
    countdown_path = None
    if hook_id == "countdown":
        if on_progress:
            await on_progress(0, "rendering", "⏱ Рендерю таймер 5→0...")
        from styled_subtitles import render_countdown_video
        countdown_path = str(OUTPUT_DIR / "bloom_countdown.mp4")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: render_countdown_video(duration=5.0, output_path=countdown_path, fps=30)
        )
        if on_progress:
            await on_progress(0, "rendering", "⏱ Таймер готов!")
        # Don't pass countdown as hook_id to LLM
        hook_id = None

    # Step 1: Generate ideas
    if on_progress:
        await on_progress(0, "ideas", f"💡 Генерирую {count} идей ({format})...")

    ideas = await step_generate_ideas(count, format, hook_id=hook_id, extra_context=extra_context)

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
        process_item(item, run, sem, on_progress, on_item_done,
                     hook_id=hook_id, cta_always=cta_always,
                     countdown_path=countdown_path,
                     extra_context=extra_context)
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
            "source": item.script.get("source") if item.script else None,
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
    parser.add_argument("--format", "-f", type=str, default="story",
                        choices=["story", "book", "micro", "challenge", "contrast", "debate", "mix"],
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

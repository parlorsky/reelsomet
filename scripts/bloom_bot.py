"""
Bloom Video Bot — Telegram bot for video production pipeline.

Start: python scripts/bloom_bot.py

Flow:
  /start → "Генерировать" button
  → Select format (Story / Book / Микс)
  → Select hook source (Авто / Из банка → pick hook)
  → Select quantity (1 / 3 / 5 / 10)
  → DAG runs → progress messages → video delivery
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).parent))
from bloom_dag import run_dag, DagRun

BOT_TOKEN = "8527890522:AAHQvyCAz_2Rns_mAFrZPmYVsNmHeVw-884"
HOOKS_CATALOG = Path(__file__).parent.parent / "input" / "hooks" / "catalog.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# Suppress noisy httpx polling logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Track active DAG runs per chat
active_runs: dict[int, bool] = {}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    logger.info(f"/start from chat_id={update.effective_chat.id} user={update.effective_user.username}")
    keyboard = ReplyKeyboardMarkup(
        [["🎬 Генерировать"], ["📊 Статус", "⚙️ Настройки"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "Привет! Я Bloom Video Bot.\n"
        "Нажми «Генерировать» чтобы создать видео.",
        reply_markup=keyboard,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show last DAG run status."""
    log_path = Path(__file__).parent.parent / "data" / "dag_log.json"
    if not log_path.exists():
        await update.message.reply_text("Нет завершённых запусков.")
        return

    data = json.loads(log_path.read_text(encoding="utf-8"))
    runs = data.get("runs", [])
    if not runs:
        await update.message.reply_text("Нет завершённых запусков.")
        return

    last = runs[-1]
    items_info = []
    for item in last.get("items", []):
        icon = "✅" if item["status"] == "done" else "❌"
        items_info.append(f"  {icon} #{item['id']} {item['title']}")

    text = (
        f"Последний запуск: {last['id']}\n"
        f"Статус: {last['status']}\n"
        f"Формат: {last['format']}\n"
        f"Видео: {last['requested_count']}\n"
        f"Начало: {last['started_at']}\n"
        f"Конец: {last.get('finished_at', '—')}\n\n"
        + "\n".join(items_info)
    )
    await update.message.reply_text(text)


async def handle_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Генерировать' button — show format selection."""
    chat_id = update.effective_chat.id
    if active_runs.get(chat_id):
        await update.message.reply_text("⏳ Генерация уже идёт. Подожди завершения.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Micro", callback_data="fmt:micro"),
            InlineKeyboardButton("🎯 Challenge", callback_data="fmt:challenge"),
        ],
        [
            InlineKeyboardButton("🔄 Contrast", callback_data="fmt:contrast"),
            InlineKeyboardButton("💬 Debate", callback_data="fmt:debate"),
        ],
        [
            InlineKeyboardButton("📖 Story", callback_data="fmt:story"),
            InlineKeyboardButton("📚 Book", callback_data="fmt:book"),
        ],
        [
            InlineKeyboardButton("🎲 Микс", callback_data="fmt:mix"),
        ],
    ])
    await update.message.reply_text("Выбери формат видео:", reply_markup=keyboard)


def _load_hooks_catalog() -> list:
    """Load hooks from catalog.json."""
    if HOOKS_CATALOG.exists():
        try:
            data = json.loads(HOOKS_CATALOG.read_text(encoding="utf-8"))
            return data.get("hooks", [])
        except Exception:
            pass
    return []


def _fmt_label(fmt: str) -> str:
    """Return human-readable format label."""
    return {
        "micro": "Micro", "challenge": "Challenge", "contrast": "Contrast",
        "debate": "Debate", "story": "Story", "book": "Book", "mix": "Микс",
    }.get(fmt, fmt)


async def handle_format_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle format selection — show hook source choice."""
    query = update.callback_query
    await query.answer()

    fmt = query.data.split(":")[1]  # "story", "book", "mix"
    context.user_data["format"] = fmt

    fmt_label = _fmt_label(fmt)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Авто (LLM)", callback_data="hook:auto"),
            InlineKeyboardButton("📂 Из банка", callback_data="hook:bank"),
        ],
        [
            InlineKeyboardButton("⏱ Таймер 5→0", callback_data="hook:countdown"),
        ]
    ])
    await query.edit_message_text(
        f"Формат: {fmt_label}\nХуки — генерировать или выбрать из банка?",
        reply_markup=keyboard,
    )


async def handle_hook_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle hook source selection."""
    query = update.callback_query
    await query.answer()

    source = query.data.split(":")[1]  # "auto" or "bank"
    fmt = context.user_data.get("format", "story")
    fmt_label = _fmt_label(fmt)

    if source == "countdown":
        # Countdown timer hook (5→0 with beeps)
        context.user_data["hook_id"] = "countdown"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1", callback_data="qty:1"),
                InlineKeyboardButton("3", callback_data="qty:3"),
                InlineKeyboardButton("5", callback_data="qty:5"),
                InlineKeyboardButton("10", callback_data="qty:10"),
            ]
        ])
        await query.edit_message_text(
            f"Формат: {fmt_label} | Хук: ⏱ Таймер 5→0\nСколько видео?",
            reply_markup=keyboard,
        )
    elif source == "auto":
        # No specific hook — proceed to quantity
        context.user_data["hook_id"] = None
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1", callback_data="qty:1"),
                InlineKeyboardButton("3", callback_data="qty:3"),
                InlineKeyboardButton("5", callback_data="qty:5"),
                InlineKeyboardButton("10", callback_data="qty:10"),
            ]
        ])
        await query.edit_message_text(
            f"Формат: {fmt_label} | Хуки: авто\nСколько видео?",
            reply_markup=keyboard,
        )
    else:
        # Show hook list from catalog
        hooks = _load_hooks_catalog()
        if not hooks:
            context.user_data["hook_id"] = None
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("1", callback_data="qty:1"),
                    InlineKeyboardButton("3", callback_data="qty:3"),
                    InlineKeyboardButton("5", callback_data="qty:5"),
                    InlineKeyboardButton("10", callback_data="qty:10"),
                ]
            ])
            await query.edit_message_text(
                f"Формат: {fmt_label}\n⚠️ Банк хуков пуст, используем авто.\nСколько видео?",
                reply_markup=keyboard,
            )
            return

        rows = []
        for hook in hooks:
            hook_id = hook["id"]
            hook_text = hook.get("hook_text", "")[:40]
            label = f"🎣 {hook_id}"
            rows.append([InlineKeyboardButton(label, callback_data=f"hookid:{hook_id}")])

        keyboard = InlineKeyboardMarkup(rows)
        await query.edit_message_text(
            f"Формат: {fmt_label}\nВыбери хук:",
            reply_markup=keyboard,
        )


async def handle_hook_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle specific hook selection from bank — show quantity."""
    query = update.callback_query
    await query.answer()

    hook_id = query.data.split(":", 1)[1]
    context.user_data["hook_id"] = hook_id

    fmt = context.user_data.get("format", "story")
    fmt_label = _fmt_label(fmt)

    # Find hook text for display
    hooks = _load_hooks_catalog()
    hook_text = ""
    for h in hooks:
        if h["id"] == hook_id:
            hook_text = h.get("hook_text", "")[:60]
            break

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="qty:1"),
            InlineKeyboardButton("3", callback_data="qty:3"),
            InlineKeyboardButton("5", callback_data="qty:5"),
            InlineKeyboardButton("10", callback_data="qty:10"),
        ]
    ])
    await query.edit_message_text(
        f"Формат: {fmt_label} | Хук: {hook_id}\n"
        f"«{hook_text}»\n"
        f"Сколько видео?",
        reply_markup=keyboard,
    )


async def handle_quantity_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quantity selection — start DAG."""
    query = update.callback_query
    await query.answer()

    count = int(query.data.split(":")[1])
    fmt = context.user_data.get("format", "story")
    hook_id = context.user_data.get("hook_id")  # None = auto
    chat_id = update.effective_chat.id

    fmt_label = _fmt_label(fmt)
    hook_label = f" | Хук: {hook_id}" if hook_id else " | Хуки: авто"
    await query.edit_message_text(
        f"🚀 Запускаю генерацию {count} видео ({fmt_label}{hook_label})..."
    )

    # Run DAG in background
    active_runs[chat_id] = True
    bot = context.bot

    total = count
    step_labels = {
        "ideas": "💡 Генерирую идеи",
        "ideas_done": "💡 Идеи готовы",
        "script": "📝 Сценарий",
        "tts": "🎙 Озвучка",
        "timestamps": "⏱ Таймстампы",
        "backgrounds": "🎨 Подбор фонов",
        "rendering": "🎬 Рендер",
        "done": "✅ Готово",
        "failed": "❌ Ошибка",
    }

    import time as _time
    _last_progress_ts = 0.0

    async def on_progress(item_id: int, step: str, message: str):
        """Send progress update to chat (throttled: max 1 msg per 3s)."""
        nonlocal _last_progress_ts
        now = _time.monotonic()
        # Always send done/failed, throttle the rest
        if step not in ("done", "failed", "ideas_done") and (now - _last_progress_ts) < 3.0:
            return
        _last_progress_ts = now
        try:
            label = step_labels.get(step, step)
            if item_id > 0:
                text = f"[{item_id}] {label}: {message.split(': ', 1)[-1] if ': ' in message else message}"
            else:
                text = message
            await asyncio.wait_for(
                bot.send_message(chat_id=chat_id, text=text),
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"Progress send skipped: {e}")

    done_count = 0

    async def on_item_done(item):
        """Send video immediately when ready."""
        nonlocal done_count
        if item.files.get("video"):
            video_path = Path(item.files["video"])
            if video_path.exists():
                try:
                    size_mb = video_path.stat().st_size / (1024 * 1024)
                    await bot.send_document(
                        chat_id=chat_id,
                        document=open(video_path, "rb"),
                        filename=video_path.name,
                        caption=f"🎬 #{item.id} {item.title} ({size_mb:.1f} MB)",
                    )
                    # Send full info: title, description, plain text
                    info_parts = [f"📌 #{item.id} {item.title}"]
                    if item.instagram_caption:
                        info_parts.append(f"\n📋 Описание для Instagram:\n{item.instagram_caption}")
                    if item.plain_text:
                        info_parts.append(f"\n📝 Транскрипция:\n{item.plain_text}")
                    info_parts.append(f"\n📁 {video_path.name}")
                    await bot.send_message(
                        chat_id=chat_id,
                        text="\n".join(info_parts),
                    )
                    done_count += 1
                except Exception as e:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ Не удалось отправить видео #{item.id}: {e}",
                    )

    try:
        cta_always = context.user_data.get("cta_always", True)
        run = await run_dag(count=count, format=fmt, hook_id=hook_id,
                            on_progress=on_progress, on_item_done=on_item_done,
                            cta_always=cta_always)

        # Summary
        failed = sum(1 for i in run.items if i.status == "failed")
        summary = f"🏁 Готово! {done_count}/{count} видео создано."
        if failed > 0:
            summary += f"\n❌ {failed} ошибок."
            for item in run.items:
                if item.error:
                    summary += f"\n  • #{item.id}: {item.error[:100]}"
        await bot.send_message(chat_id=chat_id, text=summary)

    except Exception as e:
        logger.exception("DAG run failed")
        await bot.send_message(
            chat_id=chat_id,
            text=f"💥 DAG упал: {str(e)[:300]}",
        )
    finally:
        active_runs[chat_id] = False


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route callback queries."""
    data = update.callback_query.data
    if data.startswith("fmt:"):
        await handle_format_choice(update, context)
    elif data.startswith("hook:"):
        await handle_hook_source(update, context)
    elif data.startswith("hookid:"):
        await handle_hook_pick(update, context)
    elif data.startswith("qty:"):
        await handle_quantity_choice(update, context)


async def handle_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle status button."""
    await cmd_status(update, context)


async def handle_settings_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show settings menu."""
    cta_always = context.user_data.get("cta_always", True)
    current = "Всегда" if cta_always else "На 25%"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Всегда" + (" ✅" if cta_always else ""),
                                 callback_data="set:cta_always:1"),
            InlineKeyboardButton("На 25%" + (" ✅" if not cta_always else ""),
                                 callback_data="set:cta_always:0"),
        ],
    ])
    await update.message.reply_text(
        f"⚙️ Настройки\n\n"
        f"📌 CTA «Бот в шапке профиля»: {current}\n"
        f"  • Всегда — надпись видна весь ролик\n"
        f"  • На 25% — появляется на 4 сек когда котик доходит",
        reply_markup=keyboard,
    )


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings toggle."""
    query = update.callback_query
    await query.answer()
    _, key, val = query.data.split(":")
    if key == "cta_always":
        context.user_data["cta_always"] = val == "1"
        label = "Всегда" if val == "1" else "На 25%"
        await query.edit_message_text(f"✅ CTA «Бот в шапке профиля» → {label}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))

    # Buttons
    app.add_handler(MessageHandler(
        filters.Regex(r"^🎬 Генерировать$"), handle_generate
    ))
    app.add_handler(MessageHandler(
        filters.Regex(r"^📊 Статус$"), handle_status_button
    ))
    app.add_handler(MessageHandler(
        filters.Regex(r"^⚙️ Настройки$"), handle_settings_button
    ))

    # Callbacks — settings first (more specific prefix)
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern=r"^set:"))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Bloom Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

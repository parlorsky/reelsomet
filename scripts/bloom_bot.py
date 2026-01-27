"""
Bloom Video Bot — Telegram bot for video production pipeline.

Start: python scripts/bloom_bot.py

Flow:
  /start → "Генерировать" button
  → Select format (Story / Book / Микс)
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Track active DAG runs per chat
active_runs: dict[int, bool] = {}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    keyboard = ReplyKeyboardMarkup(
        [["🎬 Генерировать"], ["📊 Статус"]],
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
            InlineKeyboardButton("📖 Story", callback_data="fmt:story"),
            InlineKeyboardButton("📚 Book", callback_data="fmt:book"),
            InlineKeyboardButton("🎲 Микс", callback_data="fmt:mix"),
        ]
    ])
    await update.message.reply_text("Выбери формат видео:", reply_markup=keyboard)


async def handle_format_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle format selection — show quantity."""
    query = update.callback_query
    await query.answer()

    fmt = query.data.split(":")[1]  # "story", "book", "mix"
    context.user_data["format"] = fmt

    fmt_label = {"story": "Story", "book": "Book", "mix": "Микс"}[fmt]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="qty:1"),
            InlineKeyboardButton("3", callback_data="qty:3"),
            InlineKeyboardButton("5", callback_data="qty:5"),
            InlineKeyboardButton("10", callback_data="qty:10"),
        ]
    ])
    await query.edit_message_text(
        f"Формат: {fmt_label}\nСколько видео?",
        reply_markup=keyboard,
    )


async def handle_quantity_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quantity selection — start DAG."""
    query = update.callback_query
    await query.answer()

    count = int(query.data.split(":")[1])
    fmt = context.user_data.get("format", "story")
    chat_id = update.effective_chat.id

    fmt_label = {"story": "Story", "book": "Book", "mix": "Микс"}[fmt]
    await query.edit_message_text(
        f"🚀 Запускаю генерацию {count} видео ({fmt_label})..."
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

    async def on_progress(item_id: int, step: str, message: str):
        """Send progress update to chat."""
        try:
            label = step_labels.get(step, step)
            if item_id > 0:
                # Find item index
                idx = item_id - (item_id % 100)  # approximate
                text = f"[{item_id}] {label}: {message.split(': ', 1)[-1] if ': ' in message else message}"
            else:
                text = message
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Failed to send progress: {e}")

    try:
        run = await run_dag(count=count, format=fmt, on_progress=on_progress)

        # Deliver videos as documents (full quality, no compression)
        done_count = 0
        for item in run.items:
            if item.status == "done" and item.files.get("video"):
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
                        if item.instagram_caption:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"📋 Описание для Instagram:\n\n"
                                    f"{item.instagram_caption}\n\n"
                                    f"📁 Файл: {video_path.name}"
                                ),
                            )
                        done_count += 1
                    except Exception as e:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ Не удалось отправить видео #{item.id}: {e}",
                        )

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
    elif data.startswith("qty:"):
        await handle_quantity_choice(update, context)


async def handle_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle status button."""
    await cmd_status(update, context)


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

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Bloom Bot started. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

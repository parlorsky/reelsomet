# CLAUDE.md

Instructions for Claude Code when working with this repository.

## Project Overview

Video content toolkit for Instagram Reels:
- Download reels via snapinsta.to
- Generate TTS voiceovers via KIE.ai (ElevenLabs V3)
- Create styled word-by-word animated subtitles
- Extract word timestamps via OpenAI Whisper

## File Organization

```
reelsomet/
├── scripts/           # All Python scripts
│   ├── styled_subtitles.py      # Main subtitle generator
│   ├── kie_tts.py               # TTS via KIE.ai
│   ├── audio_to_word_timestamps.py  # Whisper timestamps
│   ├── content_audit.py          # Pre-render content validator
│   ├── background_catalog.py    # Background video cataloger
│   ├── video_analyzer.py        # Frame extraction
│   ├── download_from_html.py    # Instagram downloader
│   ├── instagram_downloader.py  # Core downloader
│   ├── instagram_profile_scraper.py
│   ├── instagram_account_manager.py
│   └── rename_by_popularity.py
├── input/             # Input resources
│   ├── backgrounds/   # Background videos + catalog.json
│   │   └── catalog.json
│   ├── hooks/         # Hook videos + catalog.json
│   │   └── catalog.json
│   ├── images/        # Image overlays for [img:] tags
│   ├── scripts_catalog.json       # Одобренные сценарии (script_text внутри)
│   └── scripts_catalog_draft.json # Черновики и идеи
├── downloads/         # Промежуточные файлы
│   ├── fonts/         # Montserrat-Bold.ttf
│   ├── music/         # Background music
│   ├── *_audio.mp3    # TTS аудио
│   └── *_timestamps.json  # Whisper timestamps
├── output/            # Готовые видео
│   └── *_final.mp4
├── docs/              # Documentation
├── .env               # API keys (not in git)
├── CLAUDE.md          # This file
└── README.md          # Project readme
```

## Core Scripts

### styled_subtitles.py - Main Feature
Creates videos with animated word-by-word subtitles.

```bash
# Basic usage
python scripts/styled_subtitles.py script.txt audio.mp3 -o output.mp4

# Fast parallel rendering (recommended)
python scripts/styled_subtitles.py script.txt audio.mp3 --threads 30 -o output.mp4

# With GPU encoding (NVIDIA)
python scripts/styled_subtitles.py script.txt audio.mp3 --threads 30 --gpu nvenc -o output.mp4
```

**Performance options:**
- `--threads N` - parallel frame rendering (use CPU cores, e.g. 16-30)
- `--gpu nvenc` - NVIDIA GPU encoding
- `--gpu amd` - AMD GPU encoding
- `--gpu intel` - Intel QuickSync encoding

**Speed:** 60-sec video renders in ~30 seconds with `--threads 30`

**Hook video (intro):**
```bash
# With hook video at the start
python scripts/styled_subtitles.py script.txt audio.mp3 \
    --hook input/hooks/my_hook.mp4 \
    --hook-duration 3 \
    --freeze-duration 3 \
    --threads 30 -o output.mp4
```

Hook options:
- `--hook PATH` - path to hook video (plays first, original quality)
- `--hook-duration N` - seconds of hook to use (0=full video)
- `--freeze-duration N` - freeze last frame duration (default: 3s)

**Markup syntax:**
- `**word**` - accent (110px, white, glow)
- `*word*` - highlight (88px, yellow)
- `_word_` - muted (58px, gray)
- `[c:color]word[/]` - custom color
- `[img:filename.jpg]` - image overlay with pop_drift effect
- `---` - page break

**Colors:** white, gray, red, green, blue, yellow, orange, purple, pink, cyan, coral, lime, gold, rose

**Image overlays:**
Insert images with dynamic pop_drift effect (bounce-in + continuous zoom):
```
[img:book_cover.jpg]
[c:cyan]Автор[/] _в_ _книге_
*«Название»* пишет
```

Image features:
- Automatic rounded corners and drop shadow
- Pop-in animation (0.18s elastic bounce)
- Continuous slow zoom while visible (drift effect)
- Quick fade-out at page end
- Positioned above text (doesn't overlap subtitles)

Image locations (checked in order):
1. `input/images/filename.jpg`
2. Absolute path

### kie_tts.py - TTS Generation (ElevenLabs Turbo 2.5 via KIE.ai)
```bash
python scripts/kie_tts.py "Text" -o voice.mp3
python scripts/kie_tts.py "Text" -v Callum -o voice.mp3
python scripts/kie_tts.py "Text" -v EiNlNiXeDU1pqqOPrYMO -o voice.mp3  # voice ID
python scripts/kie_tts.py --voices  # list voices
```

**Default voice:** `EiNlNiXeDU1pqqOPrYMO` (используется всегда если не указан другой)

**Voice presets:** Callum, Rachel, Aria, Roger, Sarah, Laura, Charlie, George, River, Liam, Charlotte, Alice, Matilda, Will, Jessica, Eric, Chris, Brian, Daniel, Lily, Bill

**Can also pass raw ElevenLabs voice IDs** with `-v`

**Params:** `--stability 0.5` `--similarity 0.75` `--style 0` `--speed 1.0` `-l ru`

**Emotion tags:** `[whispers]` `[shouts]` `[sad]` `[happy]` `[sarcastic]` `[pause]` `[laughs]` `[sighs]`

### audio_to_word_timestamps.py - Whisper
```bash
python scripts/audio_to_word_timestamps.py audio.mp3 -o timestamps.json
```

### video_analyzer.py - Frame Extraction
```bash
python scripts/video_analyzer.py video.mp4 -o frames -i 2
```

### background_catalog.py - Background Management
Analyzes video backgrounds for automatic selection.

```bash
# Scan all backgrounds and create catalog
python scripts/background_catalog.py scan

# Analyze single video
python scripts/background_catalog.py analyze video.mp4

# Search by criteria
python scripts/background_catalog.py search --mood calm --style lofi
```

**Catalog location:** `input/backgrounds/catalog.json`

**Using backgrounds with styled_subtitles:**
```bash
# Use background directory with catalog
python scripts/styled_subtitles.py script.txt audio.mp3 --bg-dir input/backgrounds -o output.mp4

# Single background video
python scripts/styled_subtitles.py script.txt audio.mp3 --bg background.mp4 -o output.mp4

# Adjust background effects
--darken 0.65       # darken factor (default: 0.65)
--desaturate 0.25   # desaturate factor (default: 0.25)
```

**Catalog structure:**
- `technical`: duration, resolution, fps, codec
- `visual`: dominant_colors, brightness, contrast, saturation, motion_speed, text_friendly
- `semantic`: style, mood, elements, color_palette, time_of_day
- `timeline`: scene descriptions with timestamps

## Форматы видео Bloom

6 форматов. Жёсткий лимит: **max 8 страниц / 30 секунд** для всех.

### Format: Micro (7-15 сек, 3-4 стр)
Один факт/инсайт + эмоция. Максимальный вирусный потенциал.
- 3-4 страницы МАКСИМУМ
- Хук = шокирующая цифра или вопрос
- Payoff к 7-й секунде
- CTA = share trigger ("отправь партнёру")

### Format: Challenge (15-20 сек, 5-6 стр)
Конкретное задание + "попробуй сегодня". Actionable, saveable.
- Хук = прямая команда или вопрос
- Задание должно быть КОНКРЕТНЫМ и выполнимым сегодня вечером
- CTA = "попробуй сегодня вечером" / "сохрани"

### Format: Contrast (15-25 сек, 5-7 стр)
До/После БЕЗ книги и авторитета. Чистая эмоциональная история.
- Начинается с РЕЗУЛЬТАТА ("после")
- Затем флешбэк к "до"
- Без книг, без авторов, без Bloom (engagement-only)

### Format: Debate (15-25 сек, 5-7 стр)
Провокация + "а ты как думаешь?" Генерирует комментарии.
- Поляризующий вопрос как хук
- Две стороны представлены
- Ответ НЕ дан — зритель решает сам
- CTA = "напиши в комменты"

### Format: Book (20-30 сек, 6-8 стр)
Цитата из книги + хук-видео. **MAX 8 страниц.**
- Хук-видео из `input/hooks/`
- Интро подхватывает смысл хука (НЕ имя автора!)
- Автор + книга + цитата + применение + CTA
- `[img:book_cover.jpg]` — обложка обязательна

### Format: Story (20-30 сек, 6-8 стр)
Сторителлинг без хук-видео. **MAX 8 страниц.**
- Начинается с КУЛЬМИНАЦИИ (не экспозиция, не контекст)
- Open loop → боль → поворот → развязка + CTA

---

## Жёсткие правила контента

### Лимиты
| Правило | Лимит |
|---------|-------|
| Max страниц | **8** (Micro: 4) |
| Max длительность | **30 секунд** (Micro: 15 сек) |
| Мат | **АБСОЛЮТНЫЙ ЗАПРЕТ** |
| Упоминания Bloom | **Max 1** на скрипт (или 0) |
| Слово "Телеграм" | **НИКОГДА** (Instagram штрафует) |

### CTA: 80/20 правило

**80% видео — engagement CTA (без Bloom):**
Цель: DM shares, saves, comments — топ-сигналы алгоритма.
```
Отправь партнёру — проверь реакцию
Сохрани — пригодится вечером
А ты? Напиши в комменты
```

**20% видео — Bloom CTA (нативно, без "Телеграм"):**
```
Я нашла это в Bloom — бесплатно — ссылка ↑
```

**НИКОГДА:** "Телеграм", "скачай приложение", "ссылка в шапке профиля"

### Иерархия сигналов Instagram
```
DM Shares (3-5x вес) > Saves (1.7x) > Comments > Shares > Likes (1x)
```

### Правила хука (первые 3 секунды)
Page 1 ОБЯЗАН содержать один из приёмов:
- **Незаконченная мысль:** "Когда он сказал ЭТО — я..."
- **Шокирующая цифра:** "4 из 5 пар делают это неправильно"
- **Прямой вопрос:** "Твой партнёр делает это?"
- **Контраст:** "Вчера — чужие. Сегодня — он плачет"

**ЗАПРЕЩЕНО на Page 1:** экспозиция, имя автора, "привет сегодня расскажу", "представь ситуацию"

### Разнообразие тем (антиповтор)
**Забаненные темы** (если нет свежего угла):
- "Одиночество вдвоём", "Телефон убивает близость", "Языки любви", "Один жест в день"

**Обязательная ротация кластеров:**
Конфликты, Физическая близость, Деньги в паре, Родители партнёра, Дети и пара, Личные границы, Ревность и доверие, Юмор и быт, Самооценка, Кризисы отношений, Расставание, Первые отношения

**ЗАПРЕТ:** никакого мата и вульгарных выражений в скриптах (без исключений)

## Workflow: Scripts & Video Production

### Scripts Catalog Structure

Поле `format` определяет тип видео: `"micro"`, `"challenge"`, `"contrast"`, `"debate"`, `"book"` или `"story"`.

**scripts_catalog_draft.json** — черновики и идеи:
```json
// Format: Micro / Challenge / Contrast / Debate (короткие форматы)
{
  "id": 400,
  "format": "micro",          // micro | challenge | contrast | debate
  "status": "idea",           // idea → draft → ready
  "title": "Название",
  "hook_type": "shock",       // одна из 8 формул хука
  "concept": "Краткое описание идеи",
  "script_text": null,        // Полный текст с markup
  "duration_target": 15,      // micro: 15, challenge: 20, contrast/debate: 25
  "voice": "EiNlNiXeDU1pqqOPrYMO",
  "mood": "inspiring",
  "topic_cluster": "conflicts", // кластер темы для антиповтора
  "tags": ["тег1", "тег2"],
  "image": null
}

// Format: Book (с хук-видео)
{
  "id": 11,
  "format": "book",
  "status": "idea",
  "title": "Название",
  "hook_id": "bloom_sad_girl", // ID хука из input/hooks/catalog.json
  "source": "Автор — Книга",
  "image": "book_cover.jpg",  // Обложка книги в input/images/
  "concept": "Краткое описание идеи",
  "script_text": null,
  "duration_target": 25,      // max 30 сек
  "voice": "EiNlNiXeDU1pqqOPrYMO",
  "mood": "inspiring",
  "topic_cluster": "self_esteem",
  "tags": ["тег1", "тег2"]
}

// Format: Story (без хук-видео)
{
  "id": 16,
  "format": "story",
  "status": "idea",
  "title": "Название",
  "hook_type": "shock",
  "concept": "Краткое описание истории",
  "script_text": null,
  "duration_target": 25,      // max 30 сек
  "voice": "EiNlNiXeDU1pqqOPrYMO",
  "mood": "emotional",
  "topic_cluster": "jealousy",
  "tags": ["тег1", "тег2"],
  "image": null
}
```

**hook_type для Story (8 формул):**
- `shock` — шок/провокация: "97% пар делают это неправильно"
- `forbidden_knowledge` — запретное знание: "Психологи не говорят об этом, но..."
- `curiosity_gap` — интрига: "То, что я узнала, меня шокировало"
- `result_numbers` — результат с цифрами: "Как мы перестали ссориться за 2 недели"
- `fomo` — страх потери: "Каждый день без этого — шаг к расставанию"
- `contrast` — контраст до/после: "Вчера он приготовил завтрак. Полгода назад мы не разговаривали"
- `status_trigger` — триггер зависти: "Мой парень делает сюрприз каждый день"
- `confession` — признание/уязвимость: "Я чуть не разрушила наши отношения"

**scripts_catalog.json** — одобренные сценарии для производства:
```json
{
  "id": 11,
  "format": "book",           // или "story"
  "status": "approved",       // approved → produced → published
  "script_text": "...",       // Полный текст с styled markup
  "hook_id": "bloom_sad_girl", // Только для book
  "hook_type": null,           // Только для story
  "audio_file": "downloads/bloom_11_audio.mp3",
  "timestamps_file": "downloads/bloom_11_timestamps.json",
  "output_file": "output/bloom_11_final.mp4"
}
```

### Workflow

1. **Идея** → добавить в `scripts_catalog_draft.json` (status: idea, format: book/story)
2. **Написать сценарий** → заполнить `script_text` (status: draft)
3. **Одобрить** → перенести в `scripts_catalog.json` (status: approved)
4. **Производство:**
   ```bash
   # TTS (default voice: EiNlNiXeDU1pqqOPrYMO)
   python scripts/kie_tts.py "plain_text" -o downloads/bloom_XX_audio.mp3

   # Timestamps (auto 1.15x speedup)
   python scripts/audio_to_word_timestamps.py downloads/bloom_XX_audio.mp3

   # Рендер — Format: Book (с хук-видео)
   python scripts/styled_subtitles.py \
     downloads/bloom_XX_markup.txt \
     downloads/bloom_XX_audio.mp3 \
     downloads/bloom_XX_timestamps.json \
     --hook input/hooks/bloom_sad_girl.mp4 \
     --hook-intro \
     --bg-dir input/backgrounds/ \
     --threads 20 -o output/bloom_XX_final.mp4

   # Рендер — Format: Story (без хук-видео)
   python scripts/styled_subtitles.py \
     downloads/bloom_XX_markup.txt \
     downloads/bloom_XX_audio.mp3 \
     downloads/bloom_XX_timestamps.json \
     --bg-dir input/backgrounds/ \
     --threads 20 -o output/bloom_XX_final.mp4
   ```
5. **Публикация** → обновить status: published, добавить instagram_url

## Environment

`.env` in project root:
```
OPENAI_API_KEY=sk-...
KIE_API_KEY=...
```

## Key Paths

```
Font: downloads/fonts/Montserrat-Bold.ttf
FFmpeg: imageio_ffmpeg auto-detected
```

## Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

Core: moviepy, pillow, numpy, openai, aiohttp, playwright

## Bloom App — Content Context

**Bloom** — Telegram Mini App для отношений (bloombot.love)

### Что делает
Генерирует персонализированные романтические микро-жесты — небольшие идеи и задания для проявления заботы о партнёре. Пользователь свайпает карточки (как в Tinder), сохраняет понравившиеся, выполняет их и оставляет фидбек.

### Целевая аудитория
Люди в отношениях, которые хотят:
- Поддерживать романтику в паре
- Получать готовые идеи, а не придумывать самим
- Делать регулярные небольшие приятности партнёру

### Проблема
"Хочу сделать что-то приятное, но не знаю что" — классическая проблема в долгосрочных отношениях. Bloom снимает когнитивную нагрузку: вместо того чтобы думать, пользователь просто свайпает и выбирает из персонализированных предложений.

### Ключевые фичи
| Фича | Описание |
|------|----------|
| Свайп-лента | Карточки с идеями, свайп вверх = сохранить, вправо = пропустить |
| GPT-персонализация | Часть карточек генерируется AI под конкретную пару |
| Тиры качества | S/A/B карточки с бейджами ("Редкая находка", "Партнёр оценит") |
| Трекинг задач | Сохранённые карточки превращаются в задачи с выполнением и фидбеком |
| Подписка через Stars | Монетизация через Telegram Stars |

### УТП (уникальное торговое предложение)
- **Микро-жесты** — фокус на ежедневной заботе, а не на дорогих подарках
- **AI-персонализация** — карточки учитывают контекст пары (через онбординг)
- **Telegram Mini App** — не нужно ставить отдельное приложение
- **Геймификация** — свайпы, бейджи, тиры редкости создают вовлечение

### Тон контента для Bloom
- Про отношения, любовь, заботу, романтику
- Проблемы: рутина убивает чувства, "не знаю что подарить", забываем делать приятности
- Решение: маленькие ежедневные жесты важнее редких больших сюрпризов
- Цитаты: Фромм, Готтман (исследователь отношений), Чепмен (5 языков любви)

---

## ПАЙПЛАЙН: Создание пака видео по 1 запросу

**Триггер:** "Сделай N видео для Bloom" или "Создай пак видео"

При создании пака указать формат: `micro`, `challenge`, `contrast`, `debate`, `book`, `story` (или микс).

**Рекомендуемый микс для пака из 5 видео:**
- 2x Micro (максимальный охват)
- 1x Challenge (saves)
- 1x Contrast или Debate (comments/shares)
- 1x Book или Story (глубина)

### Шаг 0: Аудит контента (NEW)
```bash
python scripts/content_audit.py downloads/bloom_XX_markup.txt
```
Проверяет: длина, мат, дубли тем, CTA, Bloom mentions.

### Шаг 1: Написание сценариев
**Агент:** `reels-scriptwriter`

Каждый скрипт:
- MAX 8 страниц / 30 секунд (Micro: 4 стр / 15 сек)
- Хук на Page 1 (не экспозиция!)
- CTA: 80% engagement ("отправь партнёру"), 20% Bloom (без "Телеграм")
- Разные тематические кластеры (антиповтор)

**Выход:** N сценариев в `input/scripts_catalog_draft.json` со статусом `ready`

### Шаг 2: Подготовка картинок
**Book:** обязательно — найти обложку книги (WebSearch + скачать в `input/images/`)
**Остальные форматы:** опционально

### Шаг 3: TTS озвучка
```bash
python scripts/kie_tts.py "plain_text" -o downloads/bloom_XX_audio.mp3
```

### Шаг 4: Извлечение таймстампов
```bash
python scripts/audio_to_word_timestamps.py downloads/bloom_XX_audio.mp3
```

### Шаг 5: Создание markup файлов
Из `script_text` создать файлы `downloads/bloom_XX_markup.txt`

### Шаг 6: Аудит перед рендером
```bash
python scripts/content_audit.py downloads/bloom_XX_markup.txt
```

### Шаг 7: Рендер видео
```bash
# Format: Book (с хук-видео)
python scripts/styled_subtitles.py \
  downloads/bloom_XX_markup.txt \
  downloads/bloom_XX_audio.mp3 \
  downloads/bloom_XX_timestamps.json \
  --hook input/hooks/HOOK_ID.mp4 \
  --hook-intro \
  --bg-dir input/backgrounds/ \
  --threads 20 -o output/bloom_XX_final.mp4

# Все остальные форматы (без хук-видео)
python scripts/styled_subtitles.py \
  downloads/bloom_XX_markup.txt \
  downloads/bloom_XX_audio.mp3 \
  downloads/bloom_XX_timestamps.json \
  --bg-dir input/backgrounds/ \
  --threads 20 -o output/bloom_XX_final.mp4
```

### Шаг 8: Проверка качества
**Агент:** `video-qa-inspector` (автоматически после рендера)

---

## Быстрые команды для Claude

```
# Микс формат (рекомендуемый)
Сделай 5 видео Bloom микс:
1. 2x Micro + 1x Challenge + 1x Contrast + 1x Debate
2. Разные тематические кластеры (антиповтор!)
3. 80% engagement CTA, 20% Bloom CTA
4. Max 8 стр / 30 сек каждое
5. Аудит → TTS → таймстампы → рендер → проверка

# Один формат
Сделай 5 видео Bloom Micro
Сделай 3 видео Bloom Challenge
Сделай 5 видео Bloom Book
```

**Результат:** готовые видео в `output/bloom_XX_final.mp4`

---

## Используемые агенты

| Агент | Когда использовать |
|-------|-------------------|
| `reels-scriptwriter` | Написание сценариев с styled markup |
| `tts-tag-injector` | Добавление эмоциональных тегов для TTS |
| `background-video-cataloger` | Анализ и каталогизация новых backgrounds |
| `video-qa-inspector` | Проверка качества после рендера |
| `scripts-catalog-orchestrator` | Управление каталогом сценариев |

---

## Структура готового видео

### Micro / Challenge / Contrast / Debate (без хук-видео)

```
┌──────────────────────────────────────────┐
│  BACKGROUNDS (ротация по страницам)      │
│                                          │
│  3-8 страниц, 7-30 секунд               │
│  • TTS озвучка                           │
│  • Субтитры на всех страницах            │
│  • CTA: engagement (shares/saves)        │
└──────────────────────────────────────────┘
```

### Book (с хук-видео, max 30 сек основного контента)

```
┌──────────────────────────────────────────┐
│  HOOK (3-5 сек)                          │
│  • Оригинальное видео из input/hooks/    │
│  • ОРИГИНАЛЬНЫЙ ЗВУК хука                │
└──────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│  MAIN CONTENT (max 25 сек)               │
│  • 6-8 страниц                           │
│  • Картинка обложки книги                │
│  • Субтитры + TTS                        │
└──────────────────────────────────────────┘

Итого: max ~30 секунд
```

### Story (без хук-видео, max 30 сек)

```
┌──────────────────────────────────────────┐
│  BACKGROUNDS (ротация по страницам)      │
│                                          │
│  6-8 страниц, 20-30 секунд              │
│  • Хук-кульминация на Page 1             │
│  • TTS озвучка + субтитры                │
│  • [img:] опционально                    │
└──────────────────────────────────────────┘
```

---

## Checklist перед рендером

### Все форматы
- [ ] `python scripts/content_audit.py` — пройден без ошибок
- [ ] Max 8 страниц (Micro: 4)
- [ ] Нет мата
- [ ] Нет слова "Телеграм"
- [ ] Bloom упоминается max 1 раз
- [ ] CTA содержит share/save trigger
- [ ] Тема не повторяет предыдущие 20 скриптов
- [ ] Backgrounds в `input/backgrounds/catalog.json`
- [ ] TTS аудио в `downloads/`
- [ ] Timestamps JSON в `downloads/`

### Дополнительно для Book
- [ ] Хук существует в `input/hooks/`
- [ ] Картинка обложки в `input/images/`
- [ ] Markup файл с [img:] тегом

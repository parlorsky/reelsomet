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

### kie_tts.py - TTS Generation
```bash
python scripts/kie_tts.py "Text" -v Callum -o voice.mp3
python scripts/kie_tts.py --voices  # list voices
```

**Voices:** Adam, Alice, Bill, Brian, Callum, Charlie, Chris, Daniel, Eric, George, Harry, Jessica, Laura, Liam, Lily, Matilda, River, Roger, Sarah, Will

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

## Формула видео Bloom

```
┌─────────────────────────────────────────────────────────────┐
│  1. HOOK VIDEO (3-5 сек)                                    │
│     Готовое видео из input/hooks/                           │
│     Содержит hook_text — цепляющую фразу                    │
│     Пример: "она 10/10, но в детстве к ней никто..."        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  2. INTRO (связка с хуком)                                  │
│     Формула: _«До_ _пизды_ _что_ {тема хука}                │
│              **Давайте** лучше **разберёмся»**              │
│                                                             │
│     Intro должен подхватывать смысл hook_text               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  3. ОСНОВНОЙ СЮЖЕТ                                          │
│                                                             │
│     a) Автор + книга (с картинкой обложки):                 │
│        [img:book_cover.jpg]                                 │
│        [c:cyan]Автор[/] в книге                             │
│        *«Название»* пишет:                                  │
│                                                             │
│     b) Цитата (золотой цвет):                               │
│        [c:gold]«Текст цитаты»[/]                            │
│                                                             │
│     c) Развитие мысли:                                      │
│        Применение к ситуации из хука                        │
│        Проблема → последствия                               │
│                                                             │
│     d) Решение:                                             │
│        Что делать? → микро-жесты                            │
│        Примеры фраз [c:lime]«Я тебя вижу»[/]                │
│                                                             │
│     e) CTA (Bloom):                                         │
│        В [c:green]Bloom[/] мы собрали...                    │
│        [c:cyan]Ссылка[/] в шапке профиля                    │
└─────────────────────────────────────────────────────────────┘
```

**Обязательно:**
- Найти и скачать картинку (обложку книги) в `input/images/`
- Проверить картинку визуально перед использованием
- hook_id в сценарии должен соответствовать id из `input/hooks/catalog.json`

## Workflow: Scripts & Video Production

### Scripts Catalog Structure

**scripts_catalog_draft.json** — черновики и идеи:
```json
{
  "id": 11,
  "status": "idea",           // idea → draft → ready
  "title": "Название",
  "hook_id": "bloom_sad_girl", // ID хука из input/hooks/catalog.json
  "concept": "Краткое описание идеи",
  "script_text": null,        // Полный текст с markup (заполняется при status=draft)
  "duration_target": 50,
  "voice": "Callum",
  "mood": "inspiring",
  "tags": ["тег1", "тег2"],
  "source": "Автор цитаты"
}
```

**scripts_catalog.json** — одобренные сценарии для производства:
```json
{
  "id": 11,
  "status": "approved",       // approved → produced → published
  "script_text": "...",       // Полный текст с styled markup
  "hook_id": "bloom_sad_girl",
  "audio_file": "downloads/bloom_11_audio.mp3",
  "timestamps_file": "downloads/bloom_11_timestamps.json",
  "output_file": "output/bloom_11_final.mp4"
}
```

### Workflow

1. **Идея** → добавить в `scripts_catalog_draft.json` (status: idea)
2. **Написать сценарий** → заполнить `script_text` (status: draft)
3. **Одобрить** → перенести в `scripts_catalog.json` (status: approved)
4. **Производство:**
   ```bash
   # TTS
   python scripts/kie_tts.py "script_text" -v Callum -o downloads/bloom_11_audio.mp3

   # Timestamps (auto 1.15x speedup)
   python scripts/audio_to_word_timestamps.py downloads/bloom_11_audio.mp3

   # Video
   python scripts/styled_subtitles.py input/scripts_catalog.json --id 11 --threads 30
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

## 🚀 ПАЙПЛАЙН: Создание пака видео по 1 запросу

**Триггер:** "Сделай N видео для Bloom" или "Создай пак видео"

### Шаг 1: Написание сценариев
**Агент:** `reels-scriptwriter`

Для каждого видео создаётся сценарий по формуле:
1. Интро (связка с хуком)
2. Автор + книга + картинка обложки
3. Цитата
4. Развитие мысли
5. Решение (микро-жесты)
6. CTA Bloom

**Выход:** N сценариев в `input/scripts_catalog_draft.json` со статусом `ready`

### Шаг 2: Подготовка картинок
Для каждого сценария:
1. Найти обложку книги в интернете (WebSearch + WebFetch)
2. Скачать в `input/images/`
3. Проверить визуально (Read image file)

### Шаг 3: TTS озвучка
**Агент:** `tts-tag-injector` (опционально, для добавления эмоций)

```bash
# Для каждого видео
python scripts/kie_tts.py "script_text без markup" -v Callum -o downloads/bloom_XX_audio.mp3
```

### Шаг 4: Извлечение таймстампов
```bash
# Для каждого видео (авто-ускорение 1.15x перед Whisper)
python scripts/audio_to_word_timestamps.py downloads/bloom_XX_audio.mp3
# Выход: downloads/bloom_XX_timestamps.json
```

### Шаг 5: Создание markup файлов
Из `script_text` в draft.json создать файлы `downloads/bloom_XX_markup.txt`

### Шаг 6: Рендер видео
```bash
# Для каждого видео
python scripts/styled_subtitles.py \
  downloads/bloom_XX_markup.txt \
  downloads/bloom_XX_audio.mp3 \
  downloads/bloom_XX_timestamps.json \
  --hook input/hooks/bloom_sad_girl.mp4 \
  --hook-intro \
  --bg-dir input/backgrounds/ \
  --threads 20 \
  -o output/bloom_XX_final.mp4
```

**Флаги:**
- `--hook-intro` — хук с оригинальным аудио → freeze frame с интро → main с backgrounds
- `--bg-dir` — использовать backgrounds из каталога (round-robin по страницам)

### Шаг 7: Проверка качества
**Агент:** `video-qa-inspector` (автоматически после рендера)

---

## Быстрая команда для Claude

```
Сделай 5 видео Bloom:
1. Напиши 5 сценариев (разные книги/авторы про отношения)
2. Скачай обложки книг
3. Сгенерируй TTS (Callum)
4. Извлеки таймстампы
5. Отрендери все видео с хуком bloom_sad_girl
6. Проверь качество
```

**Результат:** 5 готовых видео в `output/bloom_XX_final.mp4`

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

```
┌──────────────────────────────────────────┐
│  HOOK (5 сек)                            │
│  • Оригинальное видео из input/hooks/    │
│  • ОРИГИНАЛЬНЫЙ ЗВУК хука                │
└──────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│  FREEZE FRAME (~6 сек)                   │
│  • Затемнённый последний кадр хука       │
│  • Субтитры Page 1 (интро)               │
│  • TTS озвучка интро                     │
└──────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│  MAIN CONTENT (~40 сек)                  │
│  • Backgrounds из каталога (смена по стр)│
│  • Картинка обложки книги (pop_drift)    │
│  • Субтитры Pages 2+                     │
│  • TTS озвучка остального текста         │
└──────────────────────────────────────────┘

Итого: ~50-55 секунд
```

---

## Checklist перед рендером

- [ ] Хук существует в `input/hooks/`
- [ ] Картинка обложки в `input/images/`
- [ ] Backgrounds в `input/backgrounds/catalog.json` с правильными путями
- [ ] TTS аудио в `downloads/`
- [ ] Timestamps JSON в `downloads/`
- [ ] Markup файл с правильным интро и [img:] тегом

# TODO: Производство 5 видео Bloom

## Проблемы текущих видео
- [ ] Нет background видео (чёрный фон после хука)
- [ ] Хук без оригинального аудио (должен быть со звуком)
- [ ] Интро "До пизды..." не появляется на freeze frame хука
- [ ] Backgrounds не подобраны под контент каждого видео

---

## Структура правильного видео

```
1. HOOK (5 сек) — bloom_sad_girl.mp4 С ОРИГИНАЛЬНЫМ АУДИО
   ↓
2. FREEZE FRAME (3 сек) — затемнённый последний кадр хука
   + ИНТРО субтитры: "До пизды что она 10/10, Давайте лучше разберёмся"
   + АУДИО хука ВЫКЛЮЧЕНО, начинается TTS
   ↓
3. MAIN CONTENT (40-50 сек) — BACKGROUND VIDEOS + субтитры + TTS
   - Backgrounds подобраны по настроению/теме
   - Несколько backgrounds с таймингами (смена каждые 10-15 сек)
```

---

## Шаг 1: Анализ backgrounds каталога

### Доступные backgrounds (input/backgrounds/catalog.json):
| Файл | Длина | Mood | Best for |
|------|-------|------|----------|
| pinterest_161848180356130394.mp4 | 40s | melancholic, calm | одиночество, ночные мысли |
| pinterest_48624870973153103.mp4 | 10s | romantic, epic | любовь, преданность |
| pinterest_58687601390694374.mp4 | 25s | energetic, cyberpunk | технологии, энергия |
| pinterest_6192518232549059.mp4 | 15s | calm, cozy | повседневность, уют |
| pinterest_new_109704940921189179.mp4 | 25s | melancholic, sad | потерянная любовь, грусть |
| pinterest_new_42995371468635177.mp4 | 60s | calm, peaceful | спокойствие, детство |
| pinterest_new_71353975342941705.mp4 | 8s | peaceful, serene | покой, созерцание |
| pinterest_new_8514686791397544.mp4 | 10s | peaceful, warm | дружба, закат |
| pinterest_new_899664463177102610.mp4 | 10s | romantic, passionate | любовь, страсть |
| pinterest_new_930767447964372246.mp4 | 15s | sensual, intimate | интимность, красота |
| pinterest_new_983473637372196602.mp4 | 12s | sensual, artistic | грация, самовыражение |

---

## Шаг 2: Подбор backgrounds для каждого видео

### Видео 11: "Красота не спасает от одиночества" (Attached)
- **Тема:** травма привязанности, одиночество, выбор
- **Mood:** vulnerable, melancholic → hopeful
- **Backgrounds:**
  - 0-15s: pinterest_161848180356130394.mp4 (одиночество, ночь)
  - 15-30s: pinterest_new_109704940921189179.mp4 (грусть, потеря)
  - 30-46s: pinterest_new_899664463177102610.mp4 (любовь, надежда)

### Видео 12: "Партнёр не читает мысли" (Gottman)
- **Тема:** коммуникация, ожидания, понимание
- **Mood:** reflective, thoughtful
- **Backgrounds:**
  - 0-15s: pinterest_new_42995371468635177.mp4 (спокойствие, размышления)
  - 15-30s: pinterest_6192518232549059.mp4 (повседневность)
  - 30-44s: pinterest_new_8514686791397544.mp4 (тепло, связь)

### Видео 13: "5 минут присутствия важнее 5 часов рядом" (Perel)
- **Тема:** качество внимания, близость
- **Mood:** thoughtful, intimate
- **Backgrounds:**
  - 0-15s: pinterest_new_930767447964372246.mp4 (интимность)
  - 15-30s: pinterest_new_983473637372196602.mp4 (грация, красота)
  - 30-42s: pinterest_new_899664463177102610.mp4 (близость, любовь)

### Видео 14: "Ты делаешь не то, что нужно партнёру" (Chapman)
- **Тема:** языки любви, слепые зоны
- **Mood:** confrontational → understanding
- **Backgrounds:**
  - 0-15s: pinterest_161848180356130394.mp4 (одиночество)
  - 15-30s: pinterest_new_42995371468635177.mp4 (размышления)
  - 30-45s: pinterest_48624870973153103.mp4 (романтика, понимание)

### Видео 15: "Пары распадаются от холода, не от тепла" (Fromm)
- **Тема:** страх близости, тепло vs холод
- **Mood:** empowering, warm
- **Backgrounds:**
  - 0-15s: pinterest_new_109704940921189179.mp4 (холод, одиночество)
  - 15-30s: pinterest_new_71353975342941705.mp4 (покой)
  - 30-48s: pinterest_new_899664463177102610.mp4 (тепло, любовь)

---

## Шаг 3: Исправить styled_subtitles.py

- [ ] Проверить что --hook-intro работает правильно:
  - Хук играет С ОРИГИНАЛЬНЫМ АУДИО
  - После хука — freeze frame (затемнённый)
  - На freeze frame появляется Page 1 (интро) с TTS
  - После freeze — backgrounds с остальными субтитрами

- [ ] Проверить что --bg-dir работает и использует backgrounds

---

## Шаг 4: Обновить paths в catalog.json

- [ ] Исправить paths в input/backgrounds/catalog.json:
  - Было: "downloads/backgrounds/..."
  - Нужно: "input/backgrounds/..."

---

## Шаг 5: Создать конфиги backgrounds для каждого видео

Для каждого видео создать JSON с таймингами:
```json
{
  "backgrounds": [
    {"file": "video1.mp4", "start": 0, "end": 15},
    {"file": "video2.mp4", "start": 15, "end": 30},
    {"file": "video3.mp4", "start": 30, "end": 46}
  ]
}
```

---

## Шаг 6: Рендер видео

Для каждого видео (11-15):
```bash
python scripts/styled_subtitles.py \
  downloads/bloom_XX_markup.txt \
  downloads/bloom_XX_audio.mp3 \
  downloads/bloom_XX_timestamps.json \
  --hook input/hooks/bloom_sad_girl.mp4 \
  --hook-duration 5 \
  --hook-intro \
  --bg-dir input/backgrounds/ \
  --threads 20 \
  -o output/bloom_XX_final.mp4
```

---

## Шаг 7: Проверка качества

Для каждого видео:
- [ ] Хук играет с оригинальным звуком (5 сек)
- [ ] Freeze frame с интро субтитрами (3 сек)
- [ ] Backgrounds меняются и соответствуют контенту
- [ ] TTS синхронизирован с субтитрами
- [ ] Картинка книги появляется в нужный момент

---

## Порядок выполнения

1. [x] Написать TODO
2. [x] Исправить paths в backgrounds/catalog.json (downloads → input)
3. [x] Проверить --hook-intro в styled_subtitles.py (работает корректно)
4. [x] Backgrounds используются автоматически из каталога (round-robin по страницам)
5. [x] Сгенерировать markup файлы для всех 5 видео
6. [x] Рендер видео 11 (51.6s)
7. [x] Рендер видео 12 (49.1s)
8. [x] Рендер видео 13 (47.9s)
9. [x] Рендер видео 14 (50.1s)
10. [x] Рендер видео 15 (53.9s)

## Результаты

Все видео в `output/`:
- bloom_11_final.mp4: Hook 5.4s + Freeze 5.6s + Main 40.5s = 51.6s
- bloom_12_final.mp4: Hook 5.4s + Freeze 5.8s + Main 37.9s = 49.1s
- bloom_13_final.mp4: Hook 5.4s + Freeze 6.1s + Main 36.3s = 47.9s
- bloom_14_final.mp4: Hook 5.4s + Freeze 6.2s + Main 38.5s = 50.1s
- bloom_15_final.mp4: Hook 5.4s + Freeze 6.6s + Main 41.9s = 53.9s

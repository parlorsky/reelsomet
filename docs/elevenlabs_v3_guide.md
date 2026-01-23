# ElevenLabs v3 — Полное руководство по Audio Tags

> Eleven v3 (Alpha) — самая выразительная модель ElevenLabs с поддержкой эмоций, продвинутой просодии и контекстного понимания. Выпущена 5 июня 2025.

---

## Содержание

1. [Цены](#цены)
2. [Что такое Audio Tags](#что-такое-audio-tags)
3. [Категории тегов](#категории-тегов)
4. [Примеры использования](#примеры-использования)
5. [Настройки модели](#настройки-модели)
6. [Best Practices](#best-practices)
7. [Ограничения](#ограничения)

---

## Цены

### Стоимость генерации

| Модель | Стоимость |
|--------|-----------|
| Eleven v3 | 1 кредит/символ |
| Multilingual v2 | 1 кредит/символ |
| Turbo модели | 0.5 кредита/символ |

### Тарифные планы (2026)

| План | Цена | Минуты | Доп. минуты |
|------|------|--------|-------------|
| Free | $0 | ~10 | — |
| Starter | $5/мес | ~30 | — |
| Creator | $22/мес | ~100 | ~$0.30/мин |
| Pro | $99/мес | ~500 | ~$0.24/мин |
| Scale | $330/мес | ~2,000 | ~$0.18/мин |
| Business | $1,320/мес | ~11,000 | ~$0.12/мин |

**Примечание:** Неиспользованные кредиты переносятся на следующий месяц (до 2 месяцев).

---

## Что такое Audio Tags

**Audio Tags** — это слова в квадратных скобках `[tag]`, которые модель v3 интерпретирует как режиссёрские указания для голоса.

- Теги **не произносятся вслух** — они влияют только на подачу
- Работают **только в модели v3**
- Поддерживают **70+ языков**
- Можно комбинировать несколько тегов
- Модель пытается интерпретировать **любой текст** в квадратных скобках

---

## Категории тегов

### 1. Эмоции и настроение

Базовые эмоции:
```
[sad]           — грусть
[angry]         — злость
[happy]         — радость
[happily]       — радостно
[excited]       — возбуждённо
[sorrowful]     — печально
[tired]         — устало
[nervous]       — нервно
[scared]        — испуганно
[confused]      — растерянно
```

Сложные эмоции:
```
[sarcastic]     — саркастично
[curious]       — с любопытством
[deadpan]       — невозмутимо
[playfully]     — игриво
[flatly]        — монотонно
[cheerfully]    — весело
[wistful]       — тоскливо
[annoyed]       — раздражённо
[flustered]     — смущённо
```

### 2. Подача и громкость

```
[whispers]      — шёпот
[whispering]    — шепча
[shouts]        — крик
[shouting]      — крича
[softly]        — мягко
[gently]        — нежно
[loudly]        — громко
[calm]          — спокойно
[dramatic]      — драматично
```

### 3. Невербальные звуки и реакции

```
[laughs]        — смеётся
[laughs harder] — смеётся сильнее
[starts laughing] — начинает смеяться
[wheezing]      — хрипит от смеха
[giggles]       — хихикает
[snorts]        — фыркает
[sighs]         — вздыхает
[sigh]          — вздох
[crying]        — плачет
[gasps]         — ахает
[gasp]          — ах!
[gulps]         — сглатывает
[clears throat] — прочищает горло
[breathes]      — дышит
[coughs]        — кашляет
[sniffles]      — шмыгает носом
```

### 4. Темп и паузы

```
[pause]         — пауза
[pauses]        — делает паузу
[hesitates]     — колеблется
[stammers]      — заикается
[rushed]        — торопливо
[rapid-fire]    — очень быстро
[slows down]    — замедляется
[deliberate]    — размеренно
[drawn out]     — растянуто
[continues after a beat] — продолжает после паузы
```

### 5. Акценты и диалекты

```
[British accent]        — британский акцент
[American accent]       — американский акцент
[Australian accent]     — австралийский акцент
[Southern US accent]    — южный американский акцент
[French accent]         — французский акцент
[strong French accent]  — сильный французский акцент
[strong X accent]       — сильный X акцент (замените X)
[German accent]         — немецкий акцент
[Russian accent]        — русский акцент
[Indian accent]         — индийский акцент
```

### 6. Персонажи и архетипы

```
[pirate voice]          — голос пирата
[robotic]               — роботизированно
[robotic tone]          — роботический тон
[evil scientist voice]  — голос злого учёного
[childlike tone]        — детский тон
[deep voice]            — глубокий голос
[old man voice]         — голос старика
[villain voice]         — голос злодея
```

### 7. Нарративные стили

```
[dramatic tone]         — драматический тон
[lighthearted]          — беззаботно
[reflective]            — задумчиво
[serious tone]          — серьёзный тон
[matter-of-fact]        — как факт
[awe]                   — с благоговением
[sarcastic tone]        — саркастический тон
[documentary style]     — документальный стиль
[noir narration]        — нуар-повествование
[fantasy narrator]      — фэнтези-рассказчик
[sci-fi AI voice]       — голос ИИ из научной фантастики
```

### 8. Диалоги и взаимодействие

```
[interrupting]          — прерывая
[interrupts]            — прерывает
[overlapping]           — накладываясь
[cuts in]               — вклинивается
[fast-paced]            — быстрый темп
```

### 9. Звуковые эффекты

```
[applause]              — аплодисменты
[clapping]              — хлопки
[gunshot]               — выстрел
[explosion]             — взрыв
[knocking]              — стук
[door creaks]           — скрип двери
[footsteps]             — шаги
[thunder]               — гром
[rain]                  — дождь
```

### 10. Музыкальные теги

```
[sings]                 — поёт
[singing]               — пение
[singsong]              — напевно
[rhythmically]          — ритмично
[humming]               — мурлычет
```

### 11. Акцент и ударение

```
[emphasized]            — с ударением
[stress on next word]   — ударение на следующее слово
[understated]           — приглушённо
```

### 12. Специальные эффекты (экспериментальные)

```
[vocoder]               — вокодер
[echo]                  — эхо
[pitch shift]           — изменение высоты
[radio effect]          — эффект радио
[phone call]            — звонок по телефону
```

---

## Примеры использования

### Базовый пример
```
[whispers] I can't believe it happened... [pause] [sad] It was too late.
```

### Комбинирование тегов
```
[nervously][whispers] I... I'm not sure this is going to work. [gulps] But let's try anyway.
```

### Эмоциональный переход
```
[calm] I think we should... [excited] Wait, this is brilliant!
```

### Смех с эмоцией
```
[angry][laughing] Oh, you think that's funny?
```

### Драматическая сцена
```
[dramatic tone] The door opened slowly... [pause] [whispers] Someone was inside.
[gasps] [scared] Who's there?!
```

### Диалог с прерыванием
```
[calm] I was just about to say—
[interrupting][excited] I knew it! I knew you would agree!
```

### Акцент
```
[strong British accent] Right then, shall we have a spot of tea?
```

### Нарратив
```
[documentary style] The great migration had begun. Thousands of animals...
[awe] It was a sight unlike any other.
```

### Комедийная подача
```
[deadpan] So apparently... [pause] I was supposed to turn left.
[sarcastic] Who knew reading maps was so complicated.
```

---

## Настройки модели

### Stability Slider

| Режим | Описание |
|-------|----------|
| **Creative** | Максимальная выразительность, больше эмоциональных вариаций |
| **Natural** | Баланс между выразительностью и стабильностью |
| **Robust** | Высокая стабильность, меньше реагирует на теги |

**Рекомендация:** Для работы с audio tags используйте **Creative** или **Natural**.

---

## Best Practices

### 1. Длина текста
- Используйте промпты **более 250 символов** для стабильных результатов
- Короткие промпты дают непредсказуемые результаты

### 2. Пунктуация имеет значение

| Символ | Эффект |
|--------|--------|
| `...` (многоточие) | Пауза, затухание |
| `,` (запятая) | Естественное дыхание |
| `.` (точка) | Завершение мысли |
| `!` | Восклицание, энергия |
| `?` | Вопросительная интонация |
| ЗАГЛАВНЫЕ | Ударение, акцент |

### 3. Контекст вокруг тега
- Модель учитывает **окружающий текст**
- Длинные фразы дают более стабильные результаты
- Предоставляйте контекст перед важными тегами

### 4. Выбор голоса
- **Instant Voice Clones** работают лучше всего с v3
- Убедитесь, что голос соответствует эмоциональным требованиям
- Если голос изначально "кричащий", тег `[whispers]` может не сработать

### 5. Комбинирование тегов
- Можно ставить несколько тегов подряд: `[nervous][whispers]`
- Теги складываются для создания сложных эмоций
- `[angry][laughing]` = злой смех

### 6. Генерация вариантов
- v3 даёт **вариативные результаты**
- Генерируйте несколько версий и выбирайте лучшую
- Это нормально для alpha-версии

### 7. Естественность диалогов
- Пишите так, как люди **реально говорят**
- Добавляйте хезитации: "I... I don't know"
- Используйте разговорные сокращения

---

## Ограничения

### Текущие ограничения v3 (Alpha)

| Ограничение | Описание |
|-------------|----------|
| **Нестабильность** | Короткие промпты дают непредсказуемые результаты |
| **Скорость** | 1-3 секунды на генерацию, не realtime |
| **SSML** | Break tags НЕ поддерживаются |
| **Professional Voice Clones** | Пока работают хуже Instant Clones |
| **Акценты** | Могут не всегда срабатывать, нужно экспериментировать |

### Что НЕ работает
- SSML теги (`<break>`, `<prosody>` и т.д.)
- Очень короткие фразы (< 50 символов)
- Конфликтующие теги (например, `[whispers][shouts]`)

---

## Полезные ссылки

- [ElevenLabs Pricing](https://elevenlabs.io/pricing)
- [ElevenLabs v3 Page](https://elevenlabs.io/v3)
- [API Pricing](https://elevenlabs.io/pricing/api)
- [Help Center](https://help.elevenlabs.io/)

---

## Быстрая шпаргалка

```
ЭМОЦИИ:     [sad] [happy] [angry] [excited] [nervous] [sarcastic]
ПОДАЧА:     [whispers] [shouts] [softly] [calm] [dramatic]
РЕАКЦИИ:    [laughs] [sighs] [gasps] [gulps] [crying] [clears throat]
ТЕМП:       [pause] [rushed] [slows down] [stammers] [hesitates]
АКЦЕНТЫ:    [British accent] [strong French accent] [Southern US accent]
ПЕРСОНАЖИ:  [robotic] [pirate voice] [childlike tone]
ДИАЛОГИ:    [interrupting] [overlapping] [cuts in]
ЭФФЕКТЫ:    [applause] [gunshot] [explosion] [footsteps]
```

---

*Гайд составлен на основе официальной документации ElevenLabs и сторонних источников. Январь 2026.*

#!/usr/bin/env python3
"""
Переименовывает видеофайлы по популярности (лайки + комменты)

Формат: 001_shortcode.mp4, 002_shortcode.mp4, ...

Usage:
  python rename_by_popularity.py path/to/data.csv
  python rename_by_popularity.py path/to/data.csv --dry-run
"""

import re
import os
import csv
import argparse
from pathlib import Path


def parse_engagement(description: str) -> tuple[int, int]:
    """Извлекает лайки и комменты из описания"""
    likes = 0
    comments = 0

    # Паттерны: "84K likes", "1,281 likes", "100K likes"
    likes_match = re.search(r'([\d,\.]+)([KkМм])?\s*likes?', description)
    if likes_match:
        num = likes_match.group(1).replace(',', '').replace('.', '')
        try:
            likes = int(num)
            if likes_match.group(2) and likes_match.group(2).upper() in ('K', 'М'):
                likes *= 1000
        except ValueError:
            pass

    # Паттерны: "354 comments", "1,234 comments"
    comments_match = re.search(r'([\d,]+)\s*comments?', description)
    if comments_match:
        num = comments_match.group(1).replace(',', '')
        try:
            comments = int(num)
        except ValueError:
            pass

    return likes, comments


def load_csv(csv_path: str) -> list[dict]:
    """Загружает CSV и добавляет engagement метрики"""
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            likes, comments = parse_engagement(row.get('description', ''))
            row['_likes'] = likes
            row['_comments'] = comments
            row['_engagement'] = likes + comments * 10  # Комменты весят больше
            rows.append(row)
    return rows


def rename_files(rows: list[dict], dry_run: bool = False) -> list[dict]:
    """Переименовывает файлы по рангу популярности"""
    # Сортируем по engagement (убывание)
    sorted_rows = sorted(rows, key=lambda x: x['_engagement'], reverse=True)

    # Определяем базовую папку из первого файла
    base_dir = None
    for row in sorted_rows:
        if row.get('video_file') and os.path.exists(row['video_file']):
            base_dir = os.path.dirname(row['video_file'])
            break

    if not base_dir:
        print("❌ Не найдены видеофайлы")
        return rows

    print(f"📁 Папка: {base_dir}")
    print(f"📊 Сортировка по engagement (лайки + комменты*10)\n")

    renames = []
    updated_rows = []

    for rank, row in enumerate(sorted_rows, 1):
        old_path = row.get('video_file', '')
        shortcode = row.get('shortcode', 'unknown')
        likes = row['_likes']
        comments = row['_comments']

        # Новое имя: 001_shortcode.mp4
        new_filename = f"{rank:03d}_{shortcode}.mp4"
        new_path = os.path.join(base_dir, new_filename)

        # Показываем информацию
        likes_str = f"{likes//1000}K" if likes >= 1000 else str(likes)
        print(f"  {rank:3d}. {shortcode}: {likes_str} likes, {comments} comments")

        if old_path and os.path.exists(old_path):
            if old_path != new_path:
                renames.append((old_path, new_path))
                if not dry_run:
                    # Временное имя чтобы избежать конфликтов
                    temp_path = old_path + '.tmp'
                    os.rename(old_path, temp_path)
                    renames[-1] = (temp_path, new_path)

        # Обновляем путь в row
        row_copy = dict(row)
        row_copy['video_file'] = new_path if old_path else ''
        row_copy['_rank'] = rank
        updated_rows.append(row_copy)

    # Выполняем переименования
    if renames and not dry_run:
        print(f"\n🔄 Переименовываю {len(renames)} файлов...")
        for old_path, new_path in renames:
            try:
                os.rename(old_path, new_path)
            except OSError as e:
                print(f"  ❌ Ошибка: {old_path} -> {new_path}: {e}")
        print("✓ Готово")
    elif dry_run:
        print(f"\n[DRY RUN] Было бы переименовано {len(renames)} файлов")

    return updated_rows


def save_csv(rows: list[dict], csv_path: str, dry_run: bool = False):
    """Сохраняет обновленный CSV"""
    # Сортируем по рангу
    sorted_rows = sorted(rows, key=lambda x: x.get('_rank', 999))

    # Убираем служебные поля
    fieldnames = ['url', 'shortcode', 'description', 'date', 'author', 'video_file', 'transcription', 'status']
    clean_rows = []
    for row in sorted_rows:
        clean_row = {k: row.get(k, '') for k in fieldnames}
        clean_rows.append(clean_row)

    if dry_run:
        print(f"[DRY RUN] CSV был бы обновлён: {csv_path}")
        return

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean_rows)

    print(f"📄 CSV обновлён: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Переименовывает видео по популярности',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('csv_file', help='CSV файл с данными')
    parser.add_argument('--dry-run', action='store_true', help='Только показать что будет сделано')

    args = parser.parse_args()

    if not os.path.exists(args.csv_file):
        print(f"❌ Файл не найден: {args.csv_file}")
        return 1

    print(f"📄 Загружаю: {args.csv_file}\n")

    rows = load_csv(args.csv_file)
    if not rows:
        print("❌ CSV пустой")
        return 1

    print(f"📹 Найдено {len(rows)} записей\n")

    updated = rename_files(rows, args.dry_run)
    save_csv(updated, args.csv_file, args.dry_run)

    return 0


if __name__ == '__main__':
    exit(main())

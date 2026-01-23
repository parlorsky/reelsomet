#!/usr/bin/env python3
"""
Парсит HTML из txt файла, скачивает видео, транскрибирует и сохраняет в CSV

Автоматически:
- Включает прокси при ошибках (rate limit)
- Retry проваленных URL в конце

Usage:
  python download_from_html.py page.txt
  python download_from_html.py page.txt -o ./videos
  python download_from_html.py page.txt --transcribe
"""

import re
import sys
import os
import json
import asyncio
import argparse
import csv
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# Импортируем функции ранжирования
try:
    from rename_by_popularity import parse_engagement, rename_files as rank_files
    HAS_RANKING = True
except ImportError:
    HAS_RANKING = False

# Загружаем .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(env_path)
except ImportError:
    pass

# Импортируем downloader
try:
    from instagram_downloader import SnapInstaDownloader, ProxyManager, HAS_SOCKS
except ImportError:
    print("Ошибка: не найден instagram_downloader.py")
    print("Убедитесь что файл находится в той же папке")
    sys.exit(1)

# OpenAI для транскрибации
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


def extract_instagram_urls(html: str) -> list:
    """Извлекает ссылки на посты/reels из HTML"""
    pattern = r'href="(/[^/]+/(?:reel|p)/[A-Za-z0-9_-]+/[^"]*)"'
    matches = re.findall(pattern, html)

    seen = set()
    unique = []
    for path in matches:
        clean_path = path.split('?')[0]
        if clean_path not in seen:
            seen.add(clean_path)
            unique.append(f"https://www.instagram.com{clean_path}")

    return unique


def extract_audio(video_path: str) -> str:
    """Извлекает аудио из видео в mp3"""
    audio_path = tempfile.mktemp(suffix='.mp3')
    try:
        subprocess.run([
            'ffmpeg', '-i', video_path,
            '-vn', '-acodec', 'libmp3lame', '-q:a', '2',
            '-ar', '16000', '-ac', '1',
            '-y', audio_path
        ], capture_output=True, check=True, timeout=120)
        return audio_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def transcribe_audio(audio_path: str, client: OpenAI) -> str:
    """Транскрибирует аудио через OpenAI API"""
    try:
        with open(audio_path, 'rb') as audio_file:
            transcription = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=audio_file,
                response_format="text"
            )
        return transcription if isinstance(transcription, str) else transcription.text
    except Exception as e:
        return f"[Ошибка транскрибации: {str(e)[:100]}]"


def transcribe_video(video_path: str, client: OpenAI) -> str:
    """Извлекает аудио и транскрибирует видео"""
    audio_path = extract_audio(video_path)
    if not audio_path:
        return "[Ошибка извлечения аудио]"

    try:
        result = transcribe_audio(audio_path, client)
        return result
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


async def scrape_metadata(page, url: str) -> dict:
    """Извлекает метаданные поста из Instagram страницы"""
    metadata = {
        'url': url,
        'shortcode': url.rstrip('/').split('/')[-1],
        'description': '',
        'date': '',
        'author': '',
    }

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        scripts = await page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts:
            try:
                text = await script.inner_text()
                data = json.loads(text)
                if isinstance(data, dict):
                    if 'articleBody' in data:
                        metadata['description'] = data.get('articleBody', '')[:500]
                    elif 'caption' in data:
                        metadata['description'] = data.get('caption', '')[:500]
                    if 'dateCreated' in data:
                        metadata['date'] = data.get('dateCreated', '')[:10]
                    elif 'uploadDate' in data:
                        metadata['date'] = data.get('uploadDate', '')[:10]
                    if 'author' in data:
                        author = data.get('author', {})
                        if isinstance(author, dict):
                            metadata['author'] = author.get('name', '') or author.get('identifier', '')
                        elif isinstance(author, str):
                            metadata['author'] = author
            except:
                pass

        if not metadata['description']:
            try:
                og_desc = await page.query_selector('meta[property="og:description"]')
                if og_desc:
                    content = await og_desc.get_attribute('content')
                    if content:
                        metadata['description'] = content[:500]
            except:
                pass

        if not metadata['description']:
            try:
                title = await page.title()
                if title and 'Instagram' in title:
                    metadata['description'] = title[:500]
            except:
                pass

    except Exception as e:
        pass

    return metadata


async def setup_proxy_manager():
    """Настраивает и возвращает ProxyManager"""
    if not HAS_SOCKS:
        return None

    print("\n🔄 Загружаю SOCKS5 прокси...")
    proxy_manager = ProxyManager()
    await proxy_manager.fetch_proxies()
    await proxy_manager.test_proxies(limit=20)

    if not proxy_manager.working_proxies:
        print("⚠️  Рабочие прокси не найдены")
        return None

    print(f"✓ Найдено {len(proxy_manager.working_proxies)} рабочих прокси")
    return proxy_manager


async def download_batch(urls: list, output_dir: str, max_tabs: int, proxy_manager=None) -> list:
    """Скачивает пакет URL"""
    async with SnapInstaDownloader(headless=True, max_tabs=max_tabs, proxy_manager=proxy_manager) as dl:
        return await dl.download_all(urls, output_dir)


async def main_async(html_file: str, output_dir: str, use_proxy: bool, max_tabs: int, do_transcribe: bool, do_rank: bool = False):
    # Читаем HTML из файла
    print(f"📄 Читаю файл: {html_file}")
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()

    # Парсим ссылки
    urls = extract_instagram_urls(html)

    if not urls:
        print("❌ Ссылки не найдены в файле!")
        return False

    print(f"🔗 Найдено {len(urls)} ссылок:")
    for i, url in enumerate(urls, 1):
        shortcode = url.rstrip('/').split('/')[-1]
        print(f"  {i}. {shortcode}")

    # Создаем папку
    os.makedirs(output_dir, exist_ok=True)

    # Настраиваем прокси если нужно
    proxy_manager = None
    if use_proxy:
        proxy_manager = await setup_proxy_manager()

    # Собираем метаданные
    print(f"\n📝 Собираю метаданные...")
    from playwright.async_api import async_playwright

    all_metadata = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = await context.new_page()

        for i, url in enumerate(urls, 1):
            shortcode = url.rstrip('/').split('/')[-1]
            print(f"  [{i}/{len(urls)}] {shortcode}...", end=' ', flush=True)
            meta = await scrape_metadata(page, url)
            all_metadata[url] = meta
            print(f"✓" if meta['description'] else "нет описания")

        await browser.close()

    # === ПЕРВЫЙ ПРОХОД: скачивание ===
    print(f"\n⬇️  Скачиваю {len(urls)} видео...")
    print(f"   Параллельных загрузок: {max_tabs}")

    results = await download_batch(urls, output_dir, max_tabs, proxy_manager)

    # Проверяем сколько ошибок
    failed = [r for r in results if not r['success']]
    success_count = len(results) - len(failed)

    print(f"\n📊 Первый проход: {success_count}/{len(urls)} скачано")

    # === АВТО-RETRY с прокси если много ошибок ===
    if len(failed) > 0:
        failed_urls = [r['url'] for r in failed]

        # Если не было прокси и >20% ошибок — включаем прокси
        if not proxy_manager and len(failed) > len(urls) * 0.2:
            print(f"\n⚠️  {len(failed)} ошибок ({len(failed)*100//len(urls)}%) — включаю прокси...")
            proxy_manager = await setup_proxy_manager()

        if proxy_manager or len(failed) <= 5:
            # Retry проваленных
            max_retries = 3
            for retry_num in range(max_retries):
                if not failed_urls:
                    break

                print(f"\n🔄 Retry #{retry_num + 1}: {len(failed_urls)} URL...")

                retry_results = await download_batch(failed_urls, output_dir, max(1, max_tabs // 2), proxy_manager)

                # Обновляем результаты
                still_failed = []
                for rr in retry_results:
                    # Находим и обновляем в основных результатах
                    for i, r in enumerate(results):
                        if r['url'] == rr['url']:
                            results[i] = rr
                            break

                    if not rr['success']:
                        still_failed.append(rr['url'])

                retry_success = len(failed_urls) - len(still_failed)
                print(f"   ✓ Скачано: {retry_success}/{len(failed_urls)}")

                failed_urls = still_failed

                if not failed_urls:
                    break

                # Ждём перед следующим retry
                if retry_num < max_retries - 1 and failed_urls:
                    print(f"   ⏳ Жду 10 секунд перед следующей попыткой...")
                    await asyncio.sleep(10)

    # === ТРАНСКРИБАЦИЯ ===
    transcriptions = {}
    if do_transcribe:
        if not HAS_OPENAI:
            print("\n⚠️  OpenAI не установлен. pip install openai")
        elif not os.environ.get('OPENAI_API_KEY'):
            print("\n⚠️  OPENAI_API_KEY не задан")
        else:
            # Собираем успешно скачанные
            to_transcribe = []
            for r in results:
                if r['success'] and r.get('files'):
                    video_path = r['files'][0]
                    if os.path.exists(video_path):
                        to_transcribe.append((r['url'], video_path))

            if to_transcribe:
                print(f"\n🎤 Транскрибирую {len(to_transcribe)} видео...")
                client = OpenAI()

                from concurrent.futures import ThreadPoolExecutor, as_completed

                def transcribe_task(item):
                    url, video_path = item
                    shortcode = url.rstrip('/').split('/')[-1]
                    text = transcribe_video(video_path, client)
                    return url, shortcode, text

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(transcribe_task, item): item for item in to_transcribe}
                    done = 0
                    for future in as_completed(futures):
                        done += 1
                        url, shortcode, text = future.result()
                        transcriptions[url] = text
                        print(f"  [{done}/{len(to_transcribe)}] {shortcode}: {len(text)} символов")

    # === СОХРАНЯЕМ CSV ===
    final_data = []
    for r in results:
        url = r['url']
        meta = all_metadata.get(url, {})
        final_data.append({
            'url': url,
            'shortcode': meta.get('shortcode', url.rstrip('/').split('/')[-1]),
            'description': meta.get('description', ''),
            'date': meta.get('date', ''),
            'author': meta.get('author', ''),
            'video_file': r.get('files', [''])[0] if r['success'] else '',
            'transcription': transcriptions.get(url, ''),
            'status': 'OK' if r['success'] else r.get('error', 'Error'),
        })

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_file = os.path.join(output_dir, f"data_{timestamp}.csv")

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['url', 'shortcode', 'description', 'date', 'author', 'video_file', 'transcription', 'status'])
        writer.writeheader()
        writer.writerows(final_data)

    # === РАНЖИРОВАНИЕ ПО ПОПУЛЯРНОСТИ ===
    if do_rank:
        if not HAS_RANKING:
            print("\n⚠️  Модуль ранжирования не найден (rename_by_popularity.py)")
        else:
            print(f"\n📊 Ранжирую файлы по популярности...")
            # Добавляем engagement метрики
            for row in final_data:
                likes, comments = parse_engagement(row.get('description', ''))
                row['_likes'] = likes
                row['_comments'] = comments
                row['_engagement'] = likes + comments * 10

            # Переименовываем и обновляем CSV
            ranked_data = rank_files(final_data, dry_run=False)

            # Сохраняем обновленный CSV
            sorted_ranked = sorted(ranked_data, key=lambda x: x.get('_rank', 999))
            fieldnames = ['url', 'shortcode', 'description', 'date', 'author', 'video_file', 'transcription', 'status']
            clean_rows = [{k: row.get(k, '') for k in fieldnames} for row in sorted_ranked]

            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(clean_rows)

    # === ИТОГИ ===
    success = sum(1 for r in results if r['success'])
    failed = sum(1 for r in results if not r['success'])
    transcribed = len(transcriptions)

    print(f"\n{'='*50}")
    print("📊 ИТОГИ:")
    print(f"  ✓ Скачано: {success}/{len(urls)}")
    print(f"  ✓ Транскрибировано: {transcribed}")
    print(f"  📁 Папка: {output_dir}")
    print(f"  📄 CSV: {csv_file}")

    if failed > 0:
        print(f"\n❌ Не удалось скачать ({failed}):")
        for r in results:
            if not r['success']:
                shortcode = r['url'].rstrip('/').split('/')[-1]
                print(f"  - {shortcode}: {r.get('error', 'Unknown error')}")

    return success > 0


def main():
    parser = argparse.ArgumentParser(
        description='Скачивает Instagram видео с метаданными и транскрибацией',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python download_from_html.py instagram.txt
  python download_from_html.py page.txt -o ./my_videos
  python download_from_html.py page.txt --transcribe

Автоматически:
  - Включает прокси при >20% ошибок
  - Retry проваленных URL (до 3 раз)

Для транскрибации: export OPENAI_API_KEY=sk-...
        """
    )
    parser.add_argument('html_file', help='Файл с HTML кодом Instagram')
    parser.add_argument('-o', '--output', default='../downloads', help='Папка для видео')
    parser.add_argument('--proxy', action='store_true', help='Использовать прокси сразу')
    parser.add_argument('-t', '--tabs', type=int, default=3, help='Параллельных загрузок')
    parser.add_argument('--transcribe', action='store_true', help='Транскрибировать через OpenAI')
    parser.add_argument('--rank', action='store_true', help='Переименовать файлы по популярности (001_xxx.mp4)')

    args = parser.parse_args()

    if not os.path.exists(args.html_file):
        print(f"❌ Файл не найден: {args.html_file}")
        sys.exit(1)

    try:
        ok = asyncio.run(main_async(
            args.html_file,
            args.output,
            args.proxy,
            args.tabs,
            args.transcribe,
            args.rank
        ))
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\n⛔ Отменено")
        sys.exit(1)


if __name__ == '__main__':
    main()

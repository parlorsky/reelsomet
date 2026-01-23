#!/usr/bin/env python3
"""
Instagram Profile Scraper
Собирает все посты с профиля и сохраняет метаданные + видео

Usage:
  python instagram_profile_scraper.py https://www.instagram.com/username/
  python instagram_profile_scraper.py https://www.instagram.com/username/ -o output_folder
  python instagram_profile_scraper.py https://www.instagram.com/username/ --proxy --download
"""

import re
import sys
import os
import json
import csv
import asyncio
import argparse
from datetime import datetime
from urllib.parse import urljoin
from playwright.async_api import async_playwright

# Импортируем downloader для скачивания видео
try:
    from instagram_downloader import SnapInstaDownloader, ProxyManager, HAS_SOCKS
except ImportError:
    SnapInstaDownloader = None
    ProxyManager = None
    HAS_SOCKS = False


class InstagramProfileScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.playwright = None
        self.posts = []

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def scrape_profile(self, profile_url: str, max_posts: int = None) -> list:
        """Собрать все посты с профиля"""
        context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 900}
        )
        page = await context.new_page()

        try:
            print(f"Загружаю профиль: {profile_url}")
            await page.goto(profile_url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(2)

            # Проверяем, не требуется ли логин
            if 'login' in page.url.lower():
                print("Требуется авторизация в Instagram!")
                print("Instagram ограничивает доступ без логина.")
                return []

            # Получаем имя пользователя
            username = profile_url.rstrip('/').split('/')[-1]
            print(f"Профиль: @{username}")

            # Собираем ссылки на посты прокруткой
            post_links = set()
            last_count = 0
            no_change_count = 0

            print("Прокручиваю страницу и собираю посты...")

            while True:
                # Находим все ссылки на посты
                links = await page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]')
                for link in links:
                    href = await link.get_attribute('href')
                    if href:
                        full_url = urljoin('https://www.instagram.com', href)
                        post_links.add(full_url)

                current_count = len(post_links)
                print(f"\r  Найдено постов: {current_count}", end='', flush=True)

                # Проверяем лимит
                if max_posts and current_count >= max_posts:
                    print(f"\n  Достигнут лимит {max_posts} постов")
                    break

                # Прокручиваем вниз
                await page.evaluate('window.scrollBy(0, 1000)')
                await asyncio.sleep(1.5)

                # Проверяем, появились ли новые посты
                if current_count == last_count:
                    no_change_count += 1
                    if no_change_count >= 5:
                        print("\n  Все посты загружены")
                        break
                else:
                    no_change_count = 0
                last_count = current_count

            post_links = list(post_links)
            if max_posts:
                post_links = post_links[:max_posts]

            print(f"\nВсего найдено {len(post_links)} постов")
            return post_links

        except Exception as e:
            print(f"Ошибка при загрузке профиля: {e}")
            return []
        finally:
            await context.close()

    async def get_post_metadata(self, post_url: str, context) -> dict:
        """Получить метаданные поста"""
        page = await context.new_page()
        metadata = {
            'url': post_url,
            'shortcode': post_url.rstrip('/').split('/')[-1],
            'type': 'reel' if '/reel/' in post_url else 'post',
            'description': '',
            'date': '',
            'timestamp': '',
            'likes': '',
            'comments': '',
            'is_video': False,
            'video_url': '',
            'thumbnail': '',
        }

        try:
            await page.goto(post_url, wait_until='networkidle', timeout=45000)
            await asyncio.sleep(2)

            # Пробуем получить JSON-LD данные
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    text = await script.inner_text()
                    data = json.loads(text)
                    if isinstance(data, dict):
                        if 'caption' in data:
                            metadata['description'] = data.get('caption', '')[:500]
                        if 'uploadDate' in data:
                            metadata['date'] = data.get('uploadDate', '')
                            metadata['timestamp'] = data.get('uploadDate', '')
                        if 'video' in data:
                            metadata['is_video'] = True
                            metadata['video_url'] = data.get('contentUrl', '')
                        if 'thumbnailUrl' in data:
                            metadata['thumbnail'] = data.get('thumbnailUrl', '')
                except:
                    pass

            # Альтернативно ищем в meta тегах
            if not metadata['description']:
                meta_desc = await page.query_selector('meta[property="og:description"]')
                if meta_desc:
                    content = await meta_desc.get_attribute('content')
                    if content:
                        metadata['description'] = content[:500]

            # Ищем дату в странице
            if not metadata['date']:
                time_el = await page.query_selector('time[datetime]')
                if time_el:
                    dt = await time_el.get_attribute('datetime')
                    if dt:
                        metadata['date'] = dt
                        metadata['timestamp'] = dt

            # Проверяем, есть ли видео
            video = await page.query_selector('video')
            if video:
                metadata['is_video'] = True
                src = await video.get_attribute('src')
                if src:
                    metadata['video_url'] = src

            # Форматируем дату
            if metadata['date']:
                try:
                    dt = datetime.fromisoformat(metadata['date'].replace('Z', '+00:00'))
                    metadata['date'] = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass

        except Exception as e:
            metadata['error'] = str(e)[:100]
        finally:
            await page.close()

        return metadata

    async def scrape_posts_metadata(self, post_urls: list, max_concurrent: int = 3) -> list:
        """Собрать метаданные для всех постов"""
        print(f"\nСобираю метаданные для {len(post_urls)} постов...")

        context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1280, 'height': 900}
        )

        results = []
        sem = asyncio.Semaphore(max_concurrent)

        async def fetch_one(url, index):
            async with sem:
                print(f"\r  [{index}/{len(post_urls)}] Обрабатываю...", end='', flush=True)
                meta = await self.get_post_metadata(url, context)
                await asyncio.sleep(1)  # Задержка между запросами
                return meta

        tasks = [fetch_one(url, i) for i, url in enumerate(post_urls, 1)]
        results = await asyncio.gather(*tasks)

        await context.close()
        print(f"\n  Готово!")

        self.posts = results
        return results


def save_to_csv(posts: list, filepath: str):
    """Сохранить в CSV"""
    fieldnames = ['url', 'shortcode', 'type', 'description', 'date', 'is_video', 'video_file']

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for post in posts:
            writer.writerow(post)

    print(f"Сохранено в CSV: {filepath}")


def save_to_excel(posts: list, filepath: str):
    """Сохранить в Excel"""
    try:
        import pandas as pd
        df = pd.DataFrame(posts)
        # Выбираем нужные колонки
        cols = ['url', 'shortcode', 'type', 'description', 'date', 'is_video', 'video_file']
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
        df.to_excel(filepath, index=False, engine='openpyxl')
        print(f"Сохранено в Excel: {filepath}")
    except ImportError:
        print("Для Excel установите: pip install pandas openpyxl")
        # Fallback to CSV
        csv_path = filepath.replace('.xlsx', '.csv')
        save_to_csv(posts, csv_path)


async def download_videos(posts: list, output_dir: str, use_proxy: bool = False):
    """Скачать видео через snapinsta"""
    if not SnapInstaDownloader:
        print("Не найден instagram_downloader.py!")
        return

    video_posts = [p for p in posts if p.get('is_video') or p.get('type') == 'reel']
    if not video_posts:
        print("Нет видео для скачивания")
        return

    print(f"\nСкачиваю {len(video_posts)} видео...")

    proxy_manager = None
    if use_proxy and HAS_SOCKS:
        proxy_manager = ProxyManager()
        await proxy_manager.fetch_proxies()
        await proxy_manager.test_proxies(limit=15)
        if not proxy_manager.working_proxies:
            proxy_manager = None

    async with SnapInstaDownloader(headless=True, max_tabs=3, proxy_manager=proxy_manager) as dl:
        urls = [p['url'] for p in video_posts]
        results = await dl.download_all(urls, output_dir)

    # Обновляем posts с путями к файлам
    url_to_files = {r['url']: r['files'] for r in results if r['success']}
    for post in posts:
        files = url_to_files.get(post['url'], [])
        post['video_file'] = files[0] if files else ''

    return results


async def main_async(profile_url: str, output_dir: str, max_posts: int,
                     download: bool, use_proxy: bool, show_browser: bool):
    os.makedirs(output_dir, exist_ok=True)

    # Извлекаем username для имени файла
    username = profile_url.rstrip('/').split('/')[-1]

    async with InstagramProfileScraper(headless=not show_browser) as scraper:
        # 1. Собираем ссылки на посты
        post_urls = await scraper.scrape_profile(profile_url, max_posts)

        if not post_urls:
            print("Не удалось найти посты")
            return False

        # 2. Собираем метаданные
        posts = await scraper.scrape_posts_metadata(post_urls, max_concurrent=2)

        # 3. Скачиваем видео если нужно
        if download:
            await download_videos(posts, output_dir, use_proxy)

        # 4. Сохраняем результаты
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # CSV всегда
        csv_path = os.path.join(output_dir, f'{username}_{timestamp}.csv')
        save_to_csv(posts, csv_path)

        # Excel если возможно
        try:
            import pandas
            xlsx_path = os.path.join(output_dir, f'{username}_{timestamp}.xlsx')
            save_to_excel(posts, xlsx_path)
        except ImportError:
            pass

        # Статистика
        print(f"\n{'='*60}")
        print("ИТОГИ:")
        print(f"  Всего постов: {len(posts)}")
        print(f"  Видео/Reels: {sum(1 for p in posts if p.get('is_video') or p.get('type')=='reel')}")
        print(f"  Фото: {sum(1 for p in posts if not p.get('is_video') and p.get('type')!='reel')}")
        if download:
            downloaded = sum(1 for p in posts if p.get('video_file'))
            print(f"  Скачано видео: {downloaded}")

        return True


def main():
    parser = argparse.ArgumentParser(description='Instagram Profile Scraper')
    parser.add_argument('profile_url', help='URL профиля Instagram')
    parser.add_argument('-o', '--output', default='../downloads', help='Папка для результатов')
    parser.add_argument('-n', '--max-posts', type=int, help='Максимум постов для сбора')
    parser.add_argument('--download', action='store_true', help='Скачать видео')
    parser.add_argument('--proxy', action='store_true', help='Использовать SOCKS5 прокси')
    parser.add_argument('--show', action='store_true', help='Показать браузер')

    args = parser.parse_args()

    if 'instagram.com' not in args.profile_url:
        print("Ошибка: укажите URL профиля Instagram")
        sys.exit(1)

    try:
        ok = asyncio.run(main_async(
            args.profile_url,
            args.output,
            args.max_posts,
            args.download,
            args.proxy,
            args.show
        ))
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\nОтменено")
        sys.exit(1)


if __name__ == '__main__':
    main()

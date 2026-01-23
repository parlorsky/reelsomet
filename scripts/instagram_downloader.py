#!/usr/bin/env python3
"""
Instagram Downloader via SnapInsta.to
С поддержкой SOCKS5 прокси и ротацией

Usage:
  python instagram_downloader.py <url>
  python instagram_downloader.py -f urls.txt -o downloads
  python instagram_downloader.py --proxy              # бесплатные SOCKS5 прокси
  python instagram_downloader.py --proxy-file proxies.txt
"""

import re
import sys
import os
import ssl
import random
import asyncio
import argparse
import aiohttp
import aiofiles
from urllib.parse import unquote
from playwright.async_api import async_playwright

try:
    from aiohttp_socks import ProxyConnector
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False

try:
    from aiohttp.resolver import AsyncResolver
    HAS_AIODNS = True
except ImportError:
    HAS_AIODNS = False

# Google DNS servers
DNS_NAMESERVERS = ['8.8.8.8', '8.8.4.4']


class ProxyManager:
    """Менеджер SOCKS5 прокси"""

    PROXY_SOURCES = [
        # SOCKS5 - лучше работают для HTTPS
        "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    ]

    def __init__(self):
        self.proxies = []
        self.working_proxies = []
        self.failed_proxies = set()
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    async def fetch_proxies(self) -> list:
        """Получить SOCKS5 прокси"""
        print("Загружаю SOCKS5 прокси...")
        all_proxies = set()

        resolver = AsyncResolver(nameservers=DNS_NAMESERVERS) if HAS_AIODNS else None
        connector = aiohttp.TCPConnector(ssl=self.ssl_ctx, resolver=resolver)
        async with aiohttp.ClientSession(connector=connector) as session:
            for url in self.PROXY_SOURCES:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            for line in text.split('\n'):
                                line = line.strip()
                                # Убираем префиксы
                                for prefix in ['socks5://', 'socks5h://', 'http://', 'https://']:
                                    if line.startswith(prefix):
                                        line = line[len(prefix):]
                                if ':' in line and line[0].isdigit():
                                    all_proxies.add(line)
                except Exception as e:
                    pass

        self.proxies = list(all_proxies)
        print(f"Найдено {len(self.proxies)} прокси")
        return self.proxies

    def load_from_file(self, filepath: str) -> list:
        """Загрузить прокси из файла"""
        with open(filepath, 'r') as f:
            self.proxies = []
            for line in f:
                line = line.strip()
                for prefix in ['socks5://', 'socks5h://', 'http://', 'https://']:
                    if line.startswith(prefix):
                        line = line[len(prefix):]
                if ':' in line:
                    self.proxies.append(line)
        print(f"Загружено {len(self.proxies)} прокси")
        return self.proxies

    async def test_proxy(self, proxy: str) -> bool:
        """Проверить SOCKS5 прокси"""
        if not HAS_SOCKS:
            return False
        try:
            resolver = AsyncResolver(nameservers=DNS_NAMESERVERS) if HAS_AIODNS else None
            connector = ProxyConnector.from_url(f'socks5://{proxy}', ssl=self.ssl_ctx, resolver=resolver)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get('https://api.ipify.org/', timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    return resp.status == 200
        except:
            return False

    async def test_proxies(self, limit: int = 15) -> list:
        """Найти рабочие прокси"""
        if not self.proxies:
            return []

        if not HAS_SOCKS:
            print("Установите aiohttp-socks: pip install aiohttp-socks")
            return []

        print(f"Тестирую прокси (ищу {limit} рабочих)...")

        sample = random.sample(self.proxies, min(100, len(self.proxies)))
        working = []

        tasks = [self.test_proxy(p) for p in sample]
        results = await asyncio.gather(*tasks)

        for proxy, ok in zip(sample, results):
            if ok:
                working.append(proxy)
                if len(working) >= limit:
                    break

        self.working_proxies = working
        print(f"Рабочих прокси: {len(working)}")
        return working

    def get_random_proxy(self) -> str:
        """Случайный рабочий прокси"""
        available = [p for p in self.working_proxies if p not in self.failed_proxies]
        if not available:
            self.failed_proxies.clear()
            available = self.working_proxies
        return random.choice(available) if available else None

    def mark_failed(self, proxy: str):
        self.failed_proxies.add(proxy)


class SnapInstaDownloader:
    def __init__(self, headless: bool = True, max_tabs: int = 3, proxy_manager: ProxyManager = None):
        self.headless = headless
        self.max_tabs = max_tabs
        self.proxy_manager = proxy_manager
        self.browser = None
        self.playwright = None
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    def extract_download_urls(self, content: str) -> list:
        urls = []
        patterns = [
            r'https://(?:dl|i)\.snapcdn\.app/(?:get|photo)\?token=[^"\'<>\s]+',
            r'https://scontent[^"\'<>\s]+\.(?:mp4|jpg|webp|png)',
            r'href=["\']([^"\']*(?:snapcdn|scontent)[^"\']*)["\']',
        ]
        for p in patterns:
            urls.extend(re.findall(p, content))

        seen = set()
        unique = []
        for url in urls:
            url = unquote(url).strip()
            if url not in seen and url.startswith('http'):
                seen.add(url)
                unique.append(url)
        return unique

    async def create_context(self, proxy: str = None):
        opts = {
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'viewport': {'width': 1280, 'height': 720}
        }
        if proxy:
            opts['proxy'] = {'server': f'socks5://{proxy}'}
        return await self.browser.new_context(**opts)

    async def accept_cookies(self, context) -> None:
        page = await context.new_page()
        try:
            await page.goto('https://snapinsta.to/ru', wait_until='domcontentloaded', timeout=45000)
            await asyncio.sleep(2)
            await page.evaluate('''() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.includes('Consent') || btn.classList.contains('fc-cta-consent')) {
                        btn.click(); return;
                    }
                }
            }''')
            await asyncio.sleep(1)
        except:
            pass
        finally:
            await page.close()

    async def get_media_urls(self, instagram_url: str, context) -> list:
        page = await context.new_page()
        try:
            await page.goto('https://snapinsta.to/ru', wait_until='domcontentloaded', timeout=45000)
            await asyncio.sleep(1)

            await page.evaluate('() => { const o = document.querySelector(".fc-consent-root"); if(o) o.remove(); }')

            await page.fill('input[name="url"], input#url, input[type="text"]', instagram_url)
            await asyncio.sleep(0.5)
            await page.click('button[type="submit"], button.btn-download, button:has-text("Скачать")', force=True)
            await asyncio.sleep(3)

            try:
                await page.wait_for_selector('a[href*="snapcdn"], .download-items', timeout=20000)
            except:
                pass
            await asyncio.sleep(2)

            content = await page.content()
            urls = self.extract_download_urls(content)

            for link in await page.query_selector_all('a[href*="snapcdn"]'):
                href = await link.get_attribute('href')
                if href and href.startswith('http'):
                    urls.append(href)

            return list(dict.fromkeys(urls))
        except Exception as e:
            raise e
        finally:
            await page.close()

    async def download_file(self, url: str, output_dir: str, proxy: str = None) -> tuple:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://snapinsta.to/'}

        resolver = AsyncResolver(nameservers=DNS_NAMESERVERS) if HAS_AIODNS else None
        if proxy and HAS_SOCKS:
            connector = ProxyConnector.from_url(f'socks5://{proxy}', ssl=self.ssl_ctx, resolver=resolver)
        else:
            connector = aiohttp.TCPConnector(ssl=self.ssl_ctx, resolver=resolver)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                resp.raise_for_status()

                filename = None
                cd = resp.headers.get('Content-Disposition', '')
                m = re.search(r'filename[*]?=["\']?(?:utf-8\'\')?([^"\';\n]+)', cd)
                if m:
                    filename = unquote(m.group(1))
                if not filename:
                    import hashlib
                    filename = hashlib.md5(url.encode()).hexdigest()[:16]

                ct = resp.headers.get('Content-Type', '')
                if 'video' in ct and not filename.endswith('.mp4'):
                    filename += '.mp4'
                elif 'image' in ct and not any(filename.endswith(e) for e in ['.jpg','.jpeg','.webp','.png']):
                    filename += '.jpg'

                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                filepath = os.path.join(output_dir, filename)

                async with aiofiles.open(filepath, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        await f.write(chunk)

                return filepath, os.path.getsize(filepath) / (1024*1024)

    async def process_url(self, instagram_url: str, output_dir: str, index: int, total: int, sem: asyncio.Semaphore) -> dict:
        # Большая задержка для избежания rate limit
        await asyncio.sleep((index - 1) * 2 + random.uniform(0, 2))

        async with sem:
            result = {'url': instagram_url, 'success': False, 'files': [], 'error': None}
            prefix = f"[{index}/{total}]"

            proxy = self.proxy_manager.get_random_proxy() if self.proxy_manager else None
            max_retries = 5  # Больше retry

            for attempt in range(max_retries):
                proxy_info = f" (proxy)" if proxy else ""
                try:
                    print(f"{prefix} Обрабатываю: {instagram_url}{proxy_info}")

                    context = await self.create_context(proxy)
                    await self.accept_cookies(context)
                    try:
                        urls = await self.get_media_urls(instagram_url, context)
                    finally:
                        await context.close()

                    if not urls:
                        # Rate limit - ждём и пробуем снова
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 5 + random.uniform(0, 3)
                            print(f"{prefix} Rate limit, жду {wait_time:.0f}с...")
                            await asyncio.sleep(wait_time)
                            if self.proxy_manager:
                                if proxy:
                                    self.proxy_manager.mark_failed(proxy)
                                proxy = self.proxy_manager.get_random_proxy()
                            continue
                        result['error'] = "Не найдены ссылки"
                        print(f"{prefix} Ошибка: {result['error']}")
                        return result

                    video_urls = [u for u in urls if 'dl.snapcdn' in u or '.mp4' in u.lower()]
                    to_download = video_urls if video_urls else urls[:1]

                    for dl_url in to_download:
                        try:
                            filepath, size = await self.download_file(dl_url, output_dir, proxy)
                            result['files'].append(filepath)
                            print(f"{prefix} Сохранено: {os.path.basename(filepath)} ({size:.2f} MB)")
                        except Exception as e:
                            print(f"{prefix} Ошибка скачивания: {e}")

                    result['success'] = len(result['files']) > 0
                    break

                except Exception as e:
                    if self.proxy_manager and proxy:
                        self.proxy_manager.mark_failed(proxy)
                        proxy = self.proxy_manager.get_random_proxy()
                        if attempt < max_retries - 1:
                            continue
                    result['error'] = str(e)[:100]
                    print(f"{prefix} Ошибка: {result['error']}")

            return result

    async def download_all(self, urls: list, output_dir: str = '.') -> list:
        total = len(urls)
        proxy_info = f", прокси: {len(self.proxy_manager.working_proxies)}" if self.proxy_manager else ""
        print(f"\nСкачивание {total} URL ({self.max_tabs} потоков{proxy_info})")
        print("=" * 60)

        sem = asyncio.Semaphore(self.max_tabs)
        tasks = [self.process_url(url, output_dir, i, total, sem) for i, url in enumerate(urls, 1)]
        return await asyncio.gather(*tasks)


async def main_async(urls, output_dir, workers, headless, use_proxy, proxy_file):
    proxy_manager = None

    if use_proxy or proxy_file:
        if not HAS_SOCKS:
            print("Установите: pip install aiohttp-socks")
            print("Работаю без прокси...")
        else:
            proxy_manager = ProxyManager()
            if proxy_file:
                proxy_manager.load_from_file(proxy_file)
            else:
                await proxy_manager.fetch_proxies()
            await proxy_manager.test_proxies(limit=15)

            if not proxy_manager.working_proxies:
                print("Нет рабочих прокси, работаю без них")
                proxy_manager = None

    async with SnapInstaDownloader(headless=headless, max_tabs=workers, proxy_manager=proxy_manager) as dl:
        results = await dl.download_all(urls, output_dir)

    print("\n" + "=" * 60)
    print("ИТОГИ:")
    success = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    print(f"Успешно: {len(success)}/{len(results)}")
    print(f"Файлов: {sum(len(r['files']) for r in results)}")

    if success:
        print("\nСкачано:")
        for r in success:
            for f in r['files']:
                print(f"  {f}")
    if failed:
        print("\nОшибки:")
        for r in failed:
            print(f"  {r['url']}: {r['error']}")

    return len(success) > 0


def main():
    parser = argparse.ArgumentParser(description='Instagram Downloader с SOCKS5 прокси')
    parser.add_argument('urls', nargs='*', help='Instagram URL')
    parser.add_argument('-f', '--file', help='Файл с URL')
    parser.add_argument('-o', '--output', default='.', help='Папка')
    parser.add_argument('-w', '--workers', type=int, default=3, help='Потоков (default: 3)')
    parser.add_argument('--proxy', action='store_true', help='Использовать бесплатные SOCKS5')
    parser.add_argument('--proxy-file', help='Файл с прокси')
    parser.add_argument('--show', action='store_true', help='Показать браузер')

    args = parser.parse_args()
    urls = list(args.urls)

    if args.file and os.path.exists(args.file):
        with open(args.file) as f:
            urls.extend([l.strip() for l in f if 'instagram.com' in l])

    urls = list(dict.fromkeys([u for u in urls if 'instagram.com' in u]))

    if not urls:
        parser.print_help()
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    try:
        ok = asyncio.run(main_async(urls, args.output, args.workers, not args.show, args.proxy, args.proxy_file))
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\nОтменено")
        sys.exit(1)


if __name__ == '__main__':
    main()

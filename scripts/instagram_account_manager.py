#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram Account Manager with antidetect
Manage multiple accounts with different fingerprints and proxies

Usage:
  python instagram_account_manager.py                    # interactive menu
  python instagram_account_manager.py --account user1   # open specific account
  python instagram_account_manager.py --list            # list accounts
  python instagram_account_manager.py --proxy           # with proxy
"""

import os
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import json
import random
import asyncio
import argparse
import hashlib
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright

# Импорт ProxyManager из существующего кода
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instagram_downloader import ProxyManager, HAS_SOCKS

# Попытка импорта stealth
try:
    from playwright_stealth import Stealth
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    Stealth = None


class FingerprintGenerator:
    """Генератор уникальных fingerprints для каждого аккаунта"""

    USER_AGENTS = [
        # Windows Chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        # Windows Edge
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        # Mac Chrome
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        # Mac Safari
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    VIEWPORTS = [
        {"width": 1920, "height": 1080},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1366, "height": 768},
        {"width": 1280, "height": 720},
        {"width": 1680, "height": 1050},
        {"width": 2560, "height": 1440},
    ]

    TIMEZONES = [
        "Europe/Moscow",
        "Europe/Kiev",
        "Europe/Minsk",
        "Europe/London",
        "Europe/Berlin",
        "America/New_York",
        "America/Los_Angeles",
        "Asia/Tokyo",
    ]

    LOCALES = [
        "ru-RU",
        "en-US",
        "en-GB",
        "uk-UA",
        "de-DE",
    ]

    WEBGL_VENDORS = [
        "Google Inc. (NVIDIA)",
        "Google Inc. (Intel)",
        "Google Inc. (AMD)",
        "Intel Inc.",
        "NVIDIA Corporation",
    ]

    WEBGL_RENDERERS = [
        "ANGLE (NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0)",
    ]

    @classmethod
    def generate(cls, seed: str) -> dict:
        """Генерирует детерминированный fingerprint на основе seed"""
        # Используем seed для генерации одинакового fingerprint для одного аккаунта
        rng = random.Random(seed)

        return {
            "user_agent": rng.choice(cls.USER_AGENTS),
            "viewport": rng.choice(cls.VIEWPORTS),
            "timezone_id": rng.choice(cls.TIMEZONES),
            "locale": rng.choice(cls.LOCALES),
            "webgl_vendor": rng.choice(cls.WEBGL_VENDORS),
            "webgl_renderer": rng.choice(cls.WEBGL_RENDERERS),
            "color_depth": rng.choice([24, 32]),
            "device_memory": rng.choice([4, 8, 16, 32]),
            "hardware_concurrency": rng.choice([4, 6, 8, 12, 16]),
        }


class AccountManager:
    """Менеджер Instagram аккаунтов"""

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir or os.path.dirname(os.path.dirname(__file__)))
        self.profiles_dir = self.base_dir / "profiles"
        self.accounts_file = self.base_dir / "accounts.txt"
        self.config_file = self.base_dir / "accounts_config.json"

        self.profiles_dir.mkdir(exist_ok=True)
        self.accounts = []
        self.config = {}
        self.proxy_manager = None

    def load_accounts(self) -> list:
        """Загрузить аккаунты из файла"""
        if not self.accounts_file.exists():
            print(f"Создайте файл {self.accounts_file} с аккаунтами")
            print("Формат: login:password:mail:mail_password")
            return []

        accounts = []
        with open(self.accounts_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split(':')
                if len(parts) >= 2:
                    account = {
                        'login': parts[0],
                        'password': parts[1],
                        'mail': parts[2] if len(parts) > 2 else None,
                        'mail_password': parts[3] if len(parts) > 3 else None,
                    }
                    accounts.append(account)

        self.accounts = accounts
        print(f"Загружено {len(accounts)} аккаунтов")
        return accounts

    def load_config(self):
        """Загрузить конфигурацию (fingerprints, прокси назначения)"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {}

    def save_config(self):
        """Сохранить конфигурацию"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def get_account_config(self, login: str) -> dict:
        """Получить или создать конфиг для аккаунта"""
        if login not in self.config:
            # Генерируем уникальный fingerprint
            seed = hashlib.md5(login.encode()).hexdigest()
            fingerprint = FingerprintGenerator.generate(seed)

            self.config[login] = {
                'fingerprint': fingerprint,
                'proxy': None,
                'created': datetime.now().isoformat(),
                'last_used': None,
            }
            self.save_config()

        return self.config[login]

    def get_profile_dir(self, login: str) -> Path:
        """Путь к папке профиля"""
        # Хешируем логин для безопасности
        safe_name = hashlib.md5(login.encode()).hexdigest()[:12]
        return self.profiles_dir / safe_name

    def check_session(self, login: str) -> bool:
        """Проверить есть ли сохранённая сессия"""
        profile_dir = self.get_profile_dir(login)
        # Проверяем наличие cookies
        state_file = profile_dir / "state.json"
        return state_file.exists()

    async def setup_proxy(self, use_proxy: bool = False):
        """Настроить прокси"""
        if not use_proxy:
            return

        if not HAS_SOCKS:
            print("Установите: pip install aiohttp-socks")
            return

        self.proxy_manager = ProxyManager()
        await self.proxy_manager.fetch_proxies()
        await self.proxy_manager.test_proxies(limit=15)

        if not self.proxy_manager.working_proxies:
            print("Нет рабочих прокси")
            self.proxy_manager = None

    def assign_proxies(self):
        """Назначить прокси аккаунтам (по кругу)"""
        if not self.proxy_manager or not self.proxy_manager.working_proxies:
            return

        proxies = self.proxy_manager.working_proxies
        for i, account in enumerate(self.accounts):
            login = account['login']
            config = self.get_account_config(login)
            config['proxy'] = proxies[i % len(proxies)]

        self.save_config()
        print(f"Назначено {len(proxies)} прокси на {len(self.accounts)} аккаунтов")

    async def open_account(self, login: str, password: str = None):
        """Открыть браузер для аккаунта"""
        config = self.get_account_config(login)
        fingerprint = config['fingerprint']
        profile_dir = self.get_profile_dir(login)
        profile_dir.mkdir(exist_ok=True)

        proxy = config.get('proxy')

        print(f"\n{'='*50}")
        print(f"Аккаунт: {login}")
        print(f"User-Agent: {fingerprint['user_agent'][:50]}...")
        print(f"Viewport: {fingerprint['viewport']['width']}x{fingerprint['viewport']['height']}")
        print(f"Timezone: {fingerprint['timezone_id']}")
        print(f"Locale: {fingerprint['locale']}")
        print(f"Proxy: {proxy or 'нет'}")
        print(f"Сессия: {'есть' if self.check_session(login) else 'новая'}")
        print(f"{'='*50}\n")

        async with async_playwright() as p:
            # Настройки запуска
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                f'--window-size={fingerprint["viewport"]["width"]},{fingerprint["viewport"]["height"]}',
            ]

            browser = await p.chromium.launch(
                headless=False,
                args=launch_args,
            )

            # Настройки контекста
            context_options = {
                'user_agent': fingerprint['user_agent'],
                'viewport': fingerprint['viewport'],
                'locale': fingerprint['locale'],
                'timezone_id': fingerprint['timezone_id'],
                'color_scheme': 'light',
                'device_scale_factor': 1,
                'is_mobile': False,
                'has_touch': False,
            }

            # Прокси
            if proxy:
                context_options['proxy'] = {'server': f'socks5://{proxy}'}

            # Загружаем сохранённую сессию если есть
            state_file = profile_dir / "state.json"
            if state_file.exists():
                context_options['storage_state'] = str(state_file)

            context = await browser.new_context(**context_options)

            # Применяем stealth если установлен
            page = await context.new_page()

            if HAS_STEALTH and Stealth:
                stealth = Stealth(
                    webgl_vendor_override=fingerprint["webgl_vendor"],
                    webgl_renderer_override=fingerprint["webgl_renderer"],
                )
                await stealth.apply_stealth_async(page)

            # Инъекция скриптов для маскировки
            await self._inject_antidetect_scripts(page, fingerprint)

            # Переходим на Instagram
            print("Opening Instagram...")
            await page.goto('https://www.instagram.com/', wait_until='domcontentloaded')
            await asyncio.sleep(3)

            # Закрываем cookies popup если есть
            await self._handle_cookies_popup(page)

            # Проверяем нужен ли логин
            if password:
                # Проверяем есть ли форма логина
                login_form = await page.query_selector('input[name="username"]')
                if login_form:
                    print("Login form found, logging in...")
                    await self._do_login(page, login, password)
                else:
                    print("Already logged in or no login form")

            # Обновляем last_used
            config['last_used'] = datetime.now().isoformat()
            self.save_config()

            print("\nБраузер открыт. Закройте окно когда закончите.")
            print("Сессия будет сохранена автоматически.\n")

            # Ждём пока пользователь закроет браузер
            try:
                while True:
                    await asyncio.sleep(1)
                    # Проверяем что браузер ещё открыт
                    try:
                        await page.title()
                    except:
                        break
            except:
                pass

            # Сохраняем сессию
            try:
                await context.storage_state(path=str(state_file))
                print(f"Сессия сохранена: {state_file}")
            except:
                pass

            await browser.close()

    async def _inject_antidetect_scripts(self, page, fingerprint: dict):
        """Инъекция скриптов для маскировки браузера"""

        # Скрываем webdriver
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Подменяем WebGL
        await page.add_init_script(f"""
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) {{
                    return '{fingerprint["webgl_vendor"]}';
                }}
                if (parameter === 37446) {{
                    return '{fingerprint["webgl_renderer"]}';
                }}
                return getParameter.call(this, parameter);
            }};
        """)

        # Подменяем hardware concurrency
        await page.add_init_script(f"""
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {fingerprint['hardware_concurrency']}
            }});
        """)

        # Подменяем device memory
        await page.add_init_script(f"""
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {fingerprint['device_memory']}
            }});
        """)

        # Скрываем автоматизацию
        await page.add_init_script("""
            // Убираем признаки Playwright/Puppeteer
            delete window.__playwright;
            delete window.__pw_manual;

            // Нормальные permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Chrome runtime
            window.chrome = {
                runtime: {},
            };

            // Languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ru-RU', 'ru', 'en-US', 'en']
            });

            // Plugins (не пустой массив)
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)

    async def _handle_cookies_popup(self, page):
        """Handle Instagram cookies consent popup"""
        try:
            # Look for "Allow all cookies" or similar buttons
            selectors = [
                'button:has-text("Allow all cookies")',
                'button:has-text("Allow essential and optional cookies")',
                'button:has-text("Decline optional cookies")',
                'button:has-text("Accept")',
                'button:has-text("Accept All")',
                '[role="dialog"] button:first-of-type',
            ]
            for selector in selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn:
                        await btn.click()
                        print("Cookies popup closed")
                        await asyncio.sleep(1)
                        return
                except:
                    continue
        except:
            pass

    async def _do_login(self, page, login: str, password: str):
        """Perform login"""
        try:
            print(f"Logging in as: {login}")

            # Wait for login form
            await page.wait_for_selector('input[name="username"]', timeout=10000)
            await asyncio.sleep(random.uniform(1, 2))

            # Enter username
            print("Entering username...")
            username_input = await page.query_selector('input[name="username"]')
            await username_input.click()
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # Clear field first
            await username_input.fill('')
            await asyncio.sleep(0.2)

            # Type character by character
            for char in login:
                await page.keyboard.type(char, delay=random.randint(50, 150))

            print("Username entered")
            await asyncio.sleep(random.uniform(0.5, 1))

            # Enter password
            print("Entering password...")
            password_input = await page.query_selector('input[name="password"]')
            await password_input.click()
            await asyncio.sleep(random.uniform(0.3, 0.7))

            for char in password:
                await page.keyboard.type(char, delay=random.randint(50, 150))

            print("Password entered")
            await asyncio.sleep(random.uniform(0.5, 1))

            # Click login button
            print("Clicking login button...")
            login_button = await page.query_selector('button[type="submit"]')
            if login_button:
                await login_button.click()
            else:
                # Try pressing Enter
                await page.keyboard.press('Enter')

            print("Waiting for login result...")
            await asyncio.sleep(5)

            # Check for 2FA or errors
            current_url = page.url
            if 'challenge' in current_url or 'two_factor' in current_url:
                print("WARNING: 2FA required - enter code manually")
            elif 'login' not in current_url:
                print("Login successful!")
            else:
                print("Still on login page - check for errors manually")

        except Exception as e:
            print(f"Login error: {e}")
            print("Please login manually in the browser")

    def list_accounts(self):
        """Показать список аккаунтов"""
        print("\n" + "="*60)
        print("АККАУНТЫ")
        print("="*60)

        for i, account in enumerate(self.accounts, 1):
            login = account['login']
            has_session = "✓" if self.check_session(login) else "✗"

            config = self.config.get(login, {})
            last_used = config.get('last_used', 'никогда')
            if last_used != 'никогда':
                last_used = last_used[:10]  # Только дата

            proxy = config.get('proxy', 'нет')
            if proxy and proxy != 'нет':
                proxy = proxy[:20] + "..."

            print(f"{i:2}. [{has_session}] {login:20} | Прокси: {proxy:25} | Использован: {last_used}")

        print("="*60)
        print("✓ = сессия сохранена, ✗ = требуется логин")
        print()


async def interactive_menu(manager: AccountManager):
    """Интерактивное меню"""
    while True:
        print("\n" + "="*40)
        print("INSTAGRAM ACCOUNT MANAGER")
        print("="*40)
        print("1. Открыть аккаунт")
        print("2. Список аккаунтов")
        print("3. Обновить прокси")
        print("4. Переназначить прокси")
        print("0. Выход")
        print("-"*40)

        choice = input("Выбор: ").strip()

        if choice == '0':
            break
        elif choice == '1':
            manager.list_accounts()
            try:
                idx = int(input("Номер аккаунта: ")) - 1
                if 0 <= idx < len(manager.accounts):
                    account = manager.accounts[idx]
                    await manager.open_account(account['login'], account['password'])
                else:
                    print("Неверный номер")
            except ValueError:
                print("Введите число")
        elif choice == '2':
            manager.list_accounts()
        elif choice == '3':
            await manager.setup_proxy(use_proxy=True)
        elif choice == '4':
            if manager.proxy_manager:
                manager.assign_proxies()
            else:
                print("Сначала загрузите прокси (пункт 3)")


async def main():
    parser = argparse.ArgumentParser(description='Instagram Account Manager')
    parser.add_argument('--account', '-a', help='Открыть конкретный аккаунт по логину')
    parser.add_argument('--list', '-l', action='store_true', help='Показать список аккаунтов')
    parser.add_argument('--proxy', '-p', action='store_true', help='Использовать прокси')
    parser.add_argument('--assign-proxies', action='store_true', help='Назначить прокси аккаунтам')

    args = parser.parse_args()

    manager = AccountManager()
    manager.load_accounts()
    manager.load_config()

    if not manager.accounts:
        print(f"\nСоздайте файл: {manager.accounts_file}")
        print("Формат строки: login:password:mail:mail_password")
        print("Пример:")
        print("  myaccount:mypass123:myemail@gmail.com:emailpass")
        return

    # Загружаем прокси если нужно
    if args.proxy:
        await manager.setup_proxy(use_proxy=True)
        if args.assign_proxies:
            manager.assign_proxies()

    if args.list:
        manager.list_accounts()
    elif args.account:
        # Ищем аккаунт по логину
        account = next((a for a in manager.accounts if a['login'] == args.account), None)
        if account:
            await manager.open_account(account['login'], account['password'])
        else:
            print(f"Аккаунт {args.account} не найден")
            manager.list_accounts()
    else:
        # Интерактивное меню
        await interactive_menu(manager)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nВыход")

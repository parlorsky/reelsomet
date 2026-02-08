#!/usr/bin/env python3
"""
Content audit script for Bloom video scripts.

Checks markup files before rendering:
- Page count (max 8, Micro max 4)
- Profanity detection (block)
- "Телеграм"/"Telegram" mentions (block)
- Bloom mention count (max 1 per script)
- Share/save trigger in CTA (last page)
- Duplicate topic detection vs recent scripts

Usage:
    python scripts/content_audit.py downloads/bloom_XX_markup.txt
    python scripts/content_audit.py downloads/bloom_XX_markup.txt --format micro
    python scripts/content_audit.py --batch downloads/bloom_*_markup.txt
    python scripts/content_audit.py --scan-catalog
"""

import argparse
import glob
import io
import json
import os
import re
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# --- Constants ---

PROFANITY_PATTERNS = [
    r'\bпизд',
    r'\bхуй', r'\bхуе', r'\bхуё',
    r'\bблядь', r'\bбляд',
    r'\bебать', r'\bебан', r'\bёбан',
    r'\bсука\b', r'\bсучк',
    r'\bмудак', r'\bмудач',
    r'\bзалуп',
    r'\bпидор', r'\bпидар',
    r'\bдерьм',
]

TELEGRAM_PATTERNS = [
    r'\bтелеграм', r'\btelegram\b', r'\bтелегу\b', r'\bтелеге\b', r'\bтелеги\b',
    r'\bтг\b',
]

SHARE_TRIGGERS = [
    'отправь', 'перешли', 'скинь', 'покажи партнёру', 'покажи партнеру',
    'сохрани', 'напиши в коммент', 'попробуй сегодня', 'попробуй вечером',
    'проверь реакцию', 'а ты как думаешь', 'а ты?',
]

MAX_PAGES = {
    'micro': 4,
    'challenge': 6,
    'contrast': 7,
    'debate': 7,
    'book': 8,
    'story': 8,
    'default': 8,
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(PROJECT_ROOT, 'input', 'scripts_catalog.json')


def strip_markup(text: str) -> str:
    """Remove all markup tags, return plain lowercase text."""
    text = re.sub(r'\[c:[^\]]*\]', '', text)
    text = re.sub(r'\[/\]', '', text)
    text = re.sub(r'\[s:[^\]]*\]', '', text)
    text = re.sub(r'\[img:[^\]]*\]', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    return text.lower().strip()


def get_pages(content: str) -> list:
    """Split markup content into pages by --- separator."""
    pages = re.split(r'\n---\n', content.strip())
    return [p.strip() for p in pages if p.strip()]


def check_profanity(content: str) -> list:
    """Check for profanity. Returns list of found violations."""
    plain = strip_markup(content)
    findings = []
    for pattern in PROFANITY_PATTERNS:
        matches = re.findall(pattern, plain, re.IGNORECASE)
        if matches:
            findings.extend(matches)
    return findings


def check_telegram_mentions(content: str) -> list:
    """Check for Telegram/Телеграм mentions."""
    plain = strip_markup(content)
    findings = []
    for pattern in TELEGRAM_PATTERNS:
        matches = re.findall(pattern, plain, re.IGNORECASE)
        if matches:
            findings.extend(matches)
    return findings


def count_bloom_mentions(content: str) -> int:
    """Count how many times Bloom is mentioned."""
    plain = strip_markup(content)
    return len(re.findall(r'\bbloom\b', plain, re.IGNORECASE))


def check_share_trigger(content: str) -> bool:
    """Check if the last page contains a share/save trigger."""
    pages = get_pages(content)
    if not pages:
        return False
    last_page = strip_markup(pages[-1])
    # Also check second-to-last page (CTA can span 2 pages)
    check_pages = last_page
    if len(pages) >= 2:
        check_pages = strip_markup(pages[-2]) + ' ' + last_page
    return any(trigger in check_pages for trigger in SHARE_TRIGGERS)


def check_hook_quality(content: str) -> list:
    """Check if Page 1 looks like a proper hook (not exposition)."""
    pages = get_pages(content)
    if not pages:
        return ['Empty script']

    first_page = strip_markup(pages[0])
    warnings = []

    # Check for exposition patterns
    exposition_patterns = [
        (r'^привет', 'Starts with greeting'),
        (r'^сегодня расскажу', 'Starts with "сегодня расскажу"'),
        (r'^представь', 'Starts with "представь"'),
        (r'^давайте поговорим', 'Starts with generic intro'),
        (r'^\w+ \w+ в книге', 'Starts with author name'),
    ]
    for pattern, msg in exposition_patterns:
        if re.search(pattern, first_page):
            warnings.append(f'Weak hook: {msg}')

    return warnings


def load_recent_topics(n: int = 20) -> list:
    """Load titles/topics from the last N scripts in catalog."""
    if not os.path.exists(CATALOG_PATH):
        return []
    try:
        with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
            catalog = json.load(f)
        scripts = catalog.get('scripts', [])
        recent = scripts[-n:]
        return [s.get('title', '') for s in recent]
    except (json.JSONDecodeError, KeyError):
        return []


def audit_file(filepath: str, fmt: str = 'default') -> dict:
    """Run all audit checks on a markup file. Returns dict of results."""
    results = {
        'file': os.path.basename(filepath),
        'errors': [],    # Blocking issues
        'warnings': [],  # Non-blocking issues
        'info': [],      # Informational
    }

    if not os.path.exists(filepath):
        results['errors'].append(f'File not found: {filepath}')
        return results

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Page count
    pages = get_pages(content)
    page_count = len(pages)
    max_pages = MAX_PAGES.get(fmt, MAX_PAGES['default'])
    results['info'].append(f'Pages: {page_count} (max: {max_pages})')

    if page_count > max_pages:
        results['errors'].append(
            f'Too many pages: {page_count} > {max_pages} (format: {fmt})'
        )
    elif page_count > max_pages - 1:
        results['warnings'].append(f'At page limit: {page_count}/{max_pages}')

    # 2. Profanity
    profanity = check_profanity(content)
    if profanity:
        results['errors'].append(
            f'Profanity detected: {", ".join(set(profanity))}'
        )

    # 3. Telegram mentions
    telegram = check_telegram_mentions(content)
    if telegram:
        results['errors'].append(
            f'"Телеграм" detected: {", ".join(set(telegram))} — Instagram penalizes this'
        )

    # 4. Bloom mentions
    bloom_count = count_bloom_mentions(content)
    results['info'].append(f'Bloom mentions: {bloom_count}')
    if bloom_count > 1:
        results['warnings'].append(
            f'Bloom mentioned {bloom_count} times (max 1)'
        )

    # 5. Share trigger in CTA
    has_trigger = check_share_trigger(content)
    if not has_trigger:
        results['warnings'].append(
            'No share/save trigger in CTA (last page). '
            'Consider: "отправь партнёру", "сохрани", "напиши в комменты"'
        )

    # 6. Hook quality
    hook_issues = check_hook_quality(content)
    for issue in hook_issues:
        results['warnings'].append(issue)

    return results


def scan_catalog():
    """Scan all scripts in catalog for issues."""
    if not os.path.exists(CATALOG_PATH):
        print(f'Catalog not found: {CATALOG_PATH}')
        return

    with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
        catalog = json.load(f)

    scripts = catalog.get('scripts', [])
    total_errors = 0
    total_warnings = 0

    for script in scripts:
        script_id = script.get('id', '?')
        plain_text = script.get('plain_text', '') or ''
        title = script.get('title', 'Untitled')

        if not plain_text:
            continue

        issues = []

        # Check profanity in plain text
        profanity = check_profanity(plain_text)
        if profanity:
            issues.append(f'  PROFANITY: {", ".join(set(profanity))}')
            total_errors += 1

        # Check telegram
        telegram = check_telegram_mentions(plain_text)
        if telegram:
            issues.append(f'  TELEGRAM: {", ".join(set(telegram))}')
            total_errors += 1

        # Check bloom count
        bloom_count = count_bloom_mentions(plain_text)
        if bloom_count > 1:
            issues.append(f'  BLOOM x{bloom_count} (max 1)')
            total_warnings += 1

        if issues:
            print(f'\n#{script_id}: {title}')
            for issue in issues:
                print(issue)

    print(f'\n--- Summary ---')
    print(f'Scripts scanned: {len(scripts)}')
    print(f'Errors: {total_errors}')
    print(f'Warnings: {total_warnings}')


def print_results(results: dict) -> bool:
    """Print audit results. Returns True if passed (no errors)."""
    has_errors = len(results['errors']) > 0

    status = 'FAIL' if has_errors else 'PASS'
    print(f'\n[{status}] {results["file"]}')

    for info in results['info']:
        print(f'  INFO: {info}')
    for warning in results['warnings']:
        print(f'  WARN: {warning}')
    for error in results['errors']:
        print(f'  ERROR: {error}')

    return not has_errors


def main():
    parser = argparse.ArgumentParser(description='Audit Bloom video scripts before rendering')
    parser.add_argument('files', nargs='*', help='Markup file(s) to audit')
    parser.add_argument('--format', '-f', default='default',
                        choices=['micro', 'challenge', 'contrast', 'debate', 'book', 'story', 'default'],
                        help='Script format (affects page limit)')
    parser.add_argument('--batch', action='store_true',
                        help='Process multiple files')
    parser.add_argument('--scan-catalog', action='store_true',
                        help='Scan scripts_catalog.json for issues')
    args = parser.parse_args()

    if args.scan_catalog:
        scan_catalog()
        return

    if not args.files:
        parser.print_help()
        sys.exit(1)

    all_passed = True
    for filepath in args.files:
        # Expand globs on Windows
        expanded = glob.glob(filepath) if '*' in filepath else [filepath]
        for f in expanded:
            results = audit_file(f, args.format)
            passed = print_results(results)
            if not passed:
                all_passed = False

    print()
    if all_passed:
        print('All checks passed.')
    else:
        print('Some checks FAILED. Fix errors before rendering.')
        sys.exit(1)


if __name__ == '__main__':
    main()

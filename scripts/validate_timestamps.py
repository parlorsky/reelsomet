"""
Validate script words against TTS timestamps.
Finds mismatches that would cause subtitles to disappear.

Usage:
    python scripts/validate_timestamps.py input/script.txt downloads/audio_timestamps.json
"""

import sys
import os
import re
import json
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def parse_script_words(script_path: str) -> list:
    """Extract words from styled script, preserving order."""
    with open(script_path, 'r', encoding='utf-8') as f:
        text = f.read()

    words = []

    # Split by page breaks
    parts = re.split(r'\n*---\n*', text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Pattern to match styled segments
        pattern = r'''
            (\*\*[^*]+\*\*)           |  # **accent**
            (\*[^*]+\*)               |  # *highlight*
            (_[^_]+_)                 |  # _muted_
            (\[[^\]]+\][^\[]+\[/\])   |  # [style]word[/]
            (\S+)                        # plain word
        '''

        tokens = re.findall(pattern, part, re.VERBOSE)

        for token_tuple in tokens:
            token = next(t for t in token_tuple if t)

            # Extract inner text
            if token.startswith('**') and token.endswith('**'):
                inner = token[2:-2].strip()
            elif token.startswith('*') and token.endswith('*'):
                inner = token[1:-1].strip()
            elif token.startswith('_') and token.endswith('_'):
                inner = token[1:-1].strip()
            elif token.startswith('[') and token.endswith('[/]'):
                match = re.match(r'\[([^\]]+)\](.+)\[/\]', token)
                if match:
                    inner = match.group(2).strip()
                else:
                    inner = token
            else:
                inner = token.strip()

            if inner:
                words.append(inner)

    return words


def clean_word(word: str) -> str:
    """Clean word for comparison (lowercase, alphanumeric, ё→е)."""
    word = word.lower().replace('ё', 'е')
    return ''.join(c for c in word if c.isalnum())


def validate_matching(script_words: list, timestamps: list) -> list:
    """
    Simulate the matching algorithm and find mismatches.
    Returns list of issues.
    """
    issues = []
    ts_idx = 0

    for word_idx, script_word in enumerate(script_words):
        script_clean = clean_word(script_word)
        if not script_clean:
            continue

        start_ts_idx = ts_idx
        found = False

        while ts_idx < len(timestamps):
            ts = timestamps[ts_idx]
            ts_clean = clean_word(ts['word'])

            # Check for match (exact or partial)
            if script_clean == ts_clean or script_clean in ts_clean or ts_clean in script_clean:
                found = True
                ts_idx += 1
                break
            else:
                ts_idx += 1

        if not found:
            # This word didn't match - all subsequent words will fail
            issues.append({
                'word_idx': word_idx,
                'script_word': script_word,
                'script_clean': script_clean,
                'skipped_from': start_ts_idx,
                'skipped_count': ts_idx - start_ts_idx,
                'nearby_ts': [
                    timestamps[i]['word']
                    for i in range(max(0, start_ts_idx - 2), min(len(timestamps), start_ts_idx + 5))
                ]
            })
            # Reset to try next word from where we left off
            # Actually in the real algorithm, once ts_idx reaches end, all subsequent words fail
            break

    return issues


def suggest_fix(issue: dict) -> str:
    """Suggest a fix for a mismatch."""
    script_word = issue['script_word']
    nearby = issue['nearby_ts']

    # Look for similar word in nearby timestamps
    script_clean = issue['script_clean']

    for ts_word in nearby:
        ts_clean = clean_word(ts_word)
        # Check if it's a number vs written form mismatch
        if script_clean.isdigit() and not ts_clean.isdigit():
            return f"Change \"{script_word}\" to \"{ts_word}\" (number vs text)"
        if script_clean and ts_clean:
            # Check for similar words (different spelling)
            if script_clean[:3] == ts_clean[:3] or ts_clean[:3] == script_clean[:3]:
                return f"Change \"{script_word}\" to \"{ts_word}\" (spelling mismatch)"

    return f"Check TTS pronunciation. Nearby words: {nearby}"


def main():
    if len(sys.argv) < 3:
        print("Usage: python validate_timestamps.py <script.txt> <timestamps.json>")
        print("\nValidates script against TTS timestamps to find mismatches.")
        sys.exit(1)

    script_path = sys.argv[1]
    timestamps_path = sys.argv[2]

    # Load data
    print(f"Script: {script_path}")
    print(f"Timestamps: {timestamps_path}")

    script_words = parse_script_words(script_path)
    print(f"Script words: {len(script_words)}")

    with open(timestamps_path, 'r', encoding='utf-8') as f:
        timestamps = json.load(f)
    print(f"Timestamp words: {len(timestamps)}")

    # Validate
    print("\n" + "="*60)
    print("VALIDATION RESULTS")
    print("="*60)

    issues = validate_matching(script_words, timestamps)

    if not issues:
        print("\n✓ All words match! No issues found.")
        return 0

    print(f"\n✗ Found {len(issues)} issue(s):\n")

    for issue in issues:
        print(f"Word #{issue['word_idx']}: \"{issue['script_word']}\"")
        print(f"  Cleaned: \"{issue['script_clean']}\"")
        print(f"  Skipped {issue['skipped_count']} timestamps from index {issue['skipped_from']}")
        print(f"  Nearby TTS words: {issue['nearby_ts']}")
        print(f"  → Suggestion: {suggest_fix(issue)}")
        print()

    print("="*60)
    print("After fixing, re-run validation to check for more issues.")
    print("="*60)

    return 1


if __name__ == '__main__':
    sys.exit(main())

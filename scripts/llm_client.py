"""
LLM API Client for Bloom video pipeline.

Sends prompts to local LLM server with scope-based system prompts.
Scopes map to directories with system prompt files on the server.
"""

import json
import re
import httpx

LLM_URL = "http://localhost:8000/api/chat"
LLM_API_KEY = "olegus123456"

SCOPES = {
    "ideas": r"C:\Users\olegus\Desktop\idea_generator",
    "scripts": r"C:\Users\olegus\Desktop\script_generator",
    "general": r"C:\Users\olegus\Desktop\general_use",
}


async def chat(prompt: str, scope: str = "general", timeout: float = 180) -> str:
    """Send prompt to LLM, return response text.

    Args:
        prompt: The user prompt to send.
        scope: Scope key ("ideas", "scripts", "general") or a direct path.
        timeout: Request timeout in seconds.

    Returns:
        Raw response text from the LLM.
    """
    resolved_scope = SCOPES.get(scope, scope)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            LLM_URL,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": LLM_API_KEY,
            },
            json={
                "prompt": prompt,
                "scope": resolved_scope,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        # Try common response keys
        for key in ("result", "response", "message", "text", "content", "reply"):
            if key in data:
                return data[key]
        # Fallback: return full JSON as string
        return json.dumps(data, ensure_ascii=False)


async def chat_json(prompt: str, scope: str = "general", timeout: float = 180) -> dict | list:
    """Send prompt to LLM, parse response as JSON.

    Handles common LLM quirks:
    - Strips markdown code fences (```json ... ```)
    - Strips leading/trailing text around JSON

    Args:
        prompt: The user prompt.
        scope: Scope key or path.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON (dict or list).

    Raises:
        json.JSONDecodeError: If response is not valid JSON.
    """
    text = await chat(prompt, scope, timeout)
    return parse_json_response(text)


def parse_json_response(text: str) -> dict | list:
    """Extract and parse JSON from LLM response text.

    Handles:
    - Clean JSON
    - ```json ... ``` fences (even unclosed)
    - Text before/after JSON
    - Truncated JSON (attempts repair)
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences (handles unclosed fences too)
    if text.startswith("```"):
        first_nl = text.find('\n')
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    elif "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Try to find JSON object or array in text
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    # Attempt to repair truncated JSON
    for start_char in ("[", "{"):
        idx = text.find(start_char)
        if idx != -1:
            fragment = text[idx:]
            repaired = _repair_truncated_json(fragment)
            if repaired is not None:
                return repaired

    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response: {text[:200]}...", text, 0
    )


def _repair_truncated_json(text: str):
    """Try to repair truncated JSON by closing open brackets/braces."""
    # Count unclosed brackets
    # Walk backwards, trimming to the last complete value
    # Then close any open brackets/braces
    for trim in range(min(len(text), 500)):
        candidate = text if trim == 0 else text[:-(trim)]
        # Trim to last complete key-value: find last comma or opening bracket
        candidate = candidate.rstrip()
        if not candidate:
            continue
        # Remove trailing comma
        if candidate.endswith(','):
            candidate = candidate[:-1]
        # Remove incomplete string (trailing unclosed quote)
        if candidate.count('"') % 2 != 0:
            last_q = candidate.rfind('"')
            candidate = candidate[:last_q] + '"'
        # Count open brackets
        opens = []
        in_str = False
        esc = False
        for ch in candidate:
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in ('{', '['):
                opens.append(ch)
            elif ch in ('}', ']'):
                if opens:
                    opens.pop()
        # Close remaining brackets in reverse
        closers = {'[': ']', '{': '}'}
        suffix = ''.join(closers[b] for b in reversed(opens))
        try:
            result = json.loads(candidate + suffix)
            return result
        except json.JSONDecodeError:
            continue
    return None

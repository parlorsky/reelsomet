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
        for key in ("response", "message", "text", "content", "reply"):
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
    - ```json ... ``` fences
    - Text before/after JSON
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences
    if "```" in text:
        # Find content between first ``` and last ```
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

    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response: {text[:200]}...", text, 0
    )

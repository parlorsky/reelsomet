"""
KIE.ai ElevenLabs TTS - Text to Speech (Turbo 2.5)
Озвучка текста с эмоциями.

Использование:
    python scripts/kie_tts.py "Текст для озвучки" -o output.mp3
    python scripts/kie_tts.py script.txt -v Callum -o voiceover.mp3
    python scripts/kie_tts.py --voices  # list voices
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv(Path(__file__).parent.parent / ".env")

KIE_API_KEY = "177a707a756ba7a3e57555a10400c245"
BASE_URL = "https://api.kie.ai/api/v1/jobs"
MODEL = "elevenlabs/text-to-speech-turbo-2-5"

# Voice presets accepted by the turbo-2-5 model (name → name or ID)
# Preset names are sent as-is; you can also pass raw ElevenLabs voice IDs
VOICES = {
    "Callum": "Callum",
    "Rachel": "Rachel",
    "Aria": "Aria",
    "Roger": "Roger",
    "Sarah": "Sarah",
    "Laura": "Laura",
    "Charlie": "Charlie",
    "George": "George",
    "River": "River",
    "Liam": "Liam",
    "Charlotte": "Charlotte",
    "Alice": "Alice",
    "Matilda": "Matilda",
    "Will": "Will",
    "Jessica": "Jessica",
    "Eric": "Eric",
    "Chris": "Chris",
    "Brian": "Brian",
    "Daniel": "Daniel",
    "Lily": "Lily",
    "Bill": "Bill",
}

DEFAULT_VOICE = "EiNlNiXeDU1pqqOPrYMO"

# Emotion tags (supported by ElevenLabs V3/Turbo)
TAGS = "[whispers] [shouts] [sad] [happy] [sarcastic] [pause] [laughs] [sighs] [thoughtful] [excited] [calm]"


def resolve_voice(voice: str) -> str:
    """Resolve voice name to ID. If already an ID (long string), pass through."""
    if voice in VOICES:
        return VOICES[voice]
    # Check case-insensitive
    for name, vid in VOICES.items():
        if name.lower() == voice.lower():
            return vid
    # Assume it's a raw voice ID
    return voice


class KieTTS:
    """TTS client for KIE.ai (ElevenLabs Turbo 2.5)"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or KIE_API_KEY
        if not self.api_key:
            raise ValueError("KIE_API_KEY not set")

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    async def generate(
        self,
        text: str,
        voice: str = None,
        output_path: str = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0,
        speed: float = 1.0,
        language: str = "ru",
    ) -> str:
        """
        Generate speech from text.

        Args:
            text: Text to speak (max 5000 chars), can include emotion tags
            voice: Voice name (from VOICES) or ElevenLabs voice ID
            output_path: Where to save MP3
            stability: Voice stability 0-1
            similarity_boost: Similarity boost 0-1
            style: Style exaggeration 0-1
            speed: Speech speed multiplier
            language: Language code (ru, en, auto, etc.)

        Returns:
            Path to saved file or audio URL
        """
        if len(text) > 5000:
            raise ValueError(f"Text too long: {len(text)}/5000 chars")

        voice_id = resolve_voice(voice or DEFAULT_VOICE)

        payload = {
            "model": MODEL,
            "input": {
                "text": text,
                "voice": voice_id,
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "speed": speed,
                "timestamps": False,
                "language_code": language,
            }
        }

        max_retries = 3

        async with aiohttp.ClientSession() as session:
            # Create task (with retry)
            print(f"Creating task ({len(text)} chars, voice: {voice or DEFAULT_VOICE} → {voice_id})...")
            task_id = None
            for attempt in range(1, max_retries + 1):
                try:
                    async with session.post(
                        f"{BASE_URL}/createTask",
                        headers=self.headers,
                        json=payload
                    ) as resp:
                        if resp.status >= 500:
                            body = await resp.text()
                            raise Exception(f"Server error {resp.status}: {body[:200]}")
                        result = await resp.json()
                        if result.get("code") != 200:
                            raise Exception(f"API Error: {result.get('msg', result)}")
                        task_id = result["data"]["taskId"]
                        print(f"Task ID: {task_id}")
                        break
                except (aiohttp.ContentTypeError, aiohttp.ClientError, Exception) as e:
                    if attempt < max_retries:
                        wait = attempt * 5
                        print(f"  createTask attempt {attempt} failed: {e}. Retrying in {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        raise

            # Poll for result
            print("Waiting for generation...")
            consecutive_errors = 0
            for _ in range(150):  # 5 min timeout
                try:
                    async with session.get(
                        f"{BASE_URL}/recordInfo",
                        headers=self.headers,
                        params={"taskId": task_id}
                    ) as resp:
                        if resp.status >= 500:
                            raise aiohttp.ClientError(f"Server error {resp.status}")
                        result = await resp.json()
                        consecutive_errors = 0

                        data = result.get("data", {})
                        state = data.get("state")

                        if state == "success":
                            result_json = json.loads(data.get("resultJson", "{}"))
                            urls = result_json.get("resultUrls", [])
                            if not urls:
                                raise Exception("No audio URL in result")
                            audio_url = urls[0]
                            print(f"Done! URL: {audio_url}")

                            if output_path:
                                await self._download(session, audio_url, output_path)
                                return output_path
                            return audio_url

                        elif state == "fail":
                            fail_msg = data.get("failMsg", "")
                            print(f"  FAIL: {json.dumps(data, indent=2, ensure_ascii=False)}")
                            raise Exception(f"Generation failed: {fail_msg}")

                        print(f"  Status: {state or 'processing'}...")

                except (aiohttp.ContentTypeError, aiohttp.ClientError) as e:
                    consecutive_errors += 1
                    print(f"  Poll error ({consecutive_errors}): {e}")
                    if consecutive_errors >= 5:
                        raise Exception(f"Too many consecutive poll errors: {e}")

                await asyncio.sleep(2)

            raise TimeoutError("Timeout waiting for generation")

    async def _download(self, session, url: str, path: str):
        """Download audio file."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(path, "wb") as f:
                    f.write(await resp.read())
                print(f"Saved: {path}")
            else:
                raise Exception(f"Download failed: {resp.status}")


async def main():
    import argparse

    voice_list = ", ".join(f"{name} ({vid})" for name, vid in VOICES.items())

    parser = argparse.ArgumentParser(description="KIE.ai TTS - Text to Speech")
    parser.add_argument("text", nargs="?", help="Text or path to .txt file")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE, help=f"Voice name or ID. Known: {voice_list}")
    parser.add_argument("-o", "--output", default="downloads/voiceover.mp3", help="Output file")
    parser.add_argument("-s", "--stability", type=float, default=0.5, help="Stability 0-1")
    parser.add_argument("--similarity", type=float, default=0.75, help="Similarity boost 0-1")
    parser.add_argument("--style", type=float, default=0, help="Style exaggeration 0-1")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed multiplier")
    parser.add_argument("-l", "--lang", default="ru", help="Language code: ru, en, auto, etc.")
    parser.add_argument("--voices", action="store_true", help="List available voices")
    args = parser.parse_args()

    if args.voices:
        print("Available voices:")
        for name, vid in VOICES.items():
            print(f"  - {name} ({vid})")
        print(f"\nYou can also pass any ElevenLabs voice ID directly with -v")
        print(f"\nEmotion tags: {TAGS}")
        return

    if not args.text:
        print("Usage: python kie_tts.py \"Your text here\" -v Callum -o output.mp3")
        print("       python kie_tts.py script.txt -v Callum")
        print("\nUse --voices to see available voices")
        return

    # Read from file or use directly
    if os.path.isfile(args.text):
        with open(args.text, "r", encoding="utf-8") as f:
            text = f.read().strip()
        print(f"Read {len(text)} chars from {args.text}")
    else:
        text = args.text

    tts = KieTTS()
    result = await tts.generate(
        text=text,
        voice=args.voice,
        output_path=args.output,
        stability=args.stability,
        similarity_boost=args.similarity,
        style=args.style,
        speed=args.speed,
        language=args.lang,
    )

    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())

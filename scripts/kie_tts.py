"""
KIE.ai ElevenLabs V3 TTS - Monologue
Озвучка текста одним голосом с эмоциями.

Использование:
    python scripts/kie_tts.py "Текст для озвучки" -v Jessica -o output.mp3
    python scripts/kie_tts.py script.txt -v Liam -o voiceover.mp3

Требует KIE_API_KEY в .env
"""

import os
import sys
import time
import json
import asyncio
import aiohttp
from pathlib import Path
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv(Path(__file__).parent.parent / ".env")

KIE_API_KEY = "08bd3e0cda8f5c950ff4b98d95b80218"
BASE_URL = "https://api.kie.ai/api/v1/jobs"
MODEL = "elevenlabs/text-to-dialogue-v3"

# Available voices
VOICES = [
    "Adam", "Alice", "Bill", "Brian", "Callum", "Charlie", "Chris",
    "Daniel", "Eric", "George", "Harry", "Jessica", "Laura", "Liam",
    "Lily", "Matilda", "River", "Roger", "Sarah", "Will"
]

# Emotion tags
TAGS = "[whispers] [shouts] [sad] [happy] [sarcastic] [pause] [laughs] [sighs] [thoughtful] [excited] [calm]"


class KieTTS:
    """Simple TTS client for KIE.ai"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or KIE_API_KEY
        if not self.api_key:
            raise ValueError("KIE_API_KEY not found in .env")

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    async def generate(
        self,
        text: str,
        voice: str = "Jessica",
        output_path: str = None,
        stability: float = 0.5,
        language: str = "auto"
    ) -> str:
        """
        Generate speech from text.

        Args:
            text: Text to speak (max 5000 chars), can include emotion tags
            voice: Voice name (see VOICES)
            output_path: Where to save MP3
            stability: Voice stability 0-1
            language: Language code (auto, en, ru, etc.)

        Returns:
            Path to saved file or audio URL
        """
        if len(text) > 5000:
            raise ValueError(f"Text too long: {len(text)}/5000 chars")

        if voice not in VOICES:
            raise ValueError(f"Unknown voice: {voice}. Available: {', '.join(VOICES)}")

        # Single speaker dialogue
        dialogue = [{"text": text, "voice": voice}]

        payload = {
            "model": MODEL,
            "input": {
                "stability": stability,
                "language_code": language,
                "dialogue": dialogue
            }
        }

        async with aiohttp.ClientSession() as session:
            # Create task
            print(f"Creating task ({len(text)} chars, voice: {voice})...")
            async with session.post(
                f"{BASE_URL}/createTask",
                headers=self.headers,
                json=payload
            ) as resp:
                result = await resp.json()
                print(f"API Response: {json.dumps(result, indent=2)}")
                if result.get("code") != 200:
                    raise Exception(f"API Error: {result}")
                task_id = result["data"]["taskId"]
                print(f"Task ID: {task_id}")

            # Poll for result
            print("Waiting for generation...")
            for _ in range(150):  # 5 min timeout
                async with session.get(
                    f"{BASE_URL}/recordInfo",
                    headers=self.headers,
                    params={"taskId": task_id}
                ) as resp:
                    result = await resp.json()
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
                        raise Exception(f"Generation failed: {data.get('failMsg')}")

                    print(f"  Status: {state or 'processing'}...")
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

    parser = argparse.ArgumentParser(description="KIE.ai TTS - Text to Speech")
    parser.add_argument("text", nargs="?", help="Text or path to .txt file")
    parser.add_argument("-v", "--voice", default="Jessica", help=f"Voice: {', '.join(VOICES)}")
    parser.add_argument("-o", "--output", default="downloads/voiceover.mp3", help="Output file")
    parser.add_argument("-s", "--stability", type=float, default=0.5, help="Stability 0-1")
    parser.add_argument("-l", "--lang", default="en", help="Language code: en, ru, es, de, fr, etc.")
    parser.add_argument("--voices", action="store_true", help="List available voices")
    args = parser.parse_args()

    if args.voices:
        print("Available voices:")
        for v in VOICES:
            print(f"  - {v}")
        print(f"\nEmotion tags: {TAGS}")
        return

    if not args.text:
        print("Usage: python kie_tts.py \"Your text here\" -v Jessica -o output.mp3")
        print("       python kie_tts.py script.txt -v Liam")
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
        language=args.lang
    )

    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())

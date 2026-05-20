import asyncio
from app.api.v1.audio import _transcribe_with_nvidia, _transcribe_with_groq
import urllib.request
import tempfile
import os

async def main():
    # Download a tiny test audio
    urllib.request.urlretrieve("https://github.com/audio-samples/audio-samples.github.io/raw/master/samples/mp3/speech/sample-1.mp3", "test.mp3")
    print("Testing Groq...")
    text, _, _ = await _transcribe_with_groq("test.mp3", "en", "")
    print(f"Groq: {text}")
    print("Testing NVIDIA...")
    text, _, _ = await _transcribe_with_nvidia("test.mp3", "en", "")
    print(f"NVIDIA: {text}")

if __name__ == "__main__":
    asyncio.run(main())

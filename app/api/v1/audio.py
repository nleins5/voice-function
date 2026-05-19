from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import os
import sys
import tempfile
import subprocess
import aiofiles
import httpx
from app.config import settings

router = APIRouter()


def _looks_invalid_key(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in ("invalid", "test_key", "your_", "paste_", "replace_"))


# Whisper hallucination patterns (silent/noise audio produces these)
WHISPER_HALLUCINATIONS = {
    "1", "1.", ".", "..", "...", "…",
    "Thank you.", "Thanks for watching.",
    "Thank you for watching.", "Subscribe to my channel.",
    "Đây là câu nói tiếng Việt.",
    "Cảm ơn các bạn đã xem.",
    "Hẹn gặp lại.",
    "you", "You",
}


def _is_hallucination(text: str, prompt: str) -> bool:
    """Check if transcription is a known Whisper hallucination."""
    if not text:
        return True
    stripped = text.strip().rstrip(".")
    if stripped in WHISPER_HALLUCINATIONS or text.strip() in WHISPER_HALLUCINATIONS:
        return True
    if text.strip() == prompt.strip():
        return True
    # Extremely short single-char or just punctuation
    if len(stripped) <= 1:
        return True
    return False


def _convert_to_wav(input_path: str) -> str:
    """Convert audio to WAV using ffmpeg if available, for better Whisper compatibility."""
    wav_path = input_path.rsplit(".", 1)[0] + ".wav"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", wav_path],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and os.path.exists(wav_path):
            return wav_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # ffmpeg not installed or timed out
    return ""


async def _transcribe_with_cloudflare(audio_bytes: bytes) -> str:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_key = os.getenv("CLOUDFLARE_API_KEY")
    if _looks_invalid_key(account_id) or _looks_invalid_key(api_key):
        raise HTTPException(
            status_code=500,
            detail="No valid speech-to-text provider configured. Set NVIDIA_API_KEY, GROQ_API_KEY or CLOUDFLARE_API_KEY.",
        )

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/openai/whisper"
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/octet-stream",
            },
            content=audio_bytes,
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Cloudflare STT error {response.status_code}: {response.text}")

    payload = response.json()
    result = payload.get("result") or {}
    return (result.get("text") or payload.get("text") or "").strip()


async def _transcribe_with_nvidia(temp_path: str, language: str, prompt: str) -> str:
    nvidia_api_key = settings.nvidia_api_key
    if _looks_invalid_key(nvidia_api_key):
        return ""

    try:
        client = AsyncOpenAI(api_key=nvidia_api_key, base_url="https://integrate.api.nvidia.com/v1")
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=audio_file,
                model="openai/whisper-large-v3",
                language=language,
                temperature=0.0,
                prompt=prompt,
                response_format="json"
            )
        return transcription.text.strip()
    except Exception as e:
        print(f"[STT] Nvidia error: {e}", file=sys.stderr)
        return ""


async def _transcribe_with_groq(temp_path: str, language: str, prompt: str) -> str:
    groq_api_key = settings.groq_api_key
    if _looks_invalid_key(groq_api_key):
        return ""

    try:
        client = AsyncOpenAI(api_key=groq_api_key, base_url="https://api.groq.com/openai/v1")
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3",
                language=language,
                temperature=0.0,
                prompt=prompt,
                response_format="json"
            )
        return transcription.text.strip()
    except Exception as e:
        print(f"[STT] Groq error: {e}", file=sys.stderr)
        return ""


@router.post("/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    language: str = Form("vi"),
):
    temp_path = None
    wav_path = None
    try:
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".webm"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        file_size = 0
        async with aiofiles.open(temp_path, "wb") as temp_file:
            while chunk := await file.read(8192):
                file_size += len(chunk)
                await temp_file.write(chunk)

        print(f"[STT] Received audio: {file.filename}, size={file_size}, suffix={suffix}", file=sys.stderr)

        # Reject extremely small files (likely empty/silence)
        if file_size < 1000:
            print(f"[STT] File too small ({file_size} bytes), likely empty recording", file=sys.stderr)
            return {"text": "", "error": "Audio quá ngắn hoặc trống"}

        normalized_language = "en" if language.lower().startswith("en") else "vi"
        transcription_prompt = (
            "This is an English learner speaking. Preserve filler words and possible recognition mistakes."
            if normalized_language == "en"
            else "Đây là câu nói tiếng Việt."
        )

        # Try converting to WAV for better compatibility (especially Safari mp4)
        wav_path = _convert_to_wav(temp_path)
        primary_path = wav_path if wav_path else temp_path

        text = ""
        provider_used = "none"

        # 1. Try Groq first (faster, better Safari mp4 support)
        text = await _transcribe_with_groq(primary_path, normalized_language, transcription_prompt)
        if text and not _is_hallucination(text, transcription_prompt):
            provider_used = "groq"
        else:
            text = ""

        # 2. Fallback to NVIDIA
        if not text:
            text = await _transcribe_with_nvidia(primary_path, normalized_language, transcription_prompt)
            if text and not _is_hallucination(text, transcription_prompt):
                provider_used = "nvidia"
            else:
                text = ""

        # 3. Fallback to Cloudflare
        if not text:
            try:
                async with aiofiles.open(primary_path, "rb") as audio_file:
                    audio_bytes = await audio_file.read()
                raw = await _transcribe_with_cloudflare(audio_bytes)
                if raw and not _is_hallucination(raw, transcription_prompt):
                    text = raw
                    provider_used = "cloudflare"
            except HTTPException as e:
                if e.status_code == 500 and "No valid speech-to-text provider" in e.detail:
                    pass
                else:
                    raise

        print(f"[STT] Result: provider={provider_used}, text_len={len(text)}, text={text[:80]}...", file=sys.stderr)

        if not text:
            return {"text": "", "error": "Không nhận diện được giọng nói. Hãy nói gần micro hơn."}

        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[STT] Unexpected error: {e}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)


@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    groq_api_key = settings.groq_api_key
    nvidia_api_key = settings.nvidia_api_key
    
    if not groq_api_key and not nvidia_api_key:
        await websocket.close(code=1011)
        return

    try:
        while True:
            data = await websocket.receive_bytes()
            temp_path = None
            try:
                suffix = ".webm"
                if data[:4] == b'\x1aE\xdf\xa3':
                    suffix = ".webm"
                elif b'ftyp' in data[:32]:
                    suffix = ".mp4"

                fd, temp_path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)

                async with aiofiles.open(temp_path, "wb") as temp_file:
                    await temp_file.write(data)

                text = ""
                prompt = "Đây là câu nói tiếng Việt."

                if not _looks_invalid_key(groq_api_key):
                    text = await _transcribe_with_groq(temp_path, "vi", prompt)

                if not text and not _looks_invalid_key(nvidia_api_key):
                    text = await _transcribe_with_nvidia(temp_path, "vi", prompt)

                if text and not _is_hallucination(text, prompt):
                    await websocket.send_json({"text": text})
            except Exception as e:
                print(f"[WS-STT] Error: {e}", file=sys.stderr)
                await websocket.send_json({"error": str(e)})
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
    except WebSocketDisconnect:
        print("Client disconnected from audio stream", file=sys.stderr)

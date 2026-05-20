from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import os
import sys
import tempfile
import subprocess
import aiofiles
import httpx
import wave
import re
from app.config import settings

router = APIRouter()

def analyze_speech_metrics(text: str, segments: list, duration: float) -> dict:
    words = re.findall(r'\b\w+\b', text.lower())
    
    # 1. Repetitions (lặp từ)
    repetitions = 0
    for i in range(1, len(words)):
        if words[i] == words[i-1]:
            repetitions += 1
            
    # 2. Hesitations (ngập ngừng)
    fillers = {"ờ", "ừm", "à", "ừ", "um", "uh", "hmm", "like", "well", "so"}
    hesitations = sum(1 for w in words if w in fillers)
    
    # 3. Pauses (ngắt quãng)
    pauses_count = 0
    total_pause_time = 0.0
    if segments:
        for i in range(1, len(segments)):
            prev_seg = segments[i-1]
            curr_seg = segments[i]
            prev_end = getattr(prev_seg, "end", prev_seg.get("end", 0)) if isinstance(prev_seg, dict) else getattr(prev_seg, "end", 0)
            curr_start = getattr(curr_seg, "start", curr_seg.get("start", 0)) if isinstance(curr_seg, dict) else getattr(curr_seg, "start", 0)
            gap = curr_start - prev_end
            if gap > 0.5: # 0.5s threshold
                pauses_count += 1
                total_pause_time += gap
    else:
        # Fallback estimation
        est_speech_time = len(words) / 2.5
        if duration > est_speech_time + 1.0:
            total_pause_time = duration - est_speech_time
            pauses_count = int(total_pause_time / 1.0)
            
    return {
        "duration_seconds": round(duration, 1),
        "pauses_count": pauses_count,
        "total_pause_seconds": round(total_pause_time, 1),
        "hesitations_count": hesitations,
        "repetitions_count": repetitions
    }



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


async def _transcribe_with_nvidia(temp_path: str, language: str, prompt: str) -> tuple[str, list, float]:
    nvidia_api_key = settings.nvidia_api_key
    if _looks_invalid_key(nvidia_api_key):
        return "", [], 0.0

    try:
        client = AsyncOpenAI(api_key=nvidia_api_key, base_url="https://integrate.api.nvidia.com/v1")
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=audio_file,
                model="openai/whisper-large-v3",
                language=language,
                temperature=0.0,
                prompt=prompt,
                response_format="verbose_json"
            )
        text = transcription.text.strip() if hasattr(transcription, "text") else transcription.get("text", "").strip()
        segments = getattr(transcription, "segments", [])
        if not segments and isinstance(transcription, dict):
            segments = transcription.get("segments", [])
            
        duration = getattr(transcription, "duration", 0.0)
        if not duration and isinstance(transcription, dict):
            duration = transcription.get("duration", 0.0)
            
        return text, segments, duration
    except Exception as e:
        print(f"[STT] Nvidia error: {e}", file=sys.stderr)
        return "", [], 0.0


async def _transcribe_with_groq(temp_path: str, language: str, prompt: str) -> tuple[str, list, float]:
    groq_api_key = settings.groq_api_key
    if _looks_invalid_key(groq_api_key):
        return "", [], 0.0

    try:
        client = AsyncOpenAI(api_key=groq_api_key, base_url="https://api.groq.com/openai/v1")
        with open(temp_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3",
                language=language,
                temperature=0.0,
                prompt=prompt,
                response_format="verbose_json"
            )
        text = transcription.text.strip() if hasattr(transcription, "text") else transcription.get("text", "").strip()
        segments = getattr(transcription, "segments", [])
        if not segments and isinstance(transcription, dict):
            segments = transcription.get("segments", [])
            
        duration = getattr(transcription, "duration", 0.0)
        if not duration and isinstance(transcription, dict):
            duration = transcription.get("duration", 0.0)
            
        return text, segments, duration
    except Exception as e:
        print(f"[STT] Groq error: {e}", file=sys.stderr)
        return "", [], 0.0


@router.post("/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    language: str = Form("vi"),
    client_duration: float = Form(0.0),
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

        duration_from_wave = 0.0
        if wav_path and os.path.exists(wav_path):
            try:
                with wave.open(wav_path, "rb") as wf:
                    duration_from_wave = wf.getnframes() / float(wf.getframerate())
            except Exception as e:
                print(f"[STT] Error getting duration: {e}", file=sys.stderr)

        text = ""
        segments = []
        stt_duration = 0.0
        provider_used = "none"

        # 1. Try Groq first (faster, better Safari mp4 support)
        text, segments, stt_duration = await _transcribe_with_groq(primary_path, normalized_language, transcription_prompt)
        if text and not _is_hallucination(text, transcription_prompt):
            provider_used = "groq"
        else:
            text = ""
            segments = []
            stt_duration = 0.0

        # 2. Fallback to NVIDIA
        if not text:
            text, segments, stt_duration = await _transcribe_with_nvidia(primary_path, normalized_language, transcription_prompt)
            if text and not _is_hallucination(text, transcription_prompt):
                provider_used = "nvidia"
            else:
                text = ""
                segments = []
                stt_duration = 0.0

        # 3. Fallback to Cloudflare
        if not text:
            try:
                async with aiofiles.open(primary_path, "rb") as audio_file:
                    audio_bytes = await audio_file.read()
                raw = await _transcribe_with_cloudflare(audio_bytes)
                if raw and not _is_hallucination(raw, transcription_prompt):
                    text = raw
                    segments = []
                    stt_duration = 0.0
                    provider_used = "cloudflare"
            except HTTPException as e:
                print(f"[STT] Cloudflare fallback error: {e.detail}", file=sys.stderr)
            except Exception as e:
                print(f"[STT] Cloudflare error: {e}", file=sys.stderr)

        print(f"[STT] Result: provider={provider_used}, text_len={len(text)}, text={text[:80]}...", file=sys.stderr)

        if not text:
            return {"text": "", "error": "Không nhận diện được giọng nói. Hãy nói gần micro hơn."}
            
        final_duration = stt_duration or client_duration or duration_from_wave

        metrics = analyze_speech_metrics(text, segments, final_duration)
        return {"text": text, "metrics": metrics}
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
                segments = []
                stt_duration = 0.0
                prompt = "Đây là câu nói tiếng Việt."

                if not _looks_invalid_key(groq_api_key):
                    text, segments, stt_duration = await _transcribe_with_groq(temp_path, "vi", prompt)

                if not text and not _looks_invalid_key(nvidia_api_key):
                    text, segments, stt_duration = await _transcribe_with_nvidia(temp_path, "vi", prompt)

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

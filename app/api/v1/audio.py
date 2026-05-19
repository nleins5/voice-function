from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import os
import tempfile
import aiofiles
import httpx
from app.config import settings

router = APIRouter()


def _looks_invalid_key(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in ("invalid", "test_key", "your_", "paste_", "replace_"))


async def _transcribe_with_cloudflare(audio_bytes: bytes) -> str:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_key = os.getenv("CLOUDFLARE_API_KEY")
    if _looks_invalid_key(account_id) or _looks_invalid_key(api_key):
        raise HTTPException(
            status_code=500,
            detail="No valid speech-to-text provider configured. Set GROQ_API_KEY or CLOUDFLARE_API_KEY/CLOUDFLARE_ACCOUNT_ID.",
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

@router.post("/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    language: str = Form("vi"),
):
    groq_api_key = settings.groq_api_key

    # Using tempfile and aiofiles to avoid blocking the event loop
    temp_path = None
    try:
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".webm"
        # Create a named temporary file and get its path, then close it immediately
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        async with aiofiles.open(temp_path, "wb") as temp_file:
            # Read in chunks to avoid loading large files into memory
            while chunk := await file.read(8192):
                await temp_file.write(chunk)

        normalized_language = "en" if language.lower().startswith("en") else "vi"
        transcription_prompt = (
            "This is an English learner speaking. Preserve filler words and possible recognition mistakes."
            if normalized_language == "en"
            else "Đây là câu nói tiếng Việt."
        )

        text = ""
        if not _looks_invalid_key(groq_api_key):
            try:
                client = AsyncOpenAI(api_key=groq_api_key, base_url="https://api.groq.com/openai/v1")
                with open(temp_path, "rb") as audio_file:
                    transcription = await client.audio.transcriptions.create(
                        file=audio_file,
                        model="whisper-large-v3",
                        language=normalized_language,
                        temperature=0.0,
                        prompt=transcription_prompt,
                        response_format="json"
                    )
                text = transcription.text.strip()
            except Exception:
                text = ""

        if not text:
            async with aiofiles.open(temp_path, "rb") as audio_file:
                audio_bytes = await audio_file.read()
            text = await _transcribe_with_cloudflare(audio_bytes)

        # Lọc bỏ các kết quả bịa đặt thường gặp của Whisper
        if not text or text in ["1", "1.", "Đây là câu nói tiếng Việt.", transcription_prompt]:
            return {"text": ""}

        return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    groq_api_key = settings.groq_api_key
    if not groq_api_key:
        await websocket.close(code=1011)
        return

    try:
        while True:
            data = await websocket.receive_bytes()
            temp_path = None
            try:
                # Detect audio format from magic bytes
                suffix = ".webm"
                if data[:4] == b'\x1aE\xdf\xa3':  # webm
                    suffix = ".webm"
                elif b'ftyp' in data[:32]:  # mp4
                    suffix = ".mp4"

                fd, temp_path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)

                async with aiofiles.open(temp_path, "wb") as temp_file:
                    await temp_file.write(data)

                # Call Groq transcription API
                import httpx
                async with httpx.AsyncClient() as client:
                    with open(temp_path, "rb") as audio_file:
                        mime_type = "audio/webm" if suffix == ".webm" else "audio/mp4"
                        files = {"file": (temp_path, audio_file, mime_type)}
                        data_payload = {
                            "model": "whisper-large-v3",
                            "language": "vi",
                            "temperature": "0.0",
                            "prompt": "Đây là câu nói tiếng Việt."
                        }

                        response = await client.post(
                            "https://api.groq.com/openai/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {groq_api_key}"},
                            files=files,
                            data=data_payload,
                            timeout=30.0
                        )

                    if response.status_code == 200:
                        result = response.json()
                        text = result.get("text", "").strip()
                        # Lọc bỏ các kết quả bịa đặt thường gặp của Whisper
                        if text and text not in ["1", "1.", "Đây là câu nói tiếng Việt."]:
                            await websocket.send_json({"text": text})
                    else:
                        await websocket.send_json({"error": f"Groq API error {response.status_code}: {response.text}"})
            except Exception as e:
                print(f"WebSocket STT Error: {e}")
                await websocket.send_json({"error": str(e)})
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
    except WebSocketDisconnect:
        print("Client disconnected from audio stream")

"""Gemini 3.8 TTS via documented Interactions REST API; no secrets in errors."""
import base64
import io
import json
import time
import urllib.error
import urllib.request
import wave

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def synthesize(transcript, style, api_key, voice="Achird", model="gemini-3.8-flash-tts", retries=2, retry_delay=65):
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for Egyptian Arabic speech.")
    if not model.startswith("gemini-3.8-"):
        raise ValueError("This speech adapter requires a Gemini 3.8 TTS model; legacy speechConfig payloads are unsupported.")
    payload = {"model": model, "input": [{"type": "user_input", "content": [{"type": "text", "text": transcript, "annotations": [{"type": "speech_metadata", "style": style}]}]}], "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": voice}]}}
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=180) as stream:
                response = json.load(stream)
            break
        except urllib.error.HTTPError as error:
            status = error.code
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(retry_delay)
                continue
            raise RuntimeError(f"Gemini speech HTTP {status}. Check model access, billing/quota and API key restrictions; no response or credentials logged.") from None
        except (OSError, ValueError):
            raise RuntimeError("Gemini speech request failed; check connectivity. No credentials logged.") from None
    blocks = [content for step in response.get("steps", []) if step.get("type") == "model_output" for content in step.get("content", []) if content.get("type") == "audio"]
    if not blocks:
        raise RuntimeError("Gemini returned no audio output.")
    try:
        audio = base64.b64decode(blocks[-1]["data"], validate=True)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getnframes() == 0:
                raise ValueError("Unexpected audio format")
    except (ValueError, KeyError, wave.Error, EOFError):
        raise RuntimeError("Gemini returned invalid WAV audio; no file was saved.") from None
    return audio

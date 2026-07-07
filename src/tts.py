"""Озвучивает текст в mp3 через edge-tts и возвращает тайминги слов для синхронных субтитров."""
import asyncio
import random

import edge_tts

from config import CFG

# Ротация голосов (берутся из конфига канала) — чтобы видео не звучали как один и тот же
# шаблон каждый раз (YouTube's "inauthentic content" policy следит за этим).

TTS_MIN_DURATION = 20.0  # секунд — меньше значит обрыв стрима, нужен retry. Понижено с 25:
# целевая длина скриптов сократилась до ~25-30с (алгоритм любит короткие), валидный короткий
# скрипт ~22с не должен ловить ложный retry; реальный обрыв стрима даёт сильно меньше.
TTS_MAX_RETRIES = 3


def _pick_voice() -> str:
    return random.choice(CFG["voices"])


async def _synthesize(text: str, out_path: str, voice: str) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice, rate="+5%", boundary="WordBoundary")
    words = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 10_000_000,  # 100-ns units -> seconds
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                })
    return words


def text_to_speech(text: str, out_path: str) -> list[dict]:
    """Synthesizes speech to out_path, returns per-word timing: [{"text", "start", "end"}, ...]."""
    voice = _pick_voice()
    words: list[dict] = []
    last_err: Exception | None = None
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        # edge-tts иногда бросает исключение (NoAudioReceived — транзиентный сбой сети/
        # сервиса), а не просто отдаёт короткое аудио — раньше это пробивало retry-цикл
        # насквозь (исключение прерывало asyncio.run до проверки длины), реальный сбой
        # на проде 2026-07-06. Теперь оба случая (исключение и короткое аудио) ретраятся.
        try:
            words = asyncio.run(_synthesize(text, out_path, voice))
        except Exception as e:
            last_err = e
            print(f"  TTS attempt {attempt}: {e}, retrying...")
            continue
        duration = words[-1]["end"] if words else 0
        if duration >= TTS_MIN_DURATION:
            return words
        print(f"  TTS attempt {attempt}: audio too short ({duration:.1f}s < {TTS_MIN_DURATION}s), retrying...")
    if not words and last_err is not None:
        raise last_err
    # Последняя попытка — возвращаем что есть (в т.ч. пусто, если ловили только
    # короткое-аудио случаи), pipeline дальше разберётся.
    return words


if __name__ == "__main__":
    result = text_to_speech("Esto es una prueba de voz.", "test.mp3")
    print(result)

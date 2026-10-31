"""Озвучивает текст в mp3 через edge-tts и возвращает тайминги слов для синхронных субтитров."""
import asyncio
import random
import time

import edge_tts

from config import CFG

# Ротация голосов (берутся из конфига канала) — чтобы видео не звучали как один и тот же
# шаблон каждый раз (YouTube's "inauthentic content" policy следит за этим).

TTS_MIN_DURATION = 20.0  # секунд — меньше значит обрыв стрима, нужен retry. Понижено с 25:
# целевая длина скриптов сократилась до ~25-30с (алгоритм любит короткие), валидный короткий
# скрипт ~22с не должен ловить ложный retry; реальный обрыв стрима даёт сильно меньше.
TTS_MAX_RETRIES = 3


def _pick_voice() -> str:
    """voice_weights (CFG, опционально) — необязательный тилт в сторону сильнейшего по retention
    голоса (2026-08-21, weekly_report). Веса, не жёсткий выбор — ротация остальных сохраняется
    ради anti-"inauthentic content" сигнала (см. комментарий выше)."""
    voices = CFG["voices"]
    weights = CFG.get("voice_weights")
    if weights:
        return random.choices(voices, weights=[weights.get(v, 1) for v in voices], k=1)[0]
    return random.choice(voices)


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


def text_to_speech(text: str, out_path: str) -> tuple[list[dict], str]:
    """Synthesizes speech to out_path, returns (per-word timing, voice used) —
    voice нужен вызывающему для тега в аналитику (2026-07-10, см. weekly_report.py)."""
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
            print(f"  TTS attempt {attempt} ({voice}): {e}")
            if attempt < TTS_MAX_RETRIES:
                time.sleep(4 * attempt)
                alternatives = [v for v in CFG["voices"] if v != voice]
                if alternatives:
                    voice = random.choice(alternatives)
            continue
        duration = words[-1]["end"] if words else 0
        if duration >= TTS_MIN_DURATION:
            return words, voice
        print(f"  TTS attempt {attempt} ({voice}): audio too short ({duration:.1f}s < {TTS_MIN_DURATION}s)")
        if attempt < TTS_MAX_RETRIES:
            time.sleep(4 * attempt)
            alternatives = [v for v in CFG["voices"] if v != voice]
            if alternatives:
                voice = random.choice(alternatives)
    if last_err is not None:
        raise last_err
    raise RuntimeError(f"TTS audio too short after {TTS_MAX_RETRIES} attempts")


if __name__ == "__main__":
    result = text_to_speech("Esto es una prueba de voz.", "test.mp3")
    print(result)

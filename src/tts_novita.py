"""TTS через novita.ai (MiniMax speech-02-turbo) — для лонгформа (качество голоса важнее,
чем у 30-сек Shorts). Синхронный эндпоинт: весь скрипт (<10k символов) одним запросом.

Интерфейс совместим с tts.text_to_speech: возвращает [{"text","start","end"}].
ВАЖНО: синхронный turbo НЕ отдаёт пословные тайминги, поэтому мы оцениваем их
пропорционально (по длине слов на измеренную длительность аудио). Для нижних субтитров
лонгформа это приемлемо; если перейдём на novita в прод — апгрейд на async-эндпоинт
с реальными субтитрами (timestamps).

Ключ: NOVITA_KEY в окружении. Язык/голос — из CFG (novita_language / novita_voice)."""
import os
import re

import requests

from config import CFG

ENDPOINT = "https://api.novita.ai/v3/minimax-speech-02-turbo"
MODEL_MAX_CHARS = 10000


def _proportional_words(text: str, total_duration: float) -> list[dict]:
    """Распределяет слова по измеренной длительности аудио пропорционально длине (+ константа
    на меж-словный зазор). Приблизительно, но для нижних субтитров лонгформа достаточно."""
    raw = [w for w in re.split(r"\s+", text.strip()) if w]
    if not raw or total_duration <= 0:
        return [{"text": w, "start": 0.0, "end": 0.0} for w in raw]
    weights = [len(w) + 2 for w in raw]  # +2 ≈ зазор/пунктуация
    total_w = sum(weights)
    words, t = [], 0.0
    for w, wt in zip(raw, weights):
        dur = total_duration * wt / total_w
        words.append({"text": w, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
    return words


def _audio_duration(path: str) -> float:
    from moviepy.editor import AudioFileClip
    clip = AudioFileClip(path)
    d = clip.duration
    clip.close()
    return d


def text_to_speech_novita(text: str, out_path: str) -> list[dict]:
    """Озвучивает text через MiniMax speech-02-turbo, пишет mp3 в out_path, возвращает
    тайминги слов (оценочные). Бросает исключение при ошибке — пайплайн ловит и фолбэчит."""
    if len(text) > MODEL_MAX_CHARS:
        raise ValueError(f"novita TTS: текст {len(text)} символов > лимита {MODEL_MAX_CHARS}")

    body = {
        "text": text,
        "stream": False,
        "output_format": "url",
        "voice_setting": {
            "voice_id": CFG.get("novita_voice", "Wise_Woman"),
            "speed": CFG.get("novita_speed", 1.0),
        },
        "audio_setting": {"format": "mp3"},
    }
    lang = CFG.get("novita_language")
    if lang:
        body["language_boost"] = lang

    resp = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {os.environ['NOVITA_KEY']}",
                 "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    audio_url = resp.json().get("audio")
    if not audio_url:
        raise RuntimeError(f"novita TTS: пустой ответ {resp.text[:200]}")

    audio = requests.get(audio_url, timeout=120)
    audio.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(audio.content)

    return _proportional_words(text, _audio_duration(out_path))


if __name__ == "__main__":
    import sys
    words = text_to_speech_novita("Esto es una prueba de la voz de novita punto a i.", "novita_test.mp3")
    print(f"OK: {len(words)} words, {words[-1]['end']:.1f}s -> novita_test.mp3")

"""TTS через novita.ai (MiniMax speech-02-turbo) — для лонгформа (качество голоса важнее,
чем у 30-сек Shorts). Синхронный эндпоинт: <10k символов за вызов.

Интерфейс совместим с tts.text_to_speech: возвращает [{"text","start","end"}].

ВАЖНО (баг, найденный на проде — рассинхрон аудио/субтитров): ни синхронный, ни async
эндпоинт novita не отдаёт пословные тайминги — поле subtitle_enable у MiniMax напрямую
существует, но novita его молча не прокидывает (проверено: запрос с subtitle_enable=True
возвращает 200 без поля субтитров). Раньше здесь была ОДНА пропорциональная оценка на
весь 4-минутный скрипт — ошибка на слово копилась на протяжении всего видео и к концу
давала заметный рассинхрон.

Фикс: режем скрипт на ПРЕДЛОЖЕНИЯ, озвучиваем каждое ОТДЕЛЬНЫМ вызовом, длительность
каждого сегмента — РЕАЛЬНАЯ (из самого аудиофайла), а не оценка. Пропорциональная
оценка остаётся только ВНУТРИ одного предложения (несколько секунд) — там ошибка
не успевает накопиться. Сегменты озвучки склеиваются в один mp3.
Цена не меняется — novita тарифицирует по символам, не по числу запросов.

Ключ: NOVITA_KEY в окружении. Язык/голос — из CFG (novita_language / novita_voice)."""
import os
import re

import requests

from config import CFG

ENDPOINT = "https://api.novita.ai/v3/minimax-speech-02-turbo"
MODEL_MAX_CHARS = 10000


def _split_sentences(text: str) -> list[str]:
    """Режет на предложения по .!? — каждое озвучивается отдельным вызовом
    (реальная длительность на границах вместо накопленной оценки)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _proportional_words(text: str, total_duration: float, t0: float) -> list[dict]:
    """Распределяет слова ОДНОГО предложения по его измеренной длительности пропорционально
    длине слова. Ошибка ограничена длиной предложения (пара секунд), не всего видео."""
    raw = [w for w in re.split(r"\s+", text.strip()) if w]
    if not raw or total_duration <= 0:
        return [{"text": w, "start": t0, "end": t0} for w in raw]
    weights = [len(w) + 2 for w in raw]  # +2 ≈ зазор/пунктуация
    total_w = sum(weights)
    words, t = [], t0
    for w, wt in zip(raw, weights):
        dur = total_duration * wt / total_w
        words.append({"text": w, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
    return words


def _synthesize_segment(text: str, out_path: str) -> None:
    """Один вызов novita на один сегмент текста (<10k символов), пишет mp3 в out_path."""
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


def text_to_speech_novita(text: str, out_path: str) -> list[dict]:
    """Озвучивает text через MiniMax speech-02-turbo ПОСЕГМЕНТНО (по предложениям),
    склеивает аудио в out_path, возвращает тайминги слов (границы предложений —
    реальные, тайминги внутри предложения — оценочные). Бросает исключение при
    ошибке — пайплайн ловит и фолбэчит на edge-tts."""
    import tempfile

    from moviepy.editor import AudioFileClip, concatenate_audioclips

    sentences = _split_sentences(text)
    if not sentences:
        raise ValueError("novita TTS: пустой текст")
    for s in sentences:
        if len(s) > MODEL_MAX_CHARS:
            raise ValueError(f"novita TTS: предложение {len(s)} символов > лимита {MODEL_MAX_CHARS}")

    all_words: list[dict] = []
    clips = []
    t_cursor = 0.0
    tmp_dir = tempfile.mkdtemp()
    try:
        for i, sentence in enumerate(sentences):
            seg_path = os.path.join(tmp_dir, f"seg_{i:03d}.mp3")
            _synthesize_segment(sentence, seg_path)
            clip = AudioFileClip(seg_path)
            all_words.extend(_proportional_words(sentence, clip.duration, t_cursor))
            t_cursor += clip.duration
            clips.append(clip)

        final = concatenate_audioclips(clips)
        final.write_audiofile(out_path, logger=None)
        final.close()
        for c in clips:
            c.close()
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return all_words


if __name__ == "__main__":
    words = text_to_speech_novita(
        "Esto es una prueba de la voz de novita. Verificamos que el corte por frases "
        "mantenga el audio y el texto sincronizados. Esta es la tercera frase de prueba.",
        "novita_test.mp3",
    )
    print(f"OK: {len(words)} words, {words[-1]['end']:.1f}s -> novita_test.mp3")

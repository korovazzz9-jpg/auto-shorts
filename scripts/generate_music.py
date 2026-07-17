"""Генерация фоновой музыки через Stable Audio Open 1.0 (локально, RTX 3060 6GB).

Запуск: python scripts/generate_music.py
Готовые .mp3 сохраняются в assets/music/ai_generated/.

Перед использованием в проде — прогнать через Audd.io + проверить на YouTube
Content ID после заливки (та же практика, что применялась к трекам от знакомого)."""
import glob
import os

import torch
from diffusers import StableAudioPipeline
import soundfile as sf
from pydub import AudioSegment

# winget ставит ffmpeg вне PATH текущей сессии, пока терминал не перезапущен полностью —
# указываем бинарь явно, чтобы не зависеть от перезапуска.
for _candidate in glob.glob(
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe")
):
    AudioSegment.converter = _candidate
    break

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music", "ai_generated")
os.makedirs(OUT_DIR, exist_ok=True)

# NEGATIVE_BASE не включает "drums" — версии с барабанами (*_drums) добавляют его
# отдельно в NEGATIVE_NO_DRUMS, чтобы не конфликтовать с их собственным prompt.
NEGATIVE_BASE = "vocals, singing, low quality, distortion, harsh, loud"
NEGATIVE_NO_DRUMS = NEGATIVE_BASE + ", drums, strong beat"
DURATION_S = 20.0

# 2026-07-17 round 2: пользовательские промпты (готовые полные описания трека под нишу
# фактов/документалку) — перкуссия/ритм уже прописаны ВНУТРИ промпта, поэтому NEGATIVE_BASE
# без "drums" (иначе конфликт с самим промптом).
CUSTOM_TRACKS = {
    "custom_v1": (
        "Cinematic mysterious electronic background music for viral science and interesting "
        "facts videos. Dark but inspiring atmosphere, subtle pulses, deep bass, soft synth "
        "arpeggios, modern documentary vibe, minimal percussion, constant forward motion, "
        "suspense without overpowering narration, highly engaging, clean production, perfect "
        "for YouTube Shorts and TikTok, no vocals, instrumental.",
        NEGATIVE_BASE,
    ),
    "custom_v2": (
        "Modern cinematic documentary soundtrack with futuristic synths, warm pads, light "
        "electronic percussion, subtle tension, sense of curiosity and discovery, uplifting "
        "but mysterious, minimal, clean, suitable for science, history and space facts, "
        "no vocals, instrumental only.",
        NEGATIVE_BASE,
    ),
    "custom_v3": (
        "Epic mysterious electronic soundtrack with hypnotic pulse, atmospheric textures, "
        "deep cinematic bass, modern trailer-inspired sound design, suspenseful and exciting, "
        "designed for short-form viral content, perfect under narration, no vocals, "
        "instrumental.",
        NEGATIVE_BASE,
    ),
    "custom_v4": (
        "Premium cinematic underscore for educational documentaries. Minimal electronic "
        "elements, organic textures, soft piano accents, evolving synth pads, subtle "
        "percussion, inspiring, mysterious, intelligent atmosphere, perfect background for "
        "narration, no vocals.",
        NEGATIVE_BASE,
    ),
    "custom_v5": (
        "Minimal cinematic electronic soundtrack with mysterious atmosphere, clean modern "
        "production, subtle analog synths, deep warm bass, light rhythmic pulse, inspiring "
        "sense of curiosity and discovery, premium documentary feeling, perfect for viral "
        "educational YouTube Shorts, designed to sit behind narration, no vocals, no dramatic "
        "drops, seamless loop, memorable melodic motif.",
        NEGATIVE_BASE,
    ),
}

# 2026-07-17 round 1: по фидбеку "понравился только calm" — даём 3 вариации в каждом
# направлении (включая ещё один шанс mystery/uplifting с другими формулировками) + 4-й трек
# в каждой категории с лёгкими барабанами (не жёсткий бит, а мягкая перкуссионная текстура).
# Не используется в текущем прогоне — оставлено для истории/повторного использования.
_TRACKS_ROUND1 = {
    # --- calm: единственное понравившееся направление, углубляем ---
    "calm_v1": (
        "calm ambient background music, soft warm synth pads, gentle airy texture, "
        "no drums, no vocals, seamless loop, cinematic and minimal",
        NEGATIVE_NO_DRUMS,
    ),
    "calm_v2": (
        "calm ambient background, soft felt piano and warm pads, minimal movement, "
        "no drums, no vocals, seamless loop, gentle and introspective",
        NEGATIVE_NO_DRUMS,
    ),
    "calm_v3": (
        "calm ambient soundscape, soft string drone and subtle pads, slow evolving texture, "
        "no drums, no vocals, seamless loop, peaceful and spacious",
        NEGATIVE_NO_DRUMS,
    ),
    "calm_drums": (
        "calm ambient background music, soft synth pads, very light soft brushed percussion, "
        "subtle rhythmic texture, no strong beat, no vocals, seamless loop, cinematic and minimal",
        NEGATIVE_BASE,
    ),
    # --- mystery: другой заход после отклонённого первого варианта ---
    "mystery_v1": (
        "dark mysterious ambient drone, low tension, soft pulsing bass, "
        "no drums, no vocals, seamless loop, documentary background",
        NEGATIVE_NO_DRUMS,
    ),
    "mystery_v2": (
        "eerie ambient atmosphere, subtle dissonant pads, distant tension, "
        "no drums, no vocals, seamless loop, suspenseful and mysterious",
        NEGATIVE_NO_DRUMS,
    ),
    "mystery_v3": (
        "dark cinematic drone, deep low bass hum, slow tension buildup, "
        "no drums, no vocals, seamless loop, ominous and mysterious",
        NEGATIVE_NO_DRUMS,
    ),
    "mystery_drums": (
        "dark mysterious ambient, soft pulsing bass, light subtle percussive texture, "
        "no strong beat, no vocals, seamless loop, tense documentary background",
        NEGATIVE_BASE,
    ),
    # --- uplifting: другой заход после отклонённого первого варианта ---
    "uplifting_v1": (
        "light uplifting ambient background, gentle piano and soft strings, "
        "no drums, no vocals, seamless loop, curious and warm",
        NEGATIVE_NO_DRUMS,
    ),
    "uplifting_v2": (
        "bright hopeful ambient background, warm strings and soft bells, "
        "no drums, no vocals, seamless loop, inspiring and light",
        NEGATIVE_NO_DRUMS,
    ),
    "uplifting_v3": (
        "gentle uplifting ambient, soft piano arpeggios and airy pads, "
        "no drums, no vocals, seamless loop, curious and optimistic",
        NEGATIVE_NO_DRUMS,
    ),
    "uplifting_drums": (
        "light uplifting ambient background, gentle piano and soft strings, "
        "subtle soft percussion, no strong beat, no vocals, seamless loop, warm and curious",
        NEGATIVE_BASE,
    ),
}


def main():
    print("Загружаю Stable Audio Open 1.0...")
    pipe = StableAudioPipeline.from_pretrained(
        "stabilityai/stable-audio-open-1.0", torch_dtype=torch.float16
    )
    pipe = pipe.to("cuda")

    for name, (prompt, negative_prompt) in CUSTOM_TRACKS.items():
        print(f"Генерирую: {name}...")
        audio = pipe(
            prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=200,
            audio_end_in_s=DURATION_S,
            num_waveforms_per_prompt=1,
        ).audios
        output = audio[0].T.float().cpu().numpy()

        wav_path = os.path.join(OUT_DIR, f"{name}.wav")
        sf.write(wav_path, output, pipe.vae.sampling_rate)

        mp3_path = os.path.join(OUT_DIR, f"{name}.mp3")
        AudioSegment.from_wav(wav_path).export(mp3_path, format="mp3", bitrate="192k")
        os.remove(wav_path)
        print(f"  Готово: {mp3_path}")

    print(f"\nВсе файлы в {OUT_DIR}")
    print("Перед заливкой в assets/music/ — прогнать через Audd.io.")


if __name__ == "__main__":
    main()

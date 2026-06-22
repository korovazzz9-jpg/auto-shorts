"""Озвучивает текст в mp3 через edge-tts и возвращает тайминги слов для синхронных субтитров."""
import asyncio

import edge_tts

VOICE = "en-US-GuyNeural"


async def _synthesize(text: str, out_path: str) -> list[dict]:
    communicate = edge_tts.Communicate(text, VOICE, rate="+5%", boundary="WordBoundary")
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
    return asyncio.run(_synthesize(text, out_path))


if __name__ == "__main__":
    result = text_to_speech("This is a test voiceover.", "test.mp3")
    print(result)

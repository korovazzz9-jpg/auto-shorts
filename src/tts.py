"""Озвучивает текст в mp3 через edge-tts (бесплатный сервис Microsoft)."""
import asyncio

import edge_tts

VOICE = "ru-RU-DmitryNeural"


async def _synthesize(text: str, out_path: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate="+5%")
    await communicate.save(out_path)


def text_to_speech(text: str, out_path: str) -> str:
    asyncio.run(_synthesize(text, out_path))
    return out_path


if __name__ == "__main__":
    text_to_speech("Это тестовая озвучка.", "test.mp3")

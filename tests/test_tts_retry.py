"""Edge TTS outages should try another voice without publishing short audio."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("edge_tts", types.ModuleType("edge_tts"))

import tts


class TtsRetryTests(unittest.TestCase):
    def test_retries_with_another_voice_after_no_audio(self):
        words = [{"text": "hola", "start": 0, "end": 25}]
        with patch.object(tts, "_pick_voice", return_value="voice-a"), \
             patch.object(tts, "CFG", {"voices": ["voice-a", "voice-b"]}), \
             patch.object(tts, "_synthesize", new=lambda *args: args[2]), \
             patch.object(tts.asyncio, "run", side_effect=[RuntimeError("No audio"), words]), \
             patch.object(tts.time, "sleep") as sleep:
            result, voice = tts.text_to_speech("hola", "unused.mp3")
        self.assertEqual(words, result)
        self.assertEqual("voice-b", voice)
        sleep.assert_called_once_with(4)

    def test_never_returns_too_short_audio(self):
        short = [{"text": "hola", "start": 0, "end": 3}]
        with patch.object(tts, "_pick_voice", return_value="voice-a"), \
             patch.object(tts, "CFG", {"voices": ["voice-a"]}), \
             patch.object(tts, "_synthesize", new=lambda *args: args[2]), \
             patch.object(tts.asyncio, "run", return_value=short), \
             patch.object(tts.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "too short"):
                tts.text_to_speech("hola", "unused.mp3")


if __name__ == "__main__":
    unittest.main()

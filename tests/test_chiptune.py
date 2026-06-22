import tempfile
import unittest
import wave
from pathlib import Path

from manageroo.chiptune import SAMPLE_RATE, generate_theme, note_frequency


class ChiptuneTests(unittest.TestCase):
    def test_note_frequency(self):
        self.assertAlmostEqual(note_frequency("A4"), 440.0, places=4)

    def test_generates_valid_original_wav(self):
        with tempfile.TemporaryDirectory() as temp:
            path = generate_theme(Path(temp) / "theme.wav", cue="success", variant=69)
            self.assertTrue(path.exists())
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getframerate(), SAMPLE_RATE)
                self.assertGreater(audio.getnframes(), SAMPLE_RATE)


if __name__ == "__main__":
    unittest.main()

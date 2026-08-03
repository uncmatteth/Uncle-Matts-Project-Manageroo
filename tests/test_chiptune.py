import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from manageroo.chiptune import (
    FADE_SECONDS,
    MASTER_VOLUME,
    SAMPLE_RATE,
    ThemePlayback,
    generate_theme,
    note_frequency,
    theme_duration_seconds,
)


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

    def test_generated_themes_fade_in_and_out(self):
        with tempfile.TemporaryDirectory() as temp:
            for cue in ("install", "build", "success"):
                with self.subTest(cue=cue):
                    path = generate_theme(Path(temp) / f"{cue}.wav", cue=cue, variant=69)
                    with wave.open(str(path), "rb") as audio:
                        frames = audio.readframes(audio.getnframes())
                        first = struct.unpack("<h", frames[:2])[0]
                        last = struct.unpack("<h", frames[-2:])[0]
                        self.assertEqual(first, 0)
                        self.assertEqual(last, 0)

    def test_install_theme_is_long_enough_for_guided_install(self):
        self.assertGreaterEqual(theme_duration_seconds("install"), 300)

    def test_every_cue_is_long_enough_for_three_second_fades(self):
        for cue in ("install", "build", "success"):
            with self.subTest(cue=cue):
                self.assertGreaterEqual(theme_duration_seconds(cue), FADE_SECONDS * 2)

    def test_generated_music_uses_twenty_percent_master(self):
        self.assertEqual(MASTER_VOLUME, 0.2)
        with tempfile.TemporaryDirectory() as temp:
            path = generate_theme(Path(temp) / "success.wav", cue="success", variant=69)
            with wave.open(str(path), "rb") as audio:
                frames = audio.readframes(audio.getnframes())
            samples = struct.unpack(f"<{len(frames) // 2}h", frames)
            self.assertGreater(max(abs(sample) for sample in samples), 1000)
            self.assertLessEqual(max(abs(sample) for sample in samples), 7000)

    def test_playback_rejects_absolute_and_parent_traversal_cues_without_touching_victim(self):
        with tempfile.TemporaryDirectory() as temp:
            victim = Path(temp) / "victim"
            victim.mkdir()
            marker = victim / "marker.txt"
            marker.write_text("keep me\n", encoding="utf-8")
            cues = (str(victim / "tone"), "../victim/tone", "../../outside")
            for cue in cues:
                with self.subTest(cue=cue), patch("manageroo.chiptune.sys.stdout.isatty", return_value=True):
                    playback = ThemePlayback(cue=cue)
                    with self.assertRaises(ValueError):
                        playback.start()
                    playback.stop()
                    self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")
                    self.assertTrue(victim.is_dir())

    def test_playback_runtime_state_cannot_be_injected(self):
        with tempfile.TemporaryDirectory() as temp:
            victim = Path(temp) / "victim"
            victim.mkdir()
            marker = victim / "marker.txt"
            marker.write_text("keep me\n", encoding="utf-8")

            with self.assertRaises(TypeError):
                ThemePlayback(temp_root=victim)  # type: ignore[call-arg]

            playback = ThemePlayback(cue="success")
            for name, value in (
                ("temp_root", victim),
                ("path", victim / "theme.wav"),
                ("process", Mock()),
            ):
                with self.subTest(name=name), self.assertRaises(AttributeError):
                    setattr(playback, name, value)
            playback.stop()
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")
            self.assertTrue(victim.is_dir())

    def test_start_twice_preserves_first_playback_until_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            owned = Path(temp) / "manageroo-owned"
            owned.mkdir()
            process = Mock()
            process.poll.return_value = None
            with (
                patch("manageroo.chiptune.sys.stdout.isatty", return_value=True),
                patch("manageroo.chiptune.tempfile.mkdtemp", return_value=str(owned)) as mkdtemp,
                patch("manageroo.chiptune.generate_theme", side_effect=lambda path, **_: path) as generate,
                patch("manageroo.chiptune._player_command", return_value=["player"]) as player_command,
                patch("manageroo.chiptune.subprocess.Popen", return_value=process) as popen,
            ):
                playback = ThemePlayback(cue="success")
                self.assertTrue(playback.start())
                first_path = playback.path
                self.assertFalse(playback.start())

            mkdtemp.assert_called_once_with(None, "manageroo-music-", None)
            generate.assert_called_once()
            self.assertEqual(player_command.call_count, 2)
            popen.assert_called_once()
            self.assertIs(playback.process, process)
            self.assertEqual(playback.path, first_path)
            self.assertEqual(playback.temp_root, owned.resolve())

            playback.stop()
            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=1.5)
            self.assertFalse(owned.exists())


if __name__ == "__main__":
    unittest.main()

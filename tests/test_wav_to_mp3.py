import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.wav_to_mp3 import convert, find_wav_files, main, plan_targets, publish


def make_wav(path: Path, seconds: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
    )


class PlanTests(unittest.TestCase):
    def test_finds_wav_files_case_insensitively_and_skips_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sub").mkdir()
            (root / "a.wav").touch()
            (root / "sub" / "b.WAV").touch()
            (root / "c.mp3").touch()
            (root / "d.flac").touch()

            found = find_wav_files(root)

        self.assertEqual([p.name for p in found], ["a.wav", "b.WAV"])

    def test_collisions_get_numeric_suffix_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "voice.wav").touch()
            (root / "voice.mp3").touch()
            (root / "voice_1.mp3").touch()

            plan = plan_targets([root / "voice.wav"])

        self.assertEqual(plan[0][1].name, "voice_2.mp3")

    def test_wavs_with_same_stem_get_distinct_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wavs = [root / "take.WAV", root / "take.wav"]

            targets = [target.name for _wav, target in plan_targets(wavs)]

        self.assertEqual(sorted(targets), ["take.mp3", "take_1.mp3"])

    def test_publish_never_overwrites_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wav = root / "music.wav"
            wav.touch()
            existing = root / "music.mp3"
            existing.write_bytes(b"keep me")
            temp = root / ".wav2mp3.tmp.mp3"
            temp.write_bytes(b"new")

            target = publish(temp, wav)

            self.assertEqual(target.name, "music_1.mp3")
            self.assertEqual(existing.read_bytes(), b"keep me")
            self.assertEqual(target.read_bytes(), b"new")
            self.assertFalse(temp.exists())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
class ConversionTests(unittest.TestCase):
    def test_dry_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            make_wav(root / "song.wav")

            code = main([str(root)])

            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["song.wav"])

    def test_run_converts_keeps_wav_and_avoids_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            make_wav(root / "song.wav")
            (root / "song.mp3").write_bytes(b"existing")

            code = main([str(root), "--run"])

            self.assertEqual(code, 0)
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["song.mp3", "song.wav", "song_1.mp3"],
            )
            self.assertEqual((root / "song.mp3").read_bytes(), b"existing")
            self.assertGreater((root / "song_1.mp3").stat().st_size, 0)

    def test_convert_reports_bitrate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wav = Path(tmpdir) / "song.wav"
            make_wav(wav)

            target, bitrate = convert(wav, 0)

            self.assertEqual(target.name, "song.mp3")
            self.assertGreater(bitrate or 0, 0)

    def test_corrupt_wav_fails_without_leaving_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "broken.wav").write_bytes(b"not audio")

            code = main([str(root), "--run"])

            self.assertEqual(code, 1)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["broken.wav"])


if __name__ == "__main__":
    unittest.main()

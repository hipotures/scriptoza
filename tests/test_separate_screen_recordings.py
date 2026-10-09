import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video import separate_screen_recordings as sep


def tags(width, height, gps=False, android="14"):
    row = {"ImageWidth": width, "ImageHeight": height}
    if gps:
        row["GPSCoordinates"] = "50.0 20.0"
    if android:
        row["AndroidVersion"] = android
    return row


class ClassifyTests(unittest.TestCase):
    def test_camera_with_gps(self):
        self.assertEqual(sep.classify(tags(1920, 1080, gps=True)), "camera")

    def test_screen_without_gps_in_portrait(self):
        self.assertEqual(sep.classify(tags(1080, 2400)), "screen")

    def test_gps_with_screen_ratio_is_unknown(self):
        self.assertEqual(sep.classify(tags(2400, 1080, gps=True)), "unknown")

    def test_missing_android_or_warning_is_unknown(self):
        self.assertEqual(sep.classify(tags(1080, 2400, android=None)), "unknown")
        self.assertEqual(sep.classify({**tags(1080, 2400), "Warning": "x"}), "unknown")

    def test_invalid_size_is_unknown(self):
        self.assertEqual(sep.classify({"AndroidVersion": "14"}), "unknown")
        self.assertEqual(sep.classify(tags(0, 0)), "unknown")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        (self.src / "sub").mkdir(parents=True)
        self.screen = self.src / "sub" / "screen.mp4"
        self.camera = self.src / "camera.mp4"
        self.screen.write_bytes(b"s")
        self.camera.write_bytes(b"c")
        self.out = self.root / "out"
        rows = {
            self.screen.resolve(): tags(1080, 2400),
            self.camera.resolve(): tags(1920, 1080, gps=True),
        }
        patcher = mock.patch.object(sep, "read_tags", side_effect=lambda paths, advance=None: {p: rows[p] for p in paths})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_moves_nothing(self):
        self.assertEqual(sep.main([str(self.src), "--output", str(self.out), "--dry-run"]), 0)
        self.assertTrue(self.screen.exists())
        self.assertFalse(self.out.exists())

    def test_moves_only_screen_recordings(self):
        self.assertEqual(sep.main([str(self.src), "--output", str(self.out)]), 0)
        self.assertFalse(self.screen.exists())
        self.assertTrue(self.camera.exists())
        self.assertTrue((self.out / "src" / "sub" / "screen.mp4").exists())

    def test_existing_destination_aborts_before_moving(self):
        target = self.out / "src" / "sub" / "screen.mp4"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        self.assertEqual(sep.main([str(self.src), "--output", str(self.out)]), 1)
        self.assertTrue(self.screen.exists())

    def test_overlapping_output_is_rejected(self):
        self.assertEqual(sep.main([str(self.src), "--output", str(self.src / "out")]), 1)


if __name__ == "__main__":
    unittest.main()

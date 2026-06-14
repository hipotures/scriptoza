import tempfile
import unittest
import zipfile
from pathlib import Path

from utils.musescore_export_mp3_with_tags import extract_metadata, next_available_path, safe_filename


SCORE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.50">
  <Score>
    <metaTag name="Alt Titles">Elegia majowa,</metaTag>
    <metaTag name="arranger"></metaTag>
    <metaTag name="audioComUrl"></metaTag>
    <metaTag name="composer">Ksaos</metaTag>
    <metaTag name="copyright">CC0 1.0</metaTag>
    <metaTag name="creationDate">2026-06-09</metaTag>
    <metaTag name="movementTitle"></metaTag>
    <metaTag name="platform">Linux</metaTag>
    <metaTag name="subtitle">dedykacja</metaTag>
    <metaTag name="workTitle">Lamento di Maggio</metaTag>
  </Score>
</museScore>
"""


class MuseScoreExportTests(unittest.TestCase):
    def test_extracts_only_meaningful_score_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            score_path = Path(tmpdir) / "score.mscz"
            with zipfile.ZipFile(score_path, "w") as archive:
                archive.writestr("score.mscx", SCORE_XML)

            metadata = extract_metadata(score_path)

        self.assertEqual(metadata.work_title, "Lamento di Maggio")
        self.assertEqual(metadata.composer, "Ksaos")
        self.assertEqual(metadata.copyright, "CC0 1.0")
        self.assertEqual(metadata.subtitle, "dedykacja")
        self.assertEqual(metadata.alt_titles, "Elegia majowa,")
        self.assertEqual(
            metadata.ffmpeg_metadata_args(),
            [
                "-metadata",
                "title=Lamento di Maggio",
                "-metadata",
                "artist=Ksaos",
                "-metadata",
                "composer=Ksaos",
                "-metadata",
                "copyright=CC0 1.0",
                "-metadata",
                "comment=dedykacja | Elegia majowa,",
            ],
        )

    def test_safe_filename_uses_work_title_and_removes_path_separators(self) -> None:
        self.assertEqual(safe_filename("Lamento di Maggio"), "Lamento di Maggio.mp3")
        self.assertEqual(safe_filename("A/B: C?"), "A B C.mp3")

    def test_next_available_path_uses_incrementing_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "Lamento di Maggio.mp3"
            self.assertEqual(next_available_path(base), base)

            base.write_bytes(b"old")
            self.assertEqual(
                next_available_path(base),
                Path(tmpdir) / "Lamento di Maggio_1.mp3",
            )

            (Path(tmpdir) / "Lamento di Maggio_1.mp3").write_bytes(b"old")
            self.assertEqual(
                next_available_path(base),
                Path(tmpdir) / "Lamento di Maggio_2.mp3",
            )


if __name__ == "__main__":
    unittest.main()

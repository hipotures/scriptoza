import json
import tempfile
import unittest
from pathlib import Path

from video.follow_crop_to_audio import (
    IdentityPath,
    IdentityPoint,
    build_crop_expression,
    build_filter_complex,
    calculate_timing,
    load_identity_path,
    parse_resolution,
)


class FollowCropToAudioTests(unittest.TestCase):
    def test_parse_resolution_accepts_even_positive_dimensions(self) -> None:
        self.assertEqual(parse_resolution("1080x1920"), (1080, 1920))
        self.assertEqual(parse_resolution("1920X1080"), (1920, 1080))

        with self.assertRaises(ValueError):
            parse_resolution("1081x1920")

        with self.assertRaises(ValueError):
            parse_resolution("1920-1080")

    def test_load_identity_path_resolves_file_uri_and_sorts_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "moon source.mp4"
            data_path = Path(tmpdir) / "identity.json"
            data = {
                "format": "identity-path-v1",
                "source": {
                    "uri": video_path.as_uri(),
                    "width": 7680,
                    "height": 4320,
                },
                "time_unit": "seconds",
                "coordinate_space": "source_pixels_top_left_origin",
                "points": [
                    {"x": 4495, "y": 2295, "t": 425.351293545},
                    {"x": 890, "y": 184, "t": 0.0},
                ],
            }
            data_path.write_text(json.dumps(data), encoding="utf-8")

            identity = load_identity_path(data_path)

        self.assertEqual(identity.source_path, video_path)
        self.assertEqual(identity.source_width, 7680)
        self.assertEqual(identity.source_height, 4320)
        self.assertEqual(
            identity.points,
            (
                IdentityPoint(t=0.0, x=890.0, y=184.0),
                IdentityPoint(t=425.351293545, x=4495.0, y=2295.0),
            ),
        )

    def test_load_identity_path_reports_missing_file(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Identity JSON does not exist"):
            load_identity_path(Path("/does/not/exist.json"))

    def test_calculate_timing_uses_audio_padding(self) -> None:
        identity = IdentityPath(
            source_path=Path("/video.mp4"),
            source_width=7680,
            source_height=4320,
            points=(
                IdentityPoint(t=0.0, x=890.0, y=184.0),
                IdentityPoint(t=425.351293545, x=4495.0, y=2295.0),
            ),
        )

        timing = calculate_timing(identity, audio_duration=110.0)

        self.assertAlmostEqual(timing.source_start, 0.0)
        self.assertAlmostEqual(timing.source_end, 425.351293545)
        self.assertAlmostEqual(timing.final_duration, 116.0)
        self.assertAlmostEqual(timing.speed_factor, 425.351293545 / 116.0)

    def test_build_crop_expression_uses_piecewise_interpolation_and_clamp(self) -> None:
        points = (
            IdentityPoint(t=0.0, x=890.0, y=184.0),
            IdentityPoint(t=10.0, x=1090.0, y=284.0),
        )

        expression = build_crop_expression(
            points=points,
            axis="x",
            crop_size=100,
            source_size_symbol="iw",
        )

        self.assertEqual(
            expression,
            "clip((if(lte(t\\,10.000000)\\,890.000000+(1090.000000-890.000000)*(t-0.000000)/10.000000\\,1090.000000))-50.000000\\,0\\,iw-100)",
        )

    def test_build_filter_complex_preserves_all_frames_and_delays_audio(self) -> None:
        identity = IdentityPath(
            source_path=Path("/video.mp4"),
            source_width=7680,
            source_height=4320,
            points=(
                IdentityPoint(t=0.0, x=890.0, y=184.0),
                IdentityPoint(t=10.0, x=1090.0, y=284.0),
            ),
        )
        timing = calculate_timing(identity, audio_duration=4.0)

        filter_complex = build_filter_complex(
            identity=identity,
            target_width=100,
            target_height=50,
            timing=timing,
        )

        self.assertIn("trim=start=0.000000:end=10.000000", filter_complex)
        self.assertIn("crop=w=100:h=50", filter_complex)
        self.assertIn("setpts=PTS/1.000000", filter_complex)
        self.assertIn("adelay=3000:all=1", filter_complex)
        self.assertIn("apad=pad_dur=3.000000", filter_complex)
        self.assertIn("atrim=duration=10.000000[a]", filter_complex)


if __name__ == "__main__":
    unittest.main()

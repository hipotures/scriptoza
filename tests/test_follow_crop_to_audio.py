import json
import tempfile
import unittest
from pathlib import Path

from rich.progress import TimeRemainingColumn

from video.follow_crop_to_audio import (
    IdentityPath,
    IdentityPoint,
    build_arg_parser,
    build_crop_expression,
    build_ffmpeg_command,
    build_filter_complex,
    build_progress_columns,
    calculate_timing,
    load_identity_path,
    options_from_args,
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

    def test_custom_audio_padding_changes_timing_and_filter(self) -> None:
        identity = IdentityPath(
            source_path=Path("/video.mp4"),
            source_width=7680,
            source_height=4320,
            points=(
                IdentityPoint(t=0.0, x=890.0, y=184.0),
                IdentityPoint(t=10.0, x=1090.0, y=284.0),
            ),
        )

        timing = calculate_timing(
            identity,
            audio_duration=4.0,
            audio_lead_in_seconds=1.0,
            audio_tail_seconds=2.0,
        )
        filter_complex = build_filter_complex(
            identity=identity,
            target_width=100,
            target_height=50,
            timing=timing,
            audio_lead_in_seconds=1.0,
            audio_tail_seconds=2.0,
        )

        self.assertAlmostEqual(timing.final_duration, 7.0)
        self.assertAlmostEqual(timing.speed_factor, 10.0 / 7.0)
        self.assertIn("setpts=PTS/1.428571", filter_complex)
        self.assertIn("adelay=1000:all=1", filter_complex)
        self.assertIn("apad=pad_dur=2.000000", filter_complex)
        self.assertIn("atrim=duration=7.000000[a]", filter_complex)

    def test_cli_options_override_render_settings(self) -> None:
        args = build_arg_parser().parse_args(
            [
                "identity.json",
                "audio.wav",
                "1200x1200",
                "out.mp4",
                "--audio-lead-in",
                "1",
                "--audio-tail",
                "2",
                "--video-codec",
                "libx265",
                "--crf",
                "22",
                "--preset",
                "medium",
                "--audio-codec",
                "libopus",
                "--audio-bitrate",
                "160k",
                "--fps-mode",
                "cfr",
                "--output-suffix",
                "custom",
                "--overwrite",
                "--ffmpeg-bin",
                "/usr/bin/ffmpeg",
                "--ffprobe-bin",
                "/usr/bin/ffprobe",
            ]
        )

        options = options_from_args(args)

        self.assertEqual(options.audio_lead_in_seconds, 1.0)
        self.assertEqual(options.audio_tail_seconds, 2.0)
        self.assertEqual(options.video_codec, "libx265")
        self.assertEqual(options.video_crf, 22)
        self.assertEqual(options.video_preset, "medium")
        self.assertEqual(options.audio_codec, "libopus")
        self.assertEqual(options.audio_bitrate, "160k")
        self.assertEqual(options.fps_mode, "cfr")
        self.assertEqual(options.output_suffix, "custom")
        self.assertTrue(options.overwrite_output)
        self.assertEqual(options.ffmpeg_bin, "/usr/bin/ffmpeg")
        self.assertEqual(options.ffprobe_bin, "/usr/bin/ffprobe")

    def test_ffmpeg_command_uses_render_options(self) -> None:
        identity = IdentityPath(
            source_path=Path("/video.mp4"),
            source_width=7680,
            source_height=4320,
            points=(
                IdentityPoint(t=0.0, x=890.0, y=184.0),
                IdentityPoint(t=10.0, x=1090.0, y=284.0),
            ),
        )
        args = build_arg_parser().parse_args(
            [
                "identity.json",
                "audio.wav",
                "1200x1200",
                "out.mp4",
                "--video-codec",
                "libx265",
                "--crf",
                "22",
                "--preset",
                "medium",
                "--audio-codec",
                "libopus",
                "--audio-bitrate",
                "160k",
                "--overwrite",
                "--ffmpeg-bin",
                "custom-ffmpeg",
            ]
        )
        options = options_from_args(args)
        timing = calculate_timing(identity, audio_duration=4.0)

        command = build_ffmpeg_command(
            identity=identity,
            audio_path=Path("/audio.wav"),
            output_path=Path("/out.mp4"),
            target_width=100,
            target_height=50,
            timing=timing,
            options=options,
        )

        self.assertEqual(command[0], "custom-ffmpeg")
        self.assertIn("-y", command)
        self.assertNotIn("-n", command)
        self.assertEqual(command[command.index("-c:v") + 1], "libx265")
        self.assertEqual(command[command.index("-crf") + 1], "22")
        self.assertEqual(command[command.index("-preset") + 1], "medium")
        self.assertEqual(command[command.index("-c:a") + 1], "libopus")
        self.assertEqual(command[command.index("-b:a") + 1], "160k")
        self.assertEqual(command[command.index("-fps_mode") + 1], "passthrough")

    def test_progress_columns_include_eta(self) -> None:
        columns = build_progress_columns()

        self.assertTrue(any(isinstance(column, TimeRemainingColumn) for column in columns))


if __name__ == "__main__":
    unittest.main()

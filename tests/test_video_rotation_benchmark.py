import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video import video_rotation_benchmark as bench


class FractionTests(unittest.TestCase):
    def test_five_frames_match_the_detector_positions(self):
        self.assertEqual(bench.frame_fractions(5), [0.15, 0.325, 0.5, 0.675, 0.85])

    def test_five_frames_are_a_subset_of_nine(self):
        self.assertTrue(set(bench.frame_fractions(5)) <= set(bench.frame_fractions(9)))

    def test_union_shares_endpoints_and_middle(self):
        self.assertEqual(len(bench.all_fractions((5, 7, 9))), 13)

    def test_single_frame_is_in_the_middle(self):
        self.assertEqual(bench.frame_fractions(1), [0.5])

    def test_zero_frames_is_invalid(self):
        with self.assertRaises(ValueError):
            bench.frame_fractions(0)


class PromptTests(unittest.TestCase):
    def test_every_prompt_offers_all_answers(self):
        for name, prompt in bench.PROMPTS.items():
            for answer in ("-1", "0", "90", "180", "270"):
                self.assertIn(answer, prompt, f"{name} is missing {answer}")

    def test_default_prompt_exists(self):
        self.assertIn(bench.DEFAULT_PROMPT, bench.PROMPTS)


class ThinkingTests(unittest.TestCase):
    def test_answer_is_taken_after_the_thinking_block(self):
        self.assertEqual(bench.strip_thinking("<think>90 or 180?</think>\n180"), "\n180")
        self.assertEqual(bench.parse_answer(bench.strip_thinking("<think>maybe 90</think>0")), 0)

    def test_unfinished_thinking_has_no_answer(self):
        self.assertIsNone(bench.strip_thinking("<think>it could be 90 because"))

    def test_plain_content_is_unchanged(self):
        self.assertEqual(bench.strip_thinking("270"), "270")

    def test_old_results_resume_without_thinking(self):
        settings = {"model": "m", "width": 512, "max_tokens": 32, "prompt_sha256": "h", "apply_tag": False,
                    "thinking": False, "thinking_tokens": 0}
        old = bench.Run(Path("x.jsonl"), {"model": "m", "width": 512, "max_tokens": 32, "prompt_sha256": "h"}, {}, 0.0)
        bench.check_resume(old, settings)
        with self.assertRaises(ValueError):
            bench.check_resume(old, {**settings, "thinking": True, "thinking_tokens": 2048})

    def test_request_gets_extra_tokens_only_when_thinking(self):
        response = mock.Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "0"}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 3},
        }
        session = mock.Mock()
        session.post.return_value = response
        base = dict(cache_dir=Path("."), url="http://x", model="m", prompt="p", width=512,
                    max_tokens=32, timeout=1, apply_tag=False, thinking_tokens=2048)
        bench.ask(session, bench.Settings(thinking=False, **base), b"jpeg")
        plain = session.post.call_args.kwargs["json"]
        bench.ask(session, bench.Settings(thinking=True, **base), b"jpeg")
        thinking = session.post.call_args.kwargs["json"]
        self.assertEqual(plain["max_tokens"], 32)
        self.assertFalse(plain["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(thinking["max_tokens"], 32 + 2048)
        self.assertTrue(thinking["chat_template_kwargs"]["enable_thinking"])


class AngleTests(unittest.TestCase):
    def test_parse_angle(self):
        self.assertEqual(bench.parse_angle("135"), 135)
        self.assertEqual(bench.parse_angle(" 345\n"), 345)
        self.assertEqual(bench.parse_angle("-1"), -1)
        self.assertEqual(bench.parse_angle("360"), 0)
        self.assertEqual(bench.parse_angle("about 45 degrees"), 45)
        self.assertIsNone(bench.parse_angle("up"))
        self.assertIsNone(bench.parse_angle("720"))

    def test_bearing_becomes_the_clockwise_correction(self):
        self.assertEqual(bench.bearing_to_correction(0), 0)
        self.assertEqual(bench.bearing_to_correction(90), 270)
        self.assertEqual(bench.bearing_to_correction(270), 90)
        self.assertEqual(bench.bearing_to_correction(180), 180)
        self.assertEqual(bench.bearing_to_correction(-1), -1)
        self.assertIsNone(bench.bearing_to_correction(None))

    def test_circular_distance_wraps(self):
        self.assertEqual(bench.circular_distance(350, 10), 20)
        self.assertEqual(bench.circular_distance(0, 180), 180)

    def test_circular_mean_wraps(self):
        self.assertEqual(bench.circular_mean([350, 10]), 0)
        self.assertEqual(bench.circular_mean([80, 100]), 90)

    def test_cluster_across_zero_wins(self):
        verdict = bench.angle_tally([345, 0, 15, 180, 90])
        self.assertEqual(verdict.winner, 0)
        self.assertAlmostEqual(verdict.agreement, 3 / 5)

    def test_scattered_answers_have_no_winner(self):
        self.assertIsNone(bench.angle_tally([0, 90, 180, 270, -1]).winner)

    def test_opposite_clusters_of_equal_size_are_ambiguous(self):
        self.assertIsNone(bench.angle_tally([0, 10, 180, 190]).winner)

    def test_undetermined_and_invalid_are_counted(self):
        verdict = bench.angle_tally([130, 140, -1, None, 135])
        self.assertEqual(verdict.winner, 135)
        self.assertEqual((verdict.undetermined, verdict.invalid, verdict.total), (1, 1, 5))

    def test_judge_angle_uses_the_tolerance(self):
        label = frozenset({180})
        self.assertEqual(bench.judge_angle(label, 140, 45), "correct")
        self.assertEqual(bench.judge_angle(label, 120, 45), "wrong")
        self.assertEqual(bench.judge_angle(label, None, 45), "unsure")
        self.assertEqual(bench.judge_angle(bench.SIDEWAYS, 265, 45), "correct")

    def test_angle_run_summary_reports_the_error(self):
        frames = {
            ("a.mp4", fraction): {"file": "a.mp4", "fraction": fraction, "answer": 150, "seconds": 1.0, "error": None}
            for fraction in bench.frame_fractions(5)
        }
        run = bench.Run(Path("x.jsonl"), {"angle": True}, frames, 0.0)
        result = bench.summarize(run, {"a.mp4": frozenset({180})}, 5, 0.6, 45)
        self.assertEqual(result["stats"]["correct"], 1)
        self.assertEqual(result["mean_error"], 30)

    def test_live_line_shows_label_need_and_verdicts(self):
        frames = {
            ("a.mp4", fraction): {"file": "a.mp4", "fraction": fraction, "answer": 180, "seconds": 1.0, "error": None}
            for fraction in bench.all_fractions((5, 7, 9))
        }
        run = bench.Run(Path("x.jsonl"), {"apply_tag": True}, frames, 0.0, {"a.mp4": {"container_rotation": 90}})
        line = bench.live_line(run, "a.mp4", {"a.mp4": frozenset({270})}, (5, 9), 0.6, 45)
        self.assertIn("label 270 tag 90 need 180", line)
        self.assertIn("5: 180 5/5", line)
        self.assertIn("9: 180 9/9", line)


class ParseAnswerTests(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(bench.parse_answer("90"), 90)
        self.assertEqual(bench.parse_answer(" -1\n"), -1)
        self.assertEqual(bench.parse_answer("0"), 0)

    def test_number_inside_text_uses_the_last_one(self):
        self.assertEqual(bench.parse_answer("rotate 270 degrees"), 270)
        self.assertEqual(bench.parse_answer("0 or 90"), 90)

    def test_decimals_and_other_numbers_are_not_answers(self):
        self.assertIsNone(bench.parse_answer("1.0"))
        self.assertIsNone(bench.parse_answer("10"))
        self.assertIsNone(bench.parse_answer(""))
        self.assertIsNone(bench.parse_answer("upright"))


class TallyTests(unittest.TestCase):
    def test_unanimous_vote(self):
        verdict = bench.tally([90] * 5)
        self.assertEqual(verdict.winner, 90)
        self.assertEqual(verdict.agreement, 1.0)

    def test_tie_has_no_winner(self):
        self.assertIsNone(bench.tally([0, 0, 90, 90, 180]).winner)

    def test_single_valid_vote_is_below_quorum(self):
        verdict = bench.tally([90, -1, -1, None, None])
        self.assertIsNone(verdict.winner)
        self.assertEqual(verdict.undetermined, 2)
        self.assertEqual(verdict.invalid, 2)

    def test_agreement_ignores_unreadable_frames(self):
        verdict = bench.tally([0, 0, 90, -1, None])
        self.assertEqual(verdict.winner, 0)
        self.assertEqual(verdict.readable, 3)
        self.assertAlmostEqual(verdict.agreement, 2 / 3)

    def test_unreadable_frames_do_not_lower_agreement(self):
        many_unreadable = bench.tally([180, 180, 180, -1, -1, -1, -1, -1, -1])
        self.assertEqual(many_unreadable.agreement, 1.0)
        self.assertEqual(many_unreadable.readable, 3)

    def test_decide_applies_the_agreement_threshold(self):
        verdict = bench.tally([0, 0, 90, 90, 180])
        self.assertIsNone(bench.decide(verdict, 0.6))
        self.assertEqual(bench.decide(bench.tally([0, 0, 0, 90, 180]), 0.6), 0)
        self.assertEqual(bench.decide(bench.tally([0, 0, 90, -1, None]), 0.6), 0)


class JudgeTests(unittest.TestCase):
    def test_angle_labels(self):
        label = frozenset({90})
        self.assertEqual(bench.judge(label, 90), "correct")
        self.assertEqual(bench.judge(label, 270), "wrong")
        self.assertEqual(bench.judge(label, None), "unsure")

    def test_sideways_accepts_both_directions(self):
        self.assertEqual(bench.judge(bench.SIDEWAYS, 270), "correct")
        self.assertEqual(bench.judge(bench.SIDEWAYS, 90), "correct")
        self.assertEqual(bench.judge(bench.SIDEWAYS, 0), "wrong")



class SummarizeTests(unittest.TestCase):
    def run_with(self, answers):
        frames = {
            (name, fraction): {"file": name, "fraction": fraction, "answer": answer, "seconds": 1.0, "error": None}
            for name, answer in answers.items()
            for fraction in bench.frame_fractions(5)
        }
        return bench.Run(Path("x.jsonl"), {}, frames, 0.0)

    def test_unknown_direction_label_is_not_scored(self):
        run = self.run_with({"a.mp4": 90, "b.mp4": 0, "c.mp4": 180})
        labels = {"a.mp4": frozenset({90}), "b.mp4": bench.EXCLUDED, "c.mp4": frozenset({0})}
        result = bench.summarize(run, labels, 5, 0.6)
        stats = result["stats"]
        self.assertEqual(stats["angle"], 2)
        self.assertEqual(stats["correct"], 1)
        self.assertEqual(stats["wrong"], 1)
        self.assertEqual(stats["excluded"], 1)
        self.assertEqual(result["cells"]["b.mp4"][0], "excluded")

    def test_excluded_videos_do_not_count_undetermined_frames(self):
        run = self.run_with({"a.mp4": 90, "b.mp4": -1})
        labels = {"a.mp4": frozenset({90}), "b.mp4": bench.EXCLUDED}
        self.assertEqual(bench.summarize(run, labels, 5, 0.6)["stats"]["undetermined"], 0)


class TagModeTests(unittest.TestCase):
    def tagged_run(self, rotation, answer):
        frames = {
            ("a.mp4", fraction): {"file": "a.mp4", "fraction": fraction, "answer": answer, "seconds": 1.0, "error": None}
            for fraction in bench.frame_fractions(5)
        }
        return bench.Run(
            Path("x.jsonl"),
            {"apply_tag": True},
            frames,
            0.0,
            {"a.mp4": {"container_rotation": rotation}},
        )

    def test_label_is_shifted_by_the_container_rotation(self):
        run = self.tagged_run(90, 180)
        self.assertEqual(bench.effective_label(run, "a.mp4", frozenset({270})), frozenset({180}))
        self.assertEqual(bench.effective_label(run, "a.mp4", frozenset({90})), frozenset({0}))
        self.assertEqual(bench.effective_label(run, "a.mp4", bench.SIDEWAYS), frozenset({0, 180}))

    def test_excluded_label_stays_excluded(self):
        run = self.tagged_run(90, 0)
        self.assertEqual(bench.effective_label(run, "a.mp4", bench.EXCLUDED), bench.EXCLUDED)

    def test_raw_run_keeps_the_label(self):
        run = bench.Run(Path("x.jsonl"), {}, {}, 0.0)
        self.assertEqual(bench.effective_label(run, "a.mp4", frozenset({270})), frozenset({270}))

    def test_missing_rotation_makes_the_video_unlabeled(self):
        run = bench.Run(Path("x.jsonl"), {"apply_tag": True}, {}, 0.0)
        self.assertIsNone(bench.effective_label(run, "a.mp4", frozenset({90})))

    def test_summary_judges_against_the_shifted_label(self):
        run = self.tagged_run(90, 180)
        stats = bench.summarize(run, {"a.mp4": frozenset({270})}, 5, 0.6)["stats"]
        self.assertEqual(stats["correct"], 1)

    def test_need_text(self):
        self.assertEqual(bench.need_text(frozenset({270}), 90), "180")
        self.assertEqual(bench.need_text(bench.SIDEWAYS, 90), "0/180")
        self.assertEqual(bench.need_text(bench.EXCLUDED, 90), "-")

    def test_old_results_resume_as_raw_runs(self):
        old = bench.Run(Path("x.jsonl"), {"model": "m", "width": 512, "max_tokens": 32, "prompt_sha256": "h"}, {}, 0.0)
        expected = {"model": "m", "width": 512, "max_tokens": 32, "prompt_sha256": "h", "apply_tag": False,
                    "thinking": False, "thinking_tokens": 0}
        bench.check_resume(old, expected)
        with self.assertRaises(ValueError):
            bench.check_resume(old, {**expected, "apply_tag": True})

    def test_frames_are_extracted_raw_unless_the_tag_is_applied(self):
        done = mock.Mock(returncode=0, stdout=b"jpeg", stderr=b"")
        with mock.patch.object(bench.subprocess, "run", return_value=done) as run:
            bench.extract_frame(Path("a.mp4"), 1.0, 512)
            raw_command = run.call_args.args[0]
            bench.extract_frame(Path("a.mp4"), 1.0, 512, apply_tag=True)
            tag_command = run.call_args.args[0]
        self.assertIn("-noautorotate", raw_command)
        self.assertNotIn("-noautorotate", tag_command)


class LabelFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "labels.txt"

    def test_loads_labels_and_skips_comments_and_unlabeled(self):
        self.path.write_text(
            "# comment\n01.mp4 0\n02.mp4 \n03.mp4 270\n\n04.mp4 s\n05.mp4 -1\n",
            encoding="utf-8",
        )
        self.assertEqual(
            bench.load_labels(self.path),
            {
                "01.mp4": frozenset({0}),
                "03.mp4": frozenset({270}),
                "04.mp4": bench.SIDEWAYS,
                "05.mp4": bench.EXCLUDED,
            },
        )

    def test_invalid_label_reports_the_line(self):
        self.path.write_text("01.mp4 0\n02.mp4 45\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"labels\.txt:2"):
            bench.load_labels(self.path)


class RunFileTests(unittest.TestCase):
    def test_last_record_wins_and_wall_time_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            bench.append_records(path, [
                {"type": "meta", "label": "x", "model": "m"},
                {"type": "frame", "file": "01.mp4", "fraction": 0.5, "answer": None, "error": "timeout"},
                {"type": "run", "wall_seconds": 10.0},
                {"type": "frame", "file": "01.mp4", "fraction": 0.5, "answer": 90, "error": None},
                {"type": "run", "wall_seconds": 5.5},
            ])
            run = bench.load_run(path)
        self.assertEqual(run.frames[("01.mp4", 0.5)]["answer"], 90)
        self.assertEqual(run.wall_seconds, 15.5)
        self.assertEqual(run.label, "x")

    def test_resume_refuses_different_settings(self):
        settings = {"model": "a", "width": 512, "max_tokens": 32, "prompt_sha256": "h", "apply_tag": False,
                    "thinking": False, "thinking_tokens": 0}
        run = bench.Run(Path("x.jsonl"), dict(settings), {}, 0.0)
        bench.check_resume(run, settings)
        with self.assertRaises(ValueError):
            bench.check_resume(run, {**settings, "model": "b"})


if __name__ == "__main__":
    unittest.main()

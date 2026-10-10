import tempfile
import unittest
from pathlib import Path

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

    def test_agreement_counts_all_frames(self):
        verdict = bench.tally([0, 0, 90, -1, None])
        self.assertEqual(verdict.winner, 0)
        self.assertAlmostEqual(verdict.agreement, 0.4)

    def test_decide_applies_the_agreement_threshold(self):
        verdict = bench.tally([0, 0, 90, -1, None])
        self.assertIsNone(bench.decide(verdict, 0.6))
        self.assertEqual(bench.decide(verdict, 0.4), 0)
        self.assertEqual(bench.decide(bench.tally([0, 0, 0, 90, 180]), 0.6), 0)


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
        run = bench.Run(Path("x.jsonl"), {"model": "a", "width": 512, "max_tokens": 32, "prompt_sha256": "h"}, {}, 0.0)
        bench.check_resume(run, {"model": "a", "width": 512, "max_tokens": 32, "prompt_sha256": "h"})
        with self.assertRaises(ValueError):
            bench.check_resume(run, {"model": "b", "width": 512, "max_tokens": 32, "prompt_sha256": "h"})


if __name__ == "__main__":
    unittest.main()

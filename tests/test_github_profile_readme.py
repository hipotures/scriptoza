import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))

import github_profile_readme as gpr

TODAY = date(2026, 11, 12)


def repo(name, fork=False, pushed="2026-01-02T00:00:00Z", **extra):
    return {
        "name": name,
        "fork": fork,
        "html_url": f"https://github.com/me/{name}",
        "pushed_at": pushed,
        "description": f"{name} desc",
        **extra,
    }


def commits(*months_and_counts):
    return [
        {"commit": {"committer": {"date": f"{month}-15T12:00:00Z"}}}
        for month, count in months_and_counts
        for _ in range(count)
    ]


def week(month, additions, deletions):
    timestamp = int(datetime.fromisoformat(f"{month}-10T00:00:00+00:00").timestamp())
    return [timestamp, additions, -deletions]


HISTORY = {
    "mine": (commits(("2026-11", 5)), [week("2026-11", 400, 20)]),
    "old": (
        commits(("2026-09", 1), ("2026-02", 3), ("2025-11", 6)),
        [week("2026-09", 2, 1), week("2026-02", 5, 3), week("2025-11", 900, 100)],
    ),
}


def fake_fetch(path):
    if path.startswith("/users/me/repos"):
        return [
            repo("mine", pushed="2026-03-01T00:00:00Z"),
            repo("old", pushed="2026-09-01T00:00:00Z"),
            repo("hidden"),
            repo("archived", archived=True),
            repo("me"),
            repo("changed-fork", fork=True),
            repo("plain-fork", fork=True),
            repo("foreign-fork", fork=True),
        ]
    if path in ("/repos/me/changed-fork", "/repos/me/plain-fork", "/repos/me/foreign-fork"):
        name = path.rsplit("/", 1)[1]
        return {"parent": {"full_name": f"up/{name}", "default_branch": "main"}, "default_branch": "main"}
    if "changed-fork/compare" in path:
        return {"ahead_by": 2, "commits": [{"author": {"login": "other"}}, {"author": {"login": "Me"}}]}
    if "plain-fork/compare" in path:
        return {"ahead_by": 0, "commits": []}
    if "foreign-fork/compare" in path:
        return {"ahead_by": 2, "commits": [{"author": {"login": "other"}}, {"author": None}]}
    name = path.split("/")[3]
    history = HISTORY.get(name, ([], []))
    if path.endswith("/stats/code_frequency"):
        return history[1]
    if "/commits?" in path:
        return history[0] if path.endswith("page=1") else []
    raise AssertionError(path)


def link(name):
    return f"[{gpr.nowrap(name)}]"


def build(config):
    return gpr.build_sections(fake_fetch, "me", config, today=TODAY, sleep=lambda _: None)


class BuildSectionsTest(unittest.TestCase):
    def test_classification_and_activity_order(self):
        sections = build({"hide": ["hidden"]})
        projects = sections["PROJECTS"]
        self.assertLess(projects.index(link("mine")), projects.index(link("old")))
        for name in ("hidden", "archived", "changed-fork", "plain-fork"):
            self.assertNotIn(link(name), projects)
        forks = sections["FORKS"]
        self.assertIn(link("changed-fork"), forks)
        self.assertIn(f"{link('up/changed-fork')}(https://github.com/up/changed-fork)", forks)
        self.assertNotIn(link("plain-fork"), forks)
        self.assertNotIn(link("foreign-fork"), forks)

    def test_forced_fork_and_description_override(self):
        config = {"forks": ["plain-fork"], "descriptions": {"plain-fork": "My fix | tweak"}}
        forks = build(config)["FORKS"]
        self.assertIn(link("plain-fork"), forks)
        self.assertIn("My fix \\| tweak", forks)

    def test_external_fork_moves_to_forks_table(self):
        sections = build({"external_forks": {"old": "https://gitlab.example.org/Owner/old.git"}})
        self.assertNotIn(link("old"), sections["PROJECTS"])
        self.assertIn(f"{link('Owner/old')}(https://gitlab.example.org/Owner/old)", sections["FORKS"])

    def test_names_do_not_wrap_and_columns_share_width(self):
        sections = build({})
        self.assertNotIn("[changed-fork]", sections["FORKS"])
        project_header = sections["PROJECTS"].split(" | ")[0]
        self.assertEqual(project_header, sections["FORKS"].split(" | ")[0])
        self.assertIn("&nbsp;Repository&nbsp;", project_header)

    def test_sort_by_name(self):
        projects = build({"sort": "name"})["PROJECTS"]
        self.assertLess(projects.index(link("hidden")), projects.index(link("mine")))

    def test_sort_by_pushed(self):
        projects = build({"sort": "pushed"})["PROJECTS"]
        self.assertLess(projects.index(link("old")), projects.index(link("mine")))


class ActivityTest(unittest.TestCase):
    def activity(self, name, config=None):
        return gpr.last_active_month(fake_fetch, "me", name, config or {}, sleep=lambda _: None)

    def test_small_later_commits_are_ignored(self):
        activity = self.activity("old")
        self.assertEqual(activity.month, "2025-11")
        self.assertEqual((activity.commits, activity.additions, activity.deletions), (6, 900, 100))

    def test_thresholds_are_configurable(self):
        activity = self.activity("old", {"activity": {"min_commits": 1, "min_lines": 1}})
        self.assertEqual(activity.month, "2026-09")

    def test_busiest_month_when_nothing_qualifies(self):
        activity = self.activity("old", {"activity": {"min_commits": 50}})
        self.assertEqual(activity.month, "2025-11")

    def test_empty_repository(self):
        self.assertIsNone(self.activity("missing"))

    def test_stats_retry_until_ready(self):
        responses = iter([None, {}, [week("2026-10", 5, 5)]])
        sleeps = []
        lines = gpr.monthly_lines(lambda _: next(responses), "me", "x", sleep=sleeps.append)
        self.assertEqual(lines, {"2026-10": (5, 5)})
        self.assertEqual(len(sleeps), 2)

    def test_stats_unavailable_uses_commits_only(self):
        def fetch(path):
            if path.endswith("code_frequency"):
                return None
            return commits(("2026-10", 3)) if path.endswith("page=1") else []

        activity = gpr.last_active_month(fetch, "me", "x", {}, sleep=lambda _: None)
        self.assertEqual(activity.month, "2026-10")
        self.assertIsNone(activity.additions)


class BadgeTest(unittest.TestCase):
    def badge(self, month):
        return gpr.activity_badge(gpr.Activity(month, 4, 10, 2), TODAY)

    def test_colors_by_age(self):
        expected = {
            "2026-11": "brightgreen",
            "2026-10": "brightgreen",
            "2026-08": "green",
            "2026-05": "yellow",
            "2025-12": "orange",
            "2025-10": "blue",
        }
        for month, color in expected.items():
            self.assertIn(f"-{color} ", self.badge(month), month)

    def test_label_and_tooltip(self):
        self.assertTrue(self.badge("2026-08").startswith("![Aug](https://img.shields.io/badge/Aug-"))
        self.assertIn("/badge/Apr_2025-blue", self.badge("2025-04"))
        self.assertIn('"Last active month: 4 commits, +10/-2 lines"', self.badge("2026-08"))

    def test_no_activity(self):
        self.assertEqual(gpr.activity_badge(None, TODAY), "")


class MarkersTest(unittest.TestCase):
    def test_replace_keeps_surroundings(self):
        text = "head\n<!-- FORKS:START -->\nold\n<!-- FORKS:END -->\ntail\n"
        result = gpr.replace_between_markers(text, "FORKS", "new")
        self.assertEqual(result, "head\n<!-- FORKS:START -->\nnew\n<!-- FORKS:END -->\ntail\n")

    def test_missing_markers(self):
        with self.assertRaises(ValueError):
            gpr.replace_between_markers("nothing", "FORKS", "x")


class MainTest(unittest.TestCase):
    TEMPLATE = (
        "<!-- PROJECTS:START -->\n<!-- PROJECTS:END -->\n"
        "<!-- FORKS:START -->\n<!-- FORKS:END -->\n"
    )

    def run_main(self, *extra):
        with tempfile.TemporaryDirectory() as directory:
            readme = Path(directory) / "README.md"
            readme.write_text(self.TEMPLATE, encoding="utf-8")
            with mock.patch.object(gpr, "make_fetcher", return_value=fake_fetch):
                with mock.patch("builtins.print"):
                    code = gpr.main([str(readme), "--user", "me", *extra])
            return code, readme.read_text(encoding="utf-8")

    def test_dry_run_does_not_write(self):
        code, content = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(content, self.TEMPLATE)

    def test_run_writes(self):
        code, content = self.run_main("--run")
        self.assertEqual(code, 0)
        self.assertIn(link("mine"), content)
        self.assertIn(link("changed-fork"), content)
        self.assertIn(" | Activity |", content)


if __name__ == "__main__":
    unittest.main()

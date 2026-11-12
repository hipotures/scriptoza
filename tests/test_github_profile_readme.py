import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))

import github_profile_readme as gpr

TODAY = date(2026, 11, 12)


def week(month, commits, additions, deletions):
    timestamp = int(datetime.fromisoformat(f"{month}-10T00:00:00+00:00").timestamp())
    return {"w": timestamp, "c": commits, "a": additions, "d": deletions}


def repo(name, fork=False, pushed="2026-01-02T00:00:00Z", **extra):
    return {
        "name": name,
        "fork": fork,
        "archived": False,
        "html_url": f"https://github.com/me/{name}",
        "pushed_at": pushed,
        "description": f"{name} desc",
        **extra,
    }


CONTRIBUTORS = {
    "mine": [{"weeks": [week("2026-11", 5, 400, 20)]}],
    "old": [
        {"weeks": [week("2025-11", 4, 600, 50), week("2026-02", 3, 5, 3), week("2026-09", 1, 2, 1)]},
        {"weeks": [week("2025-11", 2, 300, 50), week("2026-01", 0, 0, 0)]},
    ],
}
COMPARE = {
    "changed-fork": [{"author": {"login": "other"}}, {"author": {"login": "Me"}}],
    "plain-fork": [],
    "foreign-fork": [{"author": {"login": "other"}}, {"author": None}],
}


def fake_fetch(path):
    if path.startswith("/users/me/repos"):
        return [
            repo("mine", pushed="2026-03-01T00:00:00Z"),
            repo("old", pushed="2026-09-01T00:00:00Z"),
            repo("hidden"),
            repo("archived", archived=True),
            repo("me"),
            *(repo(name, fork=True) for name in COMPARE),
        ]
    parts = path.split("/")
    name = parts[3].split("?")[0] if len(parts) > 3 else ""
    if path.endswith("/stats/contributors"):
        return CONTRIBUTORS.get(name, [])
    if path.endswith("/languages"):
        return {"Python": 1000}
    if path == f"/repos/me/{name}" and name in COMPARE:
        return {"parent": {"full_name": f"up/{name}", "default_branch": "main"}, "default_branch": "main"}
    if "/compare/" in path:
        return {"commits": COMPARE[parts[3]]}
    raise AssertionError(path)


def collect():
    return gpr.collect(fake_fetch, "me", sleep=lambda _: None)


def link(name):
    return f"[{gpr.nowrap(name)}]"


class CollectTest(unittest.TestCase):
    def test_raw_data(self):
        repos = {item["name"]: item for item in collect()["repos"]}
        self.assertEqual(repos["old"]["monthly"], {"2025-11": [6, 900, 100], "2026-02": [3, 5, 3], "2026-09": [1, 2, 1]})
        self.assertEqual(repos["mine"]["languages"], {"Python": 1000})
        self.assertEqual((repos["changed-fork"]["upstream"], repos["changed-fork"]["own_commits"]), ("up/changed-fork", True))
        self.assertFalse(repos["foreign-fork"]["own_commits"])
        self.assertFalse(repos["plain-fork"]["own_commits"])

    def test_stats_retry_until_ready(self):
        responses = iter([None, {}, [{"weeks": [week("2026-10", 2, 5, 5)]}]])
        sleeps = []
        stats = gpr.monthly_stats(lambda _: next(responses), "me", "x", sleep=sleeps.append)
        self.assertEqual(stats, {"2026-10": [2, 5, 5]})
        self.assertEqual(len(sleeps), 2)

    def test_unavailable_stats_keep_previous_data(self):
        previous = {"repos": [{"name": "mine", "monthly": {"2020-01": [9, 9, 9]}}]}

        def fetch(path):
            return None if path.endswith("/stats/contributors") else fake_fetch(path)

        repos = {item["name"]: item for item in gpr.collect(fetch, "me", previous, sleep=lambda _: None)["repos"]}
        self.assertEqual(repos["mine"]["monthly"], {"2020-01": [9, 9, 9]})
        self.assertIsNone(repos["old"]["monthly"])


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = collect()

    def render(self, config):
        return gpr.render(self.data, config, today=TODAY)

    def test_classification_and_activity_order(self):
        sections = self.render({"hide": ["hidden"]})
        projects = sections["PROJECTS"]
        self.assertLess(projects.index(link("mine")), projects.index(link("old")))
        for name in ("hidden", "archived", "me", "changed-fork", "plain-fork"):
            self.assertNotIn(link(name), projects)
        forks = sections["FORKS"]
        self.assertIn(link("changed-fork"), forks)
        self.assertIn(f"{link('up/changed-fork')}(https://github.com/up/changed-fork)", forks)
        self.assertNotIn(link("plain-fork"), forks)
        self.assertNotIn(link("foreign-fork"), forks)

    def test_forced_fork_and_description_override(self):
        forks = self.render({"forks": ["plain-fork"], "descriptions": {"plain-fork": "My fix | tweak"}})["FORKS"]
        self.assertIn(link("plain-fork"), forks)
        self.assertIn("My fix \\| tweak", forks)

    def test_external_fork_moves_to_forks_table(self):
        sections = self.render({"external_forks": {"old": "https://gitlab.example.org/Owner/old.git"}})
        self.assertNotIn(link("old"), sections["PROJECTS"])
        self.assertIn(f"{link('Owner/old')}(https://gitlab.example.org/Owner/old)", sections["FORKS"])

    def test_names_do_not_wrap_and_columns_share_width(self):
        sections = self.render({})
        self.assertNotIn("[changed-fork]", sections["FORKS"])
        header = sections["PROJECTS"].split(" | ")[0]
        self.assertEqual(header, sections["FORKS"].split(" | ")[0])
        self.assertIn("Repository", header)
        wider = gpr.render(self.data, {"layout": {"name_char_em": 1.0}}, today=TODAY)["PROJECTS"].split(" | ")[0]
        self.assertGreater(len(wider), len(header))

    def test_sort_orders(self):
        projects = self.render({"sort": "name"})["PROJECTS"]
        self.assertLess(projects.index(link("hidden")), projects.index(link("mine")))
        projects = self.render({"sort": "pushed"})["PROJECTS"]
        self.assertLess(projects.index(link("old")), projects.index(link("mine")))


class ActivityTest(unittest.TestCase):
    MONTHLY = {"2025-11": [6, 900, 100], "2026-02": [3, 5, 3], "2026-09": [1, 2, 1]}

    def test_small_later_commits_are_ignored(self):
        self.assertEqual(gpr.last_active_month(self.MONTHLY, {}), gpr.Activity("2025-11", 6, 900, 100))

    def test_thresholds_are_configurable(self):
        activity = gpr.last_active_month(self.MONTHLY, {"activity": {"min_commits": 1, "min_lines": 1}})
        self.assertEqual(activity.month, "2026-09")

    def test_busiest_month_when_nothing_qualifies(self):
        activity = gpr.last_active_month(self.MONTHLY, {"activity": {"min_commits": 50}})
        self.assertEqual(activity.month, "2025-11")

    def test_no_data(self):
        self.assertIsNone(gpr.last_active_month(None, {}))
        self.assertIsNone(gpr.last_active_month({}, {}))


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
    TEMPLATE = "<!-- PROJECTS:START -->\n<!-- PROJECTS:END -->\n<!-- FORKS:START -->\n<!-- FORKS:END -->\n"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.readme = Path(directory.name) / "README.md"
        self.readme.write_text(self.TEMPLATE, encoding="utf-8")
        self.data = Path(directory.name) / "data.json"
        self.calls = 0

        def counting_fetch(path):
            self.calls += 1
            return fake_fetch(path)

        patcher = mock.patch.object(gpr, "make_fetcher", return_value=counting_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep_patcher = mock.patch.object(gpr.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def main(self, *extra):
        with redirect_stdout(io.StringIO()):
            return gpr.main([str(self.readme), "--user", "me", *extra])

    def test_dry_run_does_not_write(self):
        self.assertEqual(self.main("--data", str(self.data)), 0)
        self.assertEqual(self.readme.read_text(encoding="utf-8"), self.TEMPLATE)
        self.assertFalse(self.data.exists())

    def test_run_saves_data_and_renders_from_it(self):
        self.assertEqual(self.main("--data", str(self.data), "--run"), 0)
        content = self.readme.read_text(encoding="utf-8")
        self.assertIn(link("mine"), content)
        self.assertIn(" | Activity |", content)
        self.assertEqual(json.loads(self.data.read_text(encoding="utf-8"))["user"], "me")

        self.calls = 0
        self.readme.write_text(self.TEMPLATE, encoding="utf-8")
        self.assertEqual(self.main("--data", str(self.data), "--run"), 0)
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.readme.read_text(encoding="utf-8"), content)

        self.main("--data", str(self.data), "--refresh")
        self.assertGreater(self.calls, 0)


if __name__ == "__main__":
    unittest.main()

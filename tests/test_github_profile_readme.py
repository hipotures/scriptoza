import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))

import github_profile_readme as gpr


def repo(name, fork=False, pushed="2026-01-02T00:00:00Z", **extra):
    return {
        "name": name,
        "fork": fork,
        "html_url": f"https://github.com/me/{name}",
        "pushed_at": pushed,
        "description": f"{name} desc",
        **extra,
    }


def fake_fetch(path):
    if path.startswith("/users/me/repos"):
        return [
            repo("mine", pushed="2026-03-01T00:00:00Z"),
            repo("old", pushed="2025-01-01T00:00:00Z"),
            repo("hidden"),
            repo("archived", archived=True),
            repo("me"),
            repo("changed-fork", fork=True),
            repo("plain-fork", fork=True),
        ]
    if path == "/repos/me/changed-fork" or path == "/repos/me/plain-fork":
        name = path.rsplit("/", 1)[1]
        return {"parent": {"full_name": f"up/{name}", "default_branch": "main"}, "default_branch": "main"}
    if "changed-fork/compare" in path:
        return {"ahead_by": 3}
    if "plain-fork/compare" in path:
        return {"ahead_by": 0}
    raise AssertionError(path)


class BuildSectionsTest(unittest.TestCase):
    def test_classification_and_order(self):
        sections = gpr.build_sections(fake_fetch, "me", {"hide": ["hidden"]})
        projects = sections["PROJECTS"]
        self.assertLess(projects.index("[mine]"), projects.index("[old]"))
        for name in ("hidden", "archived", "changed-fork", "plain-fork"):
            self.assertNotIn(f"[{name}]", projects)
        forks = sections["FORKS"]
        self.assertIn("[changed-fork]", forks)
        self.assertIn("[up/changed-fork](https://github.com/up/changed-fork)", forks)
        self.assertNotIn("plain-fork", forks)

    def test_forced_fork_and_description_override(self):
        config = {"forks": ["plain-fork"], "descriptions": {"plain-fork": "My fix | tweak"}}
        forks = gpr.build_sections(fake_fetch, "me", config)["FORKS"]
        self.assertIn("[plain-fork]", forks)
        self.assertIn("My fix \\| tweak", forks)

    def test_sort_by_name(self):
        projects = gpr.build_sections(fake_fetch, "me", {"sort": "name"})["PROJECTS"]
        self.assertLess(projects.index("[hidden]"), projects.index("[mine]"))


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
        self.assertIn("[mine]", content)
        self.assertIn("[changed-fork]", content)


if __name__ == "__main__":
    unittest.main()

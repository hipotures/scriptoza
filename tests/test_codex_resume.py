"""Offline regression tests for ``codex_resume``.

All Herdr calls are mocked.  The tests exercise target resolution and monitor
state transitions without opening a real pane or sending real input.
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import unittest
from unittest.mock import patch

from ai import codex_resume as monitor_module


def make_tab(tab_id: str, label: str) -> dict[str, str]:
    return {"tab_id": tab_id, "label": label}


def make_pane(pane_id: str, tab_id: str = "tab-1", label: str = "resume") -> dict[str, str]:
    return {"pane_id": pane_id, "tab_id": tab_id, "label": label, "workspace_id": "workspace-1"}


def read_call(pane_id: str) -> tuple[str, ...]:
    return ("pane", "read", pane_id, "--source", "visible", "--format", "text")


def real_capacity_error(
    context: tuple[str, ...] = (), body: str = monitor_module.CAPACITY_MESSAGE
) -> str:
    """Build a visible capacity error whose first line has Herdr's real marker."""
    return "\n".join((*context, f"  ■ {body}"))


def error_at_row(
    row: int, context: tuple[str, ...], body: str = monitor_module.CAPACITY_MESSAGE
) -> str:
    """Place a marked capacity error at an exact one-based screen row."""
    padding = tuple(f"transcript-{index}" for index in range(row - 1 - len(context)))
    return real_capacity_error((*padding, *context), body)


def extra_thought_menu(
    marker: str | None = "›", wrapped: bool = False, selected_option: int = 1
) -> str:
    lines = [
        "Giving this request a little extra thought",
        "If you’d rather not wait, retry with a faster model. It may be less capable of handling complex requests.",
        "1. Retry with a faster model",
        "2. Dismiss and keep waiting",
        "3. Learn more",
        "No action is required. Codex will keep waiting and this menu will close when the response is ready.",
    ]
    selected_line = 1 + selected_option
    if marker is not None:
        lines[selected_line] = f"{marker} {lines[selected_line]}"
    else:
        lines[selected_line] = f"  {lines[selected_line]}"
    if wrapped:
        lines[0] = lines[0].replace("request", "requ\nest")
        for word in ("Retry", "Dismiss", "Learn"):
            if word in lines[selected_line]:
                lines[selected_line] = lines[selected_line].replace(
                    word, f"{word[:2]}\n{word[2:]}", 1
                )
                break
        lines[4] = lines[4].replace("Learn", "Le\narn")
    return "\n".join(lines)


class TargetResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tabs = [make_tab("tab-1", "first"), make_tab("tab-2", "second")]
        self.panes = [
            make_pane("pane-1", "tab-1"),
            make_pane("pane-2", "tab-1"),
            make_pane("pane-3", "tab-2", "other"),
        ]

    def test_shared_pane_label_selects_every_matching_pane(self) -> None:
        selected = monitor_module.resolve_targets("pane", ["resume"], [], self.panes)

        self.assertEqual(set(selected), {"pane-1", "pane-2"})

    def test_duplicate_selectors_are_deduplicated(self) -> None:
        selected = monitor_module.resolve_targets(
            "pane", ["resume", "pane-1", "pane-1"], [], self.panes
        )

        self.assertEqual(set(selected), {"pane-1", "pane-2"})
        self.assertEqual(len(selected), 2)

    def test_tab_selection_includes_all_tab_members_and_pane_selection_selects_one(self) -> None:
        self.assertEqual(
            set(monitor_module.resolve_targets("tab", ["first"], self.tabs, self.panes)),
            {"pane-1", "pane-2"},
        )
        self.assertEqual(
            set(monitor_module.resolve_targets("tab", ["tab-1"], self.tabs, self.panes)),
            {"pane-1", "pane-2"},
        )
        self.assertEqual(
            set(monitor_module.resolve_targets("pane", ["pane-2"], [], self.panes)),
            {"pane-2"},
        )

    def test_exact_id_wins_over_another_pane_label(self) -> None:
        panes = [
            make_pane("pane-1", label="ordinary"),
            make_pane("pane-2", label="pane-1"),
        ]

        selected = monitor_module.resolve_targets("pane", ["pane-1"], [], panes)

        self.assertEqual(set(selected), {"pane-1"})

    def test_target_kind_scopes_same_label(self) -> None:
        tabs = [make_tab("tab-collision", "same-name")]
        panes = [make_pane("pane-collision", "tab-collision", "same-name")]

        self.assertEqual(
            set(monitor_module.resolve_targets("pane", ["same-name"], [], panes)),
            {"pane-collision"},
        )
        self.assertEqual(
            set(monitor_module.resolve_targets("tab", ["same-name"], tabs, panes)),
            {"pane-collision"},
        )

    def test_missing_target_and_empty_tab_are_rejected(self) -> None:
        with self.assertRaisesRegex(monitor_module.HerdrError, "Target not found"):
            monitor_module.resolve_targets("pane", ["does-not-exist"], [], self.panes)

        empty_tab = [make_tab("tab-empty", "empty")]
        with self.assertRaisesRegex(monitor_module.HerdrError, "Target has no live panes"):
            monitor_module.resolve_targets("tab", ["empty"], empty_tab, [])


class DiscoveryTests(unittest.TestCase):
    def test_default_discovery_keeps_live_codex_panes_and_ignores_other_or_disappeared_agents(
        self,
    ) -> None:
        panes = [
            make_pane("pane-codex"),
            make_pane("pane-ssh", label="ssh"),
        ]
        agents = [
            {"pane_id": "pane-codex", "agent": "codex"},
            {"pane_id": "pane-ssh", "agent": "ssh"},
            {"pane_id": "pane-gone", "agent": "codex"},
        ]
        inventory_calls: list[str] = []

        def fake_inventory(kind: str) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return panes if kind == "pane" else agents

        with patch.object(monitor_module, "inventory", side_effect=fake_inventory):
            selected = monitor_module.discover_targets([], [])

        self.assertEqual(set(selected), {"pane-codex"})
        self.assertEqual(inventory_calls, ["pane", "agent"])

    def test_discovery_unions_explicit_panes_and_tabs(self) -> None:
        tabs = [make_tab("tab-1", "workspace"), make_tab("tab-2", "other")]
        panes = [
            make_pane("pane-codex", "tab-1", "shared"),
            make_pane("pane-ssh", "tab-1", "ssh"),
            make_pane("pane-tab-only", "tab-1", "tab-only"),
            make_pane("pane-unrelated", "tab-2", "other"),
        ]
        agents = [
            {"pane_id": "pane-codex", "agent": "codex"},
            {"pane_id": "pane-ssh", "agent": "ssh"},
            {"pane_id": "pane-gone", "agent": "codex"},
            {"pane_id": "pane-unrelated", "agent": "other"},
        ]
        inventory_calls: list[str] = []

        def fake_inventory(kind: str) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {"pane": panes, "agent": agents, "tab": tabs}[kind]

        with patch.object(monitor_module, "inventory", side_effect=fake_inventory):
            selected = monitor_module.discover_targets(["shared", "ssh"], ["workspace"])

        self.assertEqual(
            set(selected), {"pane-codex", "pane-ssh", "pane-tab-only"}
        )
        self.assertEqual(inventory_calls, ["pane", "agent", "tab"])


class MonitorTests(unittest.TestCase):
    def test_wrapped_capacity_uses_visible_read_and_one_atomic_run(self) -> None:
        wrapped_body = monitor_module.CAPACITY_MESSAGE.replace("model", "mod\nel").replace(
            "capacity", "capac\nity"
        )
        wrapped = real_capacity_error(body=wrapped_body)
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return wrapped
            self.assertEqual(args[:2], ("pane", "run"))
            return ""

        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor_module.Monitor("resume").poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            calls,
            [
                read_call("pane-1"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )

    def test_unmarked_draft_and_echo_capacity_copies_are_ignored(self) -> None:
        draft = f"Draft: {monitor_module.CAPACITY_MESSAGE}"
        echo = f"  > {monitor_module.CAPACITY_MESSAGE}"
        visible_responses = iter(
            [
                f"{draft}\n{echo}",
                f"{draft}\n{echo}\n{real_capacity_error(('context-1', 'context-2', 'context-3'))}",
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(run_calls, [("pane", "run", "pane-1", "resume")])
        self.assertEqual(monitor.errors["pane-1"][0], 1)

    def test_persistent_error_sends_once_disappearance_rearms_and_count_rise_sends(self) -> None:
        context = ("context-1", "context-2", "context-3")
        one = real_capacity_error(("old row", *context))
        one_after_scroll = real_capacity_error(context)
        two = "\n".join(
            (
                *context,
                f"  ■ {monitor_module.CAPACITY_MESSAGE}",
                f"  ■ {monitor_module.CAPACITY_MESSAGE}",
            )
        )
        visible_responses = iter([one, one_after_scroll, "", one_after_scroll, two, two])
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            for _ in range(6):
                monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(
            run_calls,
            [
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )
        self.assertEqual(monitor.errors["pane-1"][0], 2)

    def test_shifted_up_error_with_unchanged_context_does_not_resend(self) -> None:
        context = ("context-1", "context-2", "context-3")
        visible_responses = iter(
            [
                real_capacity_error(("scrolled-away", *context)),
                real_capacity_error(context),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(run_calls, [("pane", "run", "pane-1", "resume")])
        self.assertEqual(monitor.errors["pane-1"][0], 1)
        self.assertEqual(monitor.errors["pane-1"][1], 4)

    def test_down_shift_with_unchanged_context_does_not_resend(self) -> None:
        context = ("context-1", "context-2", "context-3")
        visible_responses = iter(
            [
                real_capacity_error(context),
                real_capacity_error(("resize-added", *context)),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(run_calls, [("pane", "run", "pane-1", "resume")])
        self.assertEqual(monitor.errors["pane-1"][1], 5)

    def test_same_count_replacement_at_row_48_with_new_context_resends_and_logs_position(
        self,
    ) -> None:
        old_context = ("assistant", "old transcript", "old reasoning")
        new_context = ("assistant", "new transcript", "new reasoning")
        visible_responses = iter(
            [error_at_row(48, old_context), error_at_row(48, new_context)]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        output = StringIO()
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(output):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(
            run_calls,
            [
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )
        self.assertEqual(monitor.errors["pane-1"][1], 48)
        self.assertGreaterEqual(output.getvalue().count("48:"), 2)

    def test_same_count_replacement_at_higher_row_with_new_context_resends(self) -> None:
        old_context = ("assistant", "old transcript", "old reasoning")
        new_context = ("assistant", "new transcript", "new reasoning")
        visible_responses = iter(
            [error_at_row(48, old_context), error_at_row(49, new_context)]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "run")],
            [
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )
        self.assertEqual(monitor.errors["pane-1"][1], 49)

    def test_cold_start_latest_continuation_suppresses_send_case_insensitively(self) -> None:
        visible = (
            f"{real_capacity_error(('context-1', 'context-2', 'context-3'))}\n"
            "  ›   Resume  "
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return visible
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual([call for call in calls if call[:2] == ("pane", "run")], [])
        self.assertEqual(monitor.errors["pane-1"][0], 1)

    def test_cold_start_wrapped_continuation_suppresses_send(self) -> None:
        visible = f"{real_capacity_error(('context-1', 'context-2', 'context-3'))}\n› res\nume"
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return visible
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual([call for call in calls if call[:2] == ("pane", "run")], [])

    def test_non_exact_continuation_text_does_not_suppress_new_error(self) -> None:
        first = real_capacity_error(("context-1", "context-2", "old"))
        second = (
            f"{real_capacity_error(('context-1', 'context-2', 'new'))}\n"
            "› Resume further"
        )
        visible_responses = iter([first, second])
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "run")],
            [
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )

    def test_continuation_before_latest_error_does_not_suppress_send(self) -> None:
        visible = "› resume\n" + real_capacity_error(("context-1", "context-2", "context-3"))
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return visible
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "run")],
            [("pane", "run", "pane-1", "resume")],
        )

    def test_continuation_between_two_errors_does_not_suppress_latest(self) -> None:
        visible = "\n".join(
            [
                *real_capacity_error(("first-1", "first-2", "first-3")).splitlines(),
                "› resume",
                *real_capacity_error(("second-1", "second-2", "second-3")).splitlines(),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return visible
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "run")],
            [("pane", "run", "pane-1", "resume")],
        )
        self.assertEqual(monitor.errors["pane-1"][0], 2)

    def test_failed_read_keeps_detection_state(self) -> None:
        responses = iter(
            [
                real_capacity_error(("context-1", "context-2", "context-3")),
                monitor_module.HerdrError("temporary read failure"),
                real_capacity_error(("context-1", "context-2", "context-3")),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                response = next(responses)
                if isinstance(response, Exception):
                    raise response
                return response
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(run_calls, [("pane", "run", "pane-1", "resume")])
        self.assertEqual(monitor.errors["pane-1"][0], 1)

    def test_failed_send_stops_poll_and_does_not_blindly_retry_same_count(self) -> None:
        calls: list[tuple[str, ...]] = []
        failed = True

        def fake_herdr(*args: str) -> str:
            nonlocal failed
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return real_capacity_error(("context-1", "context-2", "context-3"))
            if failed:
                failed = False
                raise monitor_module.HerdrError("send outcome uncertain")
            return ""

        selected = {
            "pane-1": make_pane("pane-1"),
            "pane-2": make_pane("pane-2"),
        }
        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            with self.assertRaisesRegex(monitor_module.HerdrError, "outcome uncertain"):
                monitor.poll(selected)

            first_poll_calls = list(calls)
            monitor.poll(selected)

        self.assertEqual(
            first_poll_calls,
            [read_call("pane-1"), ("pane", "run", "pane-1", "resume")],
        )
        run_calls = [call for call in calls if call[:2] == ("pane", "run")]
        self.assertEqual(
            run_calls,
            [
                ("pane", "run", "pane-1", "resume"),
                ("pane", "run", "pane-2", "resume"),
            ],
        )
        self.assertEqual(calls.count(read_call("pane-1")), 2)
        self.assertEqual(calls.count(read_call("pane-2")), 1)


class ExtraThoughtMenuTests(unittest.TestCase):
    def test_complete_menu_sends_exact_key_two_without_enter(self) -> None:
        visible = extra_thought_menu(marker="›")
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return visible
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            calls,
            [read_call("pane-1"), ("pane", "send-keys", "pane-1", "2")],
        )
        self.assertFalse(any(call[:2] == ("pane", "run") for call in calls))
        self.assertEqual(monitor.dismissed_menus, {"pane-1"})

    def test_menu_accepts_wrapped_lines_and_all_selection_markers(self) -> None:
        for marker in ("›", ">", "❯"):
            with self.subTest(marker=marker):
                calls: list[tuple[str, ...]] = []

                def fake_herdr(*args: str) -> str:
                    calls.append(args)
                    if args[:2] == ("pane", "read"):
                        return extra_thought_menu(marker=marker, wrapped=True, selected_option=2)
                    return ""

                monitor = monitor_module.Monitor("resume")
                with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
                    StringIO()
                ):
                    monitor.poll({"pane-1": make_pane("pane-1")})

                self.assertEqual(
                    [call for call in calls if call[:2] == ("pane", "send-keys")],
                    [("pane", "send-keys", "pane-1", "2")],
                )

    def test_persistent_menu_sends_once_and_rearms_after_menu_is_absent(self) -> None:
        visible_responses = iter(
            [extra_thought_menu(marker="›"), extra_thought_menu(marker="›"), "prompt", extra_thought_menu(marker="›")]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            for _ in range(4):
                monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "send-keys")],
            [
                ("pane", "send-keys", "pane-1", "2"),
                ("pane", "send-keys", "pane-1", "2"),
            ],
        )

    def test_incomplete_or_quoted_headline_without_exact_menu_does_not_send(self) -> None:
        lines = monitor_module.EXTRA_THOUGHT_MENU_LINES
        variants = {
            "missing option": "\n".join(lines[:3]),
            "quoted headline": "\n".join((f'"{lines[0]}"', *lines[1:])),
            "quoted and incomplete": "\n".join((f'"{lines[0]}"', lines[1], lines[2])),
        }
        for name, visible in variants.items():
            with self.subTest(name=name):
                calls: list[tuple[str, ...]] = []

                def fake_herdr(*args: str) -> str:
                    calls.append(args)
                    if args[:2] == ("pane", "read"):
                        return visible
                    return ""

                monitor = monitor_module.Monitor("resume")
                with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
                    StringIO()
                ):
                    monitor.poll({"pane-1": make_pane("pane-1")})

                self.assertEqual(calls, [read_call("pane-1")])
                self.assertEqual(monitor.dismissed_menus, set())

    def test_dry_run_detects_menu_without_input(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return extra_thought_menu(marker="❯")
            return ""

        monitor = monitor_module.Monitor("resume", dry_run=True)
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(calls, [read_call("pane-1")])
        self.assertEqual(monitor.dismissed_menus, {"pane-1"})

    def test_complete_menu_takes_priority_over_capacity_resume(self) -> None:
        visible_responses = iter(
            [
                extra_thought_menu(marker="›")
                + "\n"
                + real_capacity_error(("context-1", "context-2", "context-3")),
                real_capacity_error(("context-1", "context-2", "context-3")),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return next(visible_responses)
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            calls,
            [
                read_call("pane-1"),
                ("pane", "send-keys", "pane-1", "2"),
                read_call("pane-1"),
                ("pane", "run", "pane-1", "resume"),
            ],
        )

    def test_menu_read_failure_preserves_dismissed_state(self) -> None:
        responses = iter(
            [
                extra_thought_menu(marker="›"),
                monitor_module.HerdrError("temporary read failure"),
                extra_thought_menu(marker="›"),
            ]
        )
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                response = next(responses)
                if isinstance(response, Exception):
                    raise response
                return response
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "send-keys")],
            [("pane", "send-keys", "pane-1", "2")],
        )
        self.assertEqual(monitor.dismissed_menus, {"pane-1"})

    def test_menu_send_failure_halts_and_does_not_repeat_dismissed_pane(self) -> None:
        calls: list[tuple[str, ...]] = []
        failed = True
        menu = extra_thought_menu(marker="›")

        def fake_herdr(*args: str) -> str:
            nonlocal failed
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return menu
            if failed:
                failed = False
                raise monitor_module.HerdrError("send outcome uncertain")
            return ""

        selected = {
            "pane-1": make_pane("pane-1"),
            "pane-2": make_pane("pane-2"),
        }
        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            with self.assertRaisesRegex(monitor_module.HerdrError, "send outcome uncertain"):
                monitor.poll(selected)

            first_poll_calls = list(calls)
            monitor.poll(selected)

        self.assertEqual(
            first_poll_calls,
            [read_call("pane-1"), ("pane", "send-keys", "pane-1", "2")],
        )
        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "send-keys")],
            [
                ("pane", "send-keys", "pane-1", "2"),
                ("pane", "send-keys", "pane-2", "2"),
            ],
        )

    def test_disappearing_selected_pane_clears_menu_state(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return extra_thought_menu(marker="›")
            return ""

        monitor = monitor_module.Monitor("resume")
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            monitor.poll({"pane-1": make_pane("pane-1")})
            self.assertEqual(monitor.dismissed_menus, {"pane-1"})
            monitor.poll({})
            self.assertEqual(monitor.dismissed_menus, set())
            monitor.poll({"pane-1": make_pane("pane-1")})

        self.assertEqual(
            [call for call in calls if call[:2] == ("pane", "send-keys")],
            [
                ("pane", "send-keys", "pane-1", "2"),
                ("pane", "send-keys", "pane-1", "2"),
            ],
        )


class CliTests(unittest.TestCase):
    def test_once_discovers_codex_agents_and_uses_english_default_message(self) -> None:
        panes = [make_pane("pane-1"), make_pane("pane-2")]
        agents = [
            {"pane_id": "pane-1", "agent": "codex"},
            {"pane_id": "pane-2", "agent": "codex"},
        ]
        inventory_calls: list[str] = []
        calls: list[tuple[str, ...]] = []

        def fake_inventory(kind: str) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return panes if kind == "pane" else agents

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return (
                    real_capacity_error(("context-1", "context-2", "context-3"))
                    if args[2] == "pane-1"
                    else "prompt"
                )
            return ""

        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(
            monitor_module, "inventory", side_effect=fake_inventory
        ), patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            result = monitor_module.main(["resume", "--once"])

        self.assertEqual(result, 0)
        self.assertEqual(inventory_calls, ["pane", "agent"])
        self.assertEqual(
            calls,
            [
                read_call("pane-1"),
                ("pane", "run", "pane-1", "Resume"),
                read_call("pane-2"),
            ],
        )

    def test_once_unions_auto_codex_named_ssh_and_overlapping_tab_once_each(self) -> None:
        tabs = [make_tab("tab-1", "workspace"), make_tab("tab-2", "other")]
        panes = [
            make_pane("pane-codex", "tab-1", "shared"),
            make_pane("pane-ssh", "tab-1", "ssh"),
            make_pane("pane-tab-only", "tab-1", "tab-only"),
            make_pane("pane-unrelated", "tab-2", "other"),
        ]
        agents = [
            {"pane_id": "pane-codex", "agent": "codex"},
            {"pane_id": "pane-ssh", "agent": "ssh"},
            {"pane_id": "pane-gone", "agent": "codex"},
            {"pane_id": "pane-unrelated", "agent": "other"},
        ]
        inventory_calls: list[str] = []
        calls: list[tuple[str, ...]] = []

        def fake_inventory(kind: str) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {"pane": panes, "agent": agents, "tab": tabs}[kind]

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            if args[:2] == ("pane", "read"):
                return real_capacity_error(("context-1", "context-2", "context-3"))
            return ""

        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(
            monitor_module, "inventory", side_effect=fake_inventory
        ), patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            StringIO()
        ):
            result = monitor_module.main(
                [
                    "resume",
                    "--panes",
                    " shared , ssh ",
                    "--tabs",
                    " workspace ",
                    "--once",
                ]
            )

        selected_ids = ["pane-codex", "pane-ssh", "pane-tab-only"]
        self.assertEqual(result, 0)
        self.assertEqual(inventory_calls, ["pane", "agent", "tab"])
        self.assertCountEqual(
            [call[2] for call in calls if call[:2] == ("pane", "read")], selected_ids
        )
        self.assertCountEqual(
            [call[2] for call in calls if call[:2] == ("pane", "run")], selected_ids
        )
        self.assertEqual(len(calls), 2 * len(selected_ids))

    def test_outside_herdr_environment_performs_no_control(self) -> None:
        with patch.dict(os.environ, {"HERDR_ENV": "0"}), patch.object(
            monitor_module, "inventory"
        ) as inventory, patch.object(monitor_module, "herdr") as herdr, redirect_stderr(
            StringIO()
        ):
            with self.assertRaises(SystemExit) as raised:
                monitor_module.main(["resume", "--once"])

        self.assertEqual(raised.exception.code, 2)
        inventory.assert_not_called()
        herdr.assert_not_called()

    def test_invalid_interval_is_rejected_before_any_control(self) -> None:
        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(
            monitor_module, "inventory"
        ) as inventory, patch.object(monitor_module, "herdr") as herdr, redirect_stderr(
            StringIO()
        ):
            with self.assertRaises(SystemExit) as raised:
                monitor_module.main(["resume", "--interval=0", "--once"])

        self.assertEqual(raised.exception.code, 2)
        inventory.assert_not_called()
        herdr.assert_not_called()

    def test_ascii_control_characters_in_message_are_rejected(self) -> None:
        for control in ("\x00", "\x1f", "\x7f"):
            with self.subTest(control=ord(control)), patch.dict(
                os.environ, {"HERDR_ENV": "1"}
            ), patch.object(monitor_module, "inventory") as inventory, patch.object(
                monitor_module, "herdr"
            ) as herdr, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    monitor_module.main(
                        ["resume", "--message", f"ok{control}", "--once"]
                    )

            self.assertEqual(raised.exception.code, 2)
            inventory.assert_not_called()
            herdr.assert_not_called()

    def test_selector_list_strips_whitespace_and_rejects_empty_entries(self) -> None:
        self.assertEqual(
            monitor_module.selector_list(" pane-1 , tab-1 "), ["pane-1", "tab-1"]
        )
        for value in ("", "pane-1,", ",pane-1", "pane-1,,pane-2", " , "):
            with self.subTest(value=value):
                with self.assertRaises(monitor_module.argparse.ArgumentTypeError):
                    monitor_module.selector_list(value)

    def test_old_positional_selector_cli_is_rejected(self) -> None:
        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(
            monitor_module, "inventory"
        ) as inventory, patch.object(monitor_module, "herdr") as herdr, redirect_stderr(
            StringIO()
        ):
            with self.assertRaises(SystemExit) as raised:
                monitor_module.main(["pane-1", "--once"])

        self.assertEqual(raised.exception.code, 2)
        inventory.assert_not_called()
        herdr.assert_not_called()


if __name__ == "__main__":
    unittest.main()

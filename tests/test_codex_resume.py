"""Offline regression tests for ``codex_resume``.

All Herdr calls are mocked.  The tests exercise target resolution and monitor
state transitions without opening a real pane or sending real input.
"""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai import codex_resume as monitor_module


def make_tab(
    tab_id: str,
    label: str,
    number: int = 1,
    workspace_id: str = "workspace-1",
) -> dict:
    return {
        "tab_id": tab_id,
        "workspace_id": workspace_id,
        "label": label,
        "number": number,
    }


def make_pane(
    pane_id: str,
    tab_id: str = "tab-1",
    label: str = "resume",
    workspace_id: str = "workspace-1",
    **metadata: str,
) -> dict[str, str]:
    pane = {
        "pane_id": pane_id,
        "tab_id": tab_id,
        "label": label,
        "workspace_id": workspace_id,
    }
    pane.update(metadata)
    return pane


def make_workspace(workspace_id: str = "workspace-1", label: str = "Workspace") -> dict:
    return {"workspace_id": workspace_id, "label": label, "number": 1}


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

    def test_missing_target_and_empty_tab_remain_pending(self) -> None:
        self.assertEqual(
            monitor_module.resolve_targets("pane", ["does-not-exist"], [], self.panes),
            {},
        )

        empty_tab = [make_tab("tab-empty", "empty")]
        self.assertEqual(
            monitor_module.resolve_targets("tab", ["empty"], empty_tab, []),
            {},
        )

    def test_missing_explicit_target_does_not_hide_live_auto_target(self) -> None:
        selected = monitor_module.resolve_targets(
            "pane", ["does-not-exist", "pane-1"], [], self.panes
        )

        self.assertEqual(set(selected), {"pane-1"})


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
        tabs = [make_tab("tab-1", "first")]
        workspaces = [make_workspace()]
        inventory_calls: list[str] = []

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {
                "pane": panes,
                "agent": agents,
                "tab": tabs,
                "workspace": workspaces,
            }[kind]

        with patch.object(monitor_module, "inventory", side_effect=fake_inventory):
            selected = monitor_module.discover_targets([], [])

        self.assertEqual(set(selected), {"pane-codex"})
        self.assertEqual(inventory_calls, ["pane", "agent", "tab", "workspace"])
        self.assertEqual(selected["pane-codex"]["workspace_name"], "Workspace")
        self.assertEqual(selected["pane-codex"]["tab_name"], "first")

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
        workspaces = [make_workspace()]
        inventory_calls: list[str] = []

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {"pane": panes, "agent": agents, "tab": tabs, "workspace": workspaces}[kind]

        with patch.object(monitor_module, "inventory", side_effect=fake_inventory):
            selected = monitor_module.discover_targets(["shared", "ssh"], ["workspace"])

        self.assertEqual(
            set(selected), {"pane-codex", "pane-ssh", "pane-tab-only"}
        )
        self.assertEqual(inventory_calls, ["pane", "agent", "tab", "workspace"])
        self.assertEqual(selected["pane-codex"]["tab_name"], "workspace")

    def test_discovery_uses_workspace_labels_and_fallback_for_unknown_workspace(self) -> None:
        panes = [
            make_pane("pane-named", workspace_id="workspace-named"),
            make_pane("pane-unnamed", workspace_id="workspace-missing"),
        ]
        agents = [
            {"pane_id": "pane-named", "agent": "codex"},
            {"pane_id": "pane-unnamed", "agent": "codex"},
        ]
        tabs = [make_tab("tab-1", "", number=3)]
        workspaces = [make_workspace("workspace-named", "V-GPU")]

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            return {
                "pane": panes,
                "agent": agents,
                "tab": tabs,
                "workspace": workspaces,
            }[kind]

        with patch.object(monitor_module, "inventory", side_effect=fake_inventory):
            selected = monitor_module.discover_targets([], [])

        self.assertEqual(selected["pane-named"]["workspace_name"], "V-GPU")
        self.assertEqual(selected["pane-unnamed"]["workspace_name"], "Unnamed workspace")
        self.assertEqual(selected["pane-named"]["tab_name"], "3")
        self.assertEqual(selected["pane-unnamed"]["tab_name"], "3")


class MachineDiscoveryTests(unittest.TestCase):
    def test_machine_profiles_include_only_enabled_machines(self) -> None:
        profiles = [
            {"id": "gpu-id", "label": "gpu", "enabled": True},
            {"id": "cpu-id", "label": "cpu", "enabled": False},
        ]
        with patch.object(monitor_module, "herdr", return_value=json.dumps(profiles)) as herdr:
            self.assertEqual(monitor_module.machine_profiles(), profiles[:1])
        herdr.assert_called_once_with("machine", "list", "--json")

    def test_invalid_machine_inventory_is_fatal(self) -> None:
        for response in ("invalid", "{}", '[{"id":"gpu"}]'):
            with self.subTest(response=response), patch.object(monitor_module, "herdr", return_value=response):
                with self.assertRaises(monitor_module.HerdrError):
                    monitor_module.machine_profiles()

    def test_remote_inventory_uses_machine_prefix(self) -> None:
        with patch.object(monitor_module, "herdr", return_value='{"result":{"agents":[]}}') as herdr:
            self.assertEqual(monitor_module.inventory("agent", "gpu-id"), [])
        herdr.assert_called_once_with("--machine", "gpu-id", "agent", "list")

    def test_all_servers_discover_agents_and_additional_selectors(self) -> None:
        profiles = [{"id": "gpu-id", "label": "gpu", "enabled": True}]

        def fake_inventory(kind, machine=None):
            return {
                "pane": [make_pane("w9:p1", label="codex"), make_pane("w9:p2", label="extra")],
                "agent": [{"pane_id": "w9:p1", "agent": "codex"}],
                "tab": [make_tab("tab-1", "1")],
                "workspace": [make_workspace(label="phase1" if machine else "local")],
            }[kind]

        with patch.object(monitor_module, "machine_profiles", return_value=profiles), patch.object(
            monitor_module, "inventory", side_effect=fake_inventory
        ):
            selected, errors = monitor_module.discover_all_targets(["extra"], ["1"], {})
        self.assertEqual(errors, {})
        self.assertEqual(set(selected), {"w9:p1", "w9:p2", "gpu-id/w9:p1", "gpu-id/w9:p2"})
        self.assertEqual(monitor_module.describe_pane(selected["gpu-id/w9:p1"]), "gpu/phase1:1:codex")

    def test_same_pane_id_on_multiple_servers_routes_input_and_deduplicates_independently(self) -> None:
        local = make_pane("w9:p1")
        remote = {**local, "machine_id": "gpu-id", "machine_name": "gpu"}
        selected = {"w9:p1": local, "gpu-id/w9:p1": remote}
        for visible, action in (
            ("\n".join(monitor_module.EXTRA_THOUGHT_MENUS["1"]), ("send-keys", "1")),
            (real_capacity_error(), ("run", "Resume")),
        ):
            with self.subTest(action=action):
                calls = []

                def fake_herdr(*args):
                    calls.append(args)
                    command = args[2:] if args[0] == "--machine" else args
                    return visible if command[:2] == ("pane", "read") else ""

                monitor = monitor_module.Monitor("Resume")
                with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(StringIO()):
                    monitor.poll(selected)
                    monitor.poll(selected)
                self.assertEqual(calls, [
                    read_call("w9:p1"),
                    ("pane", action[0], "w9:p1", action[1]),
                    ("--machine", "gpu-id", *read_call("w9:p1")),
                    ("--machine", "gpu-id", "pane", action[0], "w9:p1", action[1]),
                    read_call("w9:p1"),
                    ("--machine", "gpu-id", *read_call("w9:p1")),
                ])

    def test_failed_remote_discovery_preserves_state_without_input_and_recovers(self) -> None:
        profiles = [{"id": "gpu-id", "label": "gpu", "enabled": True}]
        remote = {**make_pane("w9:p1"), "machine_id": "gpu-id", "machine_name": "gpu"}
        previous = {"gpu-id/w9:p1": remote}

        def failed_discovery(panes, tabs, machine):
            if machine:
                raise monitor_module.HerdrError("unreachable")
            return {"local": make_pane("local")}

        monitor = monitor_module.Monitor("Resume")
        monitor.dismissed_menus.add("gpu-id/w9:p1")
        monitor.errors["gpu-id/w9:p1"] = (1, 1, "context")
        monitor.pane_descriptions["gpu-id/w9:p1"] = monitor_module.describe_pane(remote)
        with patch.object(monitor_module, "machine_profiles", return_value=profiles), patch.object(
            monitor_module, "discover_targets", side_effect=failed_discovery
        ):
            selected, errors = monitor_module.discover_all_targets([], [], previous)
        self.assertEqual(errors, {"gpu": "unreachable"})
        self.assertTrue(selected["gpu-id/w9:p1"]["discovery_failed"])
        with patch.object(monitor_module, "herdr", return_value="prompt") as herdr, redirect_stdout(StringIO()):
            monitor.poll(selected)
        herdr.assert_called_once_with(*read_call("local"))
        self.assertIn("gpu-id/w9:p1", monitor.dismissed_menus)
        self.assertEqual(monitor.errors["gpu-id/w9:p1"], (1, 1, "context"))

        def recovered_discovery(panes, tabs, machine):
            return {"w9:p1": make_pane("w9:p1")} if machine else {}

        with patch.object(monitor_module, "machine_profiles", return_value=profiles), patch.object(
            monitor_module, "discover_targets", side_effect=recovered_discovery
        ):
            selected, errors = monitor_module.discover_all_targets([], [], selected)
        self.assertEqual(errors, {})
        self.assertNotIn("discovery_failed", selected["gpu-id/w9:p1"])
        visible = "\n".join(monitor_module.EXTRA_THOUGHT_MENUS["1"])
        with patch.object(monitor_module, "herdr", return_value=visible) as herdr, redirect_stdout(StringIO()):
            monitor.poll(selected)
        herdr.assert_called_once_with("--machine", "gpu-id", *read_call("w9:p1"))

    def test_remote_discovery_continues_when_local_server_is_down(self) -> None:
        profiles = [{"id": "gpu-id", "label": "gpu", "enabled": True}]

        def fake_discovery(panes, tabs, machine):
            if not machine:
                raise monitor_module.HerdrError("local unavailable")
            return {"w9:p1": make_pane("w9:p1")}

        with patch.object(monitor_module, "machine_profiles", return_value=profiles), patch.object(
            monitor_module, "discover_targets", side_effect=fake_discovery
        ):
            selected, errors = monitor_module.discover_all_targets([], [], {})
        self.assertEqual(set(selected), {"gpu-id/w9:p1"})
        self.assertEqual(errors, {"Local": "local unavailable"})

    def test_removed_profile_drops_its_previous_panes(self) -> None:
        previous = {"gpu-id/w9:p1": {**make_pane("w9:p1"), "machine_id": "gpu-id"}}
        with patch.object(monitor_module, "machine_profiles", return_value=[]), patch.object(
            monitor_module, "discover_targets", return_value={}
        ):
            selected, errors = monitor_module.discover_all_targets([], [], previous)
        self.assertEqual(selected, {})
        self.assertEqual(errors, {})

    def test_all_servers_unavailable_raise_without_discarding_previous_targets(self) -> None:
        previous = {"w9:p1": make_pane("w9:p1")}
        with patch.object(monitor_module, "machine_profiles", return_value=[]), patch.object(
            monitor_module, "discover_targets", side_effect=monitor_module.HerdrError("unreachable")
        ):
            with self.assertRaisesRegex(monitor_module.HerdrError, "Local: unreachable"):
                monitor_module.discover_all_targets([], [], previous)
        self.assertEqual(previous, {"w9:p1": make_pane("w9:p1")})


class DisplayTests(unittest.TestCase):
    def test_describe_pane_prefers_panel_label_and_collapses_whitespace(self) -> None:
        self.assertEqual(
            monitor_module.describe_pane(
                {
                    "workspace_name": "V-GPU",
                    "tab_name": "kontynuuj-2",
                    "pane_id": "w4:p3",
                    "label": " codex\n gpu ",
                }
            ),
            "V-GPU:kontynuuj-2:codex gpu",
        )

    def test_describe_pane_uses_pane_id_suffix_when_unlabeled(self) -> None:
        self.assertEqual(
            monitor_module.describe_pane(
                {
                    "workspace_name": "V-GPU",
                    "tab_name": "3",
                    "pane_id": "w4:pA",
                    "label": "",
                }
            ),
            "V-GPU:3:pA",
        )

    def test_describe_pane_uses_generic_names_when_metadata_is_missing(self) -> None:
        self.assertEqual(
            monitor_module.describe_pane({}),
            "Unnamed workspace:Unnamed tab:Unnamed pane",
        )


class MonitorTests(unittest.TestCase):
    def test_stopped_pane_keeps_human_description(self) -> None:
        calls: list[tuple[str, ...]] = []
        pane = make_pane("pane-1", label="codex-gpu")
        pane["workspace_name"] = "V-GPU"
        pane["tab_name"] = "3"

        def fake_herdr(*args: str) -> str:
            calls.append(args)
            return "prompt" if args[:2] == ("pane", "read") else ""

        monitor = monitor_module.Monitor("resume")
        output = StringIO()
        with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(
            output
        ):
            monitor.poll({"pane-1": pane})
            monitor.poll({})

        self.assertIn("Watching V-GPU:3:codex-gpu", output.getvalue())
        self.assertIn("Stopped watching V-GPU:3:codex-gpu", output.getvalue())
        self.assertNotIn("pane-1", output.getvalue())

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
    def test_two_option_menu_sends_key_one_once_and_rearms(self) -> None:
        for marker in ("›", ">", "❯", ""):
            for wrapped in (False, True):
                with self.subTest(marker=marker, wrapped=wrapped):
                    headline, dismiss, learn = monitor_module.EXTRA_THOUGHT_MENUS["1"]
                    visible = "\n".join((headline, f"{marker} {dismiss}", learn))
                    if wrapped:
                        visible = visible.replace("request", "requ\nest").replace(
                            "Dismiss", "Di\nsmiss"
                        ).replace("Learn", "Le\narn")
                    responses = iter((visible, visible, "prompt", visible))
                    calls = []

                    def fake_herdr(*args: str) -> str:
                        calls.append(args)
                        if args[:2] == ("pane", "read"):
                            return next(responses)
                        return ""

                    monitor = monitor_module.Monitor("resume")
                    with patch.object(monitor_module, "herdr", side_effect=fake_herdr), redirect_stdout(StringIO()):
                        for _ in range(4):
                            monitor.poll({"pane-1": make_pane("pane-1")})

                    self.assertEqual(
                        calls,
                        [
                            read_call("pane-1"),
                            ("pane", "send-keys", "pane-1", "1"),
                            read_call("pane-1"),
                            read_call("pane-1"),
                            read_call("pane-1"),
                            ("pane", "send-keys", "pane-1", "1"),
                        ],
                    )

    def test_two_option_menu_dry_run_reports_key_one(self) -> None:
        visible = "\n".join(monitor_module.EXTRA_THOUGHT_MENUS["1"])
        output = StringIO()
        with patch.object(monitor_module, "herdr", return_value=visible) as herdr, redirect_stdout(output):
            monitor_module.Monitor("resume", dry_run=True).poll({"pane-1": make_pane("pane-1")})
        herdr.assert_called_once_with(*read_call("pane-1"))
        self.assertIn("would press 1 (Dismiss and keep waiting)", output.getvalue())

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
        lines = monitor_module.EXTRA_THOUGHT_MENUS["2"]
        variants = {
            "missing option": "\n".join(lines[:3]),
            "quoted headline": "\n".join((f'"{lines[0]}"', *lines[1:])),
            "quoted and incomplete": "\n".join((f'"{lines[0]}"', lines[1], lines[2])),
            "two-option missing learn more": "\n".join(monitor_module.EXTRA_THOUGHT_MENUS["1"][:2]),
            "two-option quoted headline": "\n".join((f'"{lines[0]}"', *monitor_module.EXTRA_THOUGHT_MENUS["1"][1:])),
            "mixed option numbering": "\n".join((lines[0], "1. Dismiss and keep waiting", "3. Learn more")),
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
    def setUp(self) -> None:
        profiles = patch.object(monitor_module, "machine_profiles", return_value=[])
        profiles.start()
        self.addCleanup(profiles.stop)
        self.runtime_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime_directory.cleanup)
        self.runtime_environment = patch.dict(
            os.environ,
            {"XDG_RUNTIME_DIR": self.runtime_directory.name},
            clear=False,
        )
        self.runtime_environment.start()
        self.addCleanup(self.runtime_environment.stop)

    def test_once_discovers_codex_agents_and_uses_english_default_message(self) -> None:
        panes = [make_pane("pane-1"), make_pane("pane-2")]
        agents = [
            {"pane_id": "pane-1", "agent": "codex"},
            {"pane_id": "pane-2", "agent": "codex"},
        ]
        tabs = [make_tab("tab-1", "first")]
        workspaces = [make_workspace()]
        inventory_calls: list[str] = []
        calls: list[tuple[str, ...]] = []

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {
                "pane": panes,
                "agent": agents,
                "tab": tabs,
                "workspace": workspaces,
            }[kind]

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
        self.assertEqual(inventory_calls, ["pane", "agent", "tab", "workspace"])
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
        workspaces = [make_workspace()]
        inventory_calls: list[str] = []
        calls: list[tuple[str, ...]] = []

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            inventory_calls.append(kind)
            return {"pane": panes, "agent": agents, "tab": tabs, "workspace": workspaces}[kind]

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
        self.assertEqual(inventory_calls, ["pane", "agent", "tab", "workspace"])
        self.assertCountEqual(
            [call[2] for call in calls if call[:2] == ("pane", "read")], selected_ids
        )
        self.assertCountEqual(
            [call[2] for call in calls if call[:2] == ("pane", "run")], selected_ids
        )
        self.assertEqual(len(calls), 2 * len(selected_ids))

    def test_outside_herdr_environment_is_allowed(self) -> None:
        with patch.dict(os.environ, {"HERDR_ENV": "0"}), patch.object(
            monitor_module, "inventory", return_value=[]
        ) as inventory, patch.object(monitor_module, "herdr") as herdr, redirect_stdout(
            StringIO()
        ):
            result = monitor_module.main(["resume", "--once"])

        self.assertEqual(result, 0)
        self.assertEqual(inventory.call_count, 4)
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


class RuntimeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        profiles = patch.object(monitor_module, "machine_profiles", return_value=[])
        profiles.start()
        self.addCleanup(profiles.stop)
        self.runtime_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime_directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {"XDG_RUNTIME_DIR": self.runtime_directory.name},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_list_reports_partial_machine_errors_and_watched_remote_panes(self) -> None:
        state = monitor_module.RuntimeState()
        state.acquire()
        self.addCleanup(state.release)
        state.write_status(
            status="watching", message="Resume", dry_run=False,
            panes=["gpu/phase1:1:p1"], error="cpu: unreachable",
        )
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(monitor_module.list_status(), 0)
        self.assertIn("Error: cpu: unreachable", output.getvalue())
        self.assertIn("gpu/phase1:1:p1", output.getvalue())

    def test_lock_is_exclusive_and_lock_file_survives_release(self) -> None:
        first = monitor_module.RuntimeState()
        second = monitor_module.RuntimeState()
        first.acquire()
        self.addCleanup(first.release)

        with self.assertRaises(monitor_module.MonitorAlreadyRunning):
            second.acquire()

        first.release()
        self.assertTrue(first.lock_path.exists())
        second.acquire()
        second.release()

    def test_status_snapshot_is_atomic_and_contains_human_panes(self) -> None:
        state = monitor_module.RuntimeState()
        state.write_status(
            status="watching",
            message="Kontynuuj",
            dry_run=False,
            panes=("V-GPU:1:codex-gpu",),
            last_check="2026-10-05T12:00:00+00:00",
        )

        snapshot, error = state.read_status()
        self.assertIsNone(error)
        self.assertEqual(snapshot["panes"], ["V-GPU:1:codex-gpu"])
        self.assertEqual(snapshot["message"], "Kontynuuj")
        self.assertTrue(state.status_path.exists())
        self.assertEqual(list(state.directory.glob("*.tmp")), [])

    def test_list_reports_active_stale_and_does_not_call_herdr(self) -> None:
        state = monitor_module.RuntimeState()
        state.acquire()
        self.addCleanup(state.release)
        state.write_status(
            status="stale",
            message="Resume",
            dry_run=False,
            last_panes=("V-GPU:1:codex-gpu",),
            error="discovery failed for w4:p1",
            last_check="2026-10-05T12:00:00+00:00",
        )
        output = StringIO()
        with patch.object(monitor_module, "herdr") as herdr, redirect_stdout(output):
            result = monitor_module.main(["list"])

        self.assertEqual(result, 0)
        self.assertIn("discovery is stale", output.getvalue())
        self.assertIn("Error: discovery failed", output.getvalue())
        self.assertNotIn("w4:p1", output.getvalue())
        self.assertIn("V-GPU:1:codex-gpu", output.getvalue())
        self.assertNotIn("w4:p", output.getvalue())
        herdr.assert_not_called()

    def test_list_reports_inactive_even_with_stale_snapshot(self) -> None:
        state = monitor_module.RuntimeState()
        state.write_status(
            status="watching",
            message="Resume",
            dry_run=False,
            panes=("V-GPU:1:codex-gpu",),
            last_check="2026-10-05T12:00:00+00:00",
        )
        output = StringIO()
        with patch.object(monitor_module, "herdr") as herdr, redirect_stdout(output):
            result = monitor_module.main(["list"])

        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue().strip(), "Monitor is not running")
        herdr.assert_not_called()

    def test_once_cleans_status_but_keeps_lock_file(self) -> None:
        with patch.object(monitor_module, "inventory", return_value=[]), patch.object(
            monitor_module, "herdr"
        ):
            result = monitor_module.main(["resume", "--once"])

        state = monitor_module.RuntimeState()
        self.assertEqual(result, 0)
        self.assertFalse(state.status_path.exists())
        self.assertTrue(state.lock_path.exists())

    def test_duplicate_monitor_is_denied_before_discovery(self) -> None:
        state = monitor_module.RuntimeState()
        state.acquire()
        self.addCleanup(state.release)
        with patch.object(monitor_module, "inventory") as inventory, patch.object(
            monitor_module, "herdr"
        ) as herdr, redirect_stderr(StringIO()):
            result = monitor_module.main(["resume", "--once"])

        self.assertEqual(result, 1)
        inventory.assert_not_called()
        herdr.assert_not_called()

    def test_uncertain_send_returns_exit_code_two(self) -> None:
        panes = [make_pane("pane-1")]
        agents = [{"pane_id": "pane-1", "agent": "codex"}]
        tabs = [make_tab("tab-1", "first")]
        workspaces = [make_workspace()]

        def fake_inventory(kind: str, machine=None) -> list[dict[str, str]]:
            return {
                "pane": panes,
                "agent": agents,
                "tab": tabs,
                "workspace": workspaces,
            }[kind]

        def fake_herdr(*args: str) -> str:
            if args[:2] == ("pane", "read"):
                return real_capacity_error(("context-1", "context-2", "context-3"))
            raise monitor_module.HerdrError("send outcome uncertain")

        error = StringIO()
        with patch.object(monitor_module, "inventory", side_effect=fake_inventory), patch.object(
            monitor_module, "herdr", side_effect=fake_herdr
        ), patch.object(
            monitor_module.RuntimeState,
            "clear_status",
            side_effect=OSError("cleanup failed"),
        ), redirect_stderr(error), redirect_stdout(StringIO()):
            result = monitor_module.main(["resume", "--once"])

        self.assertEqual(result, 2)
        self.assertIn("Input delivery uncertain", error.getvalue())

    def test_once_dry_run_bypasses_lock_and_state(self) -> None:
        state = monitor_module.RuntimeState()
        state.acquire()
        self.addCleanup(state.release)
        with patch.object(monitor_module, "inventory", return_value=[]), patch.object(
            monitor_module, "herdr"
        ) as herdr, redirect_stdout(StringIO()):
            result = monitor_module.main(["resume", "--once", "--dry-run"])

        self.assertEqual(result, 0)
        state_snapshot, error = state.read_status()
        self.assertIsNone(state_snapshot)
        self.assertIn("not available", error)
        herdr.assert_not_called()


if __name__ == "__main__":
    unittest.main()

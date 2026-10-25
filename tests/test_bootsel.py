import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "utils" / "bootsel.sh"
STATE = """BootCurrent: 000A
BootNext: 0002
BootOrder: 0002,000A,0003
Boot0002* proxmox\tHD(1,GPT,example)/File(\\EFI\\proxmox\\shimx64.efi)
Boot000A* ubuntu\tHD(1,GPT,example)/File(\\EFI\\ubuntu\\shimx64.efi) optional-data
Boot0003* Windows Boot Manager\tHD(1,GPT,example)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)
"""


class BootselTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.write_text(STATE)
        self.log = self.root / "calls"
        for name, body in {
            "id": "#!/bin/bash\necho 0\n",
            "sudo": "#!/bin/bash\necho 'Unexpected sudo' >&2\nexit 99\n",
            "efibootmgr": """#!/bin/bash
printf '%s\\n' "$*" >> "$BOOTSEL_LOG"
if [[ "$*" == -v ]]; then
    cat "$BOOTSEL_STATE"
elif [[ -n "${BOOTSEL_FAIL:-}" && "$1" == "$BOOTSEL_FAIL" ]]; then
    echo 'Firmware write failed' >&2
    exit 1
fi
""",
        }.items():
            path = self.root / name
            path.write_text(body)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}",
                        BOOTSEL_STATE=str(self.state), BOOTSEL_LOG=str(self.log))

    def run_script(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], env=self.env,
                              text=True, capture_output=True)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_no_arguments_shows_usage_and_full_efi_details(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage: bootsel", result.stdout)
        self.assertIn("--once", result.stdout)
        self.assertIn("BootCurrent: 000A", result.stdout)
        self.assertIn("\\EFI\\ubuntu\\shimx64.efi) optional-data", result.stdout)
        self.assertEqual(self.calls(), ["-v"])

    def test_dry_run_does_not_write(self):
        result = self.run_script("UBUNTU")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Permanent BootOrder: 000A,0002,0003", result.stdout)
        self.assertEqual(result.stdout.count("DRY RUN"), 2)
        self.assertEqual(self.calls(), ["-v"])

    def test_permanent_preserves_order_and_clears_override(self):
        result = self.run_script("ubuntu", "--run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["-v", "-o 000A,0002,0003", "-N", "-v"])

    def test_once_with_spaces_only_writes_bootnext(self):
        result = self.run_script("--run", "Windows Boot Manager", "--once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["-v", "-n 0003", "-v"])

    def test_single_entry_order_and_no_pending_override(self):
        self.state.write_text("BootOrder: 000a\nBoot000A* ubuntu\n")
        result = self.run_script("ubuntu", "--run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["-v", "-o 000A", "-v"])

    def test_duplicate_label_is_rejected(self):
        self.state.write_text(STATE + "Boot00FF* UBUNTU\tFile(other.efi)\n")
        result = self.run_script("ubuntu", "--run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple UEFI entries", result.stderr)
        self.assertEqual(self.calls(), ["-v"])

    def test_label_is_literal_and_exact(self):
        result = self.run_script("ubun.*", "--run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No UEFI entry", result.stderr)
        self.assertEqual(self.calls(), ["-v"])

    def test_invalid_arguments_do_not_access_firmware(self):
        for args in [("ubuntu", "extra"), ("--run",), ("--once",),
                     ("ubuntu", "--wrong"), ("",)]:
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_missing_order_is_rejected_for_permanent_selection(self):
        self.state.write_text("Boot000A* ubuntu\n")
        result = self.run_script("ubuntu", "--run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BootOrder is missing", result.stderr)
        self.assertEqual(self.calls(), ["-v"])

    def test_bootnext_clear_failure_reports_partial_change(self):
        self.env["BOOTSEL_FAIL"] = "-N"
        result = self.run_script("ubuntu", "--run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BootOrder was changed", result.stderr)
        self.assertNotIn("UEFI changes applied.", result.stdout)

    def test_order_write_failure_does_not_clear_bootnext(self):
        self.env["BOOTSEL_FAIL"] = "-o"
        result = self.run_script("ubuntu", "--run")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["-v", "-o 000A,0002,0003"])


if __name__ == "__main__":
    unittest.main()

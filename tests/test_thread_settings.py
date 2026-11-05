"""Run with python3 -B -m unittest discover -s tests; no radio or dependencies needed."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "openthread_border_router/rootfs/etc/s6-overlay/scripts"
)
MOCK_CTL = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
with open(os.environ["COMMANDS"], "a") as log:
    log.write(json.dumps(args) + "\n")
limit = int(os.environ.get("FAIL_COUNT", "0"))
matches = sum(json.loads(line) == args
              for line in Path(os.environ["COMMANDS"]).read_text().splitlines())
if (args == json.loads(os.environ.get("FAIL_COMMAND", "null"))
        and (not limit or matches <= limit)):
    mode = os.environ.get("FAIL_MODE", "cli")
    if mode == "hang":
        time.sleep(60)
    print("Error 7: InvalidArgs")
    sys.exit(7 if mode == "exit" else 0)
if args == ["state"]:
    counter = Path(os.environ["COMMANDS"] + ".state")
    index = int(counter.read_text()) if counter.exists() else 0
    states = json.loads(os.environ.get("STATES", '["router"]'))
    print(states[min(index, len(states) - 1)] + "\r")
    counter.write_text(str(index + 1))
elif args == ["br", "omrprefix", "local"]:
    print(os.environ.get("OMR_PREFIX", "fd00:1::/64") + "\r")
print("Done\r")
"""


class ThreadSettingsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "thread"
        self.data.mkdir()
        self.counter = self.data / "srp-anycast-sequence"
        self.commands = self.root / "commands"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        ctl = self.bin / "ot-ctl"
        ctl.write_text(MOCK_CTL)
        ctl.chmod(0o755)
        timeout = shutil.which("timeout") or shutil.which("gtimeout")
        if not timeout:
            self.skipTest("GNU timeout is required (gtimeout on macOS)")
        (self.bin / "timeout").symlink_to(timeout)

    def run_settings(self, options=None, script="thread-settings", **environment):
        options = options or {}
        config = "bashio::config() { case \"$1\" in\n"
        for key, value in options.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            config += f"{shlex.quote(key)}) printf '%s\\n' {shlex.quote(value)} ;;\n"
        config += "*) return 0 ;; esac; }\n"
        config += r"""
bashio::config.has_value() { [[ -n "$(bashio::config "$1")" ]]; }
bashio::config.true() { [[ "$(bashio::config "$1")" == true ]]; }
bashio::log.warning() { echo "WARNING: $*" >&2; }
bashio::log.info() { echo "$*"; }
hostname() { echo test; }
sleep() { SECONDS=$((SECONDS + $1)); }
"""
        # Relocate only container paths; run the shipped script with bashio's
        # errexit behavior and an ot-ctl executable on PATH.
        source = (SCRIPTS / f"otbr-agent-{script}.sh").read_text()
        source = source.replace(
            ". /etc/s6-overlay/scripts/otbr-agent-common",
            ". " + shlex.quote(str(SCRIPTS / "otbr-agent-common")),
        ).replace("/data/thread", shlex.quote(str(self.data)))
        self.commands.write_text("")
        self.commands.with_suffix(".state").unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-Eeuo", "pipefail", "-c", config + source],
            env={
                **os.environ,
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "COMMANDS": str(self.commands),
                **{key: json.dumps(value) for key, value in environment.items()
                   if key in ("STATES", "FAIL_COMMAND")},
                **{key: value for key, value in environment.items()
                   if key not in ("STATES", "FAIL_COMMAND")},
            },
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.commands.read_text().splitlines()]
        return calls, result.stderr

    def test_defaults_and_legacy_options(self):
        for options in ({}, {"tx_power": 6, "take_leadership": False,
                             "srp_anycast": False, "srp_anycast_sequence_number": 0}):
            with self.subTest(options=options):
                calls, _ = self.run_settings(options, script="configure")
                self.assertEqual(calls, [["trel", "enable"],
                                        ["mdns", "localhostname", "test-otbr"],
                                        ["mdns", "enable"], ["txpower", "6"]])
                calls, _ = self.run_settings(options, STATES=["disabled"])
                self.assertEqual(calls, [])
                self.assertEqual(list(self.data.iterdir()), [])

    def test_radio_and_existing_nat64_settings(self):
        calls, _ = self.run_settings({"tx_power": -4, "nat64": True}, script="configure")
        self.assertIn(["nat64", "enable"], calls)
        self.assertIn(["dns", "server", "upstream", "enable"], calls)
        self.assertEqual(calls[-1], ["txpower", "-4"])

    def test_attachment_and_role_changes(self):
        for states, takeover in ((["disabled", "detached", "child"], True),
                                 (["router"], True), (["leader"], False),
                                 (["router", "leader"], False)):
            with self.subTest(states=states):
                calls, _ = self.run_settings(
                    {"leader_weight": 80, "omr_preference": "high", "take_leadership": True},
                    STATES=states,
                )
                self.assertEqual(calls[0], ["leaderweight", "80"])
                self.assertIn(["br", "omrconfig", "custom", "fd00:1::/64", "high"], calls)
                self.assertEqual(["state", "leader"] in calls, takeover)

    def test_attachment_timeout(self):
        for state in ("disabled", "detached"):
            with self.subTest(state=state):
                calls, warning = self.run_settings(
                    {"omr_preference": "med", "take_leadership": True}, STATES=[state]
                )
                self.assertGreater(len(calls), 1)
                self.assertLessEqual(len(calls), 60)
                self.assertTrue(all(call == ["state"] for call in calls))
                self.assertIn("restart the app after commissioning", warning)

    def test_invalid_or_unavailable_prefix(self):
        for extra in ({"OMR_PREFIX": "unexpected"},
                      {"FAIL_COMMAND": ["br", "omrprefix", "local"]}):
            with self.subTest(extra=extra):
                calls, warning = self.run_settings({"omr_preference": "low"}, **extra)
                self.assertFalse(any(call[:2] == ["br", "omrconfig"] for call in calls))
                self.assertIn("WARNING", warning)

    def test_anycast_sequence_lifecycle(self):
        cases = [(None, 250, 250), ("250 250\n", 250, 251),
                 ("250 255\n", 250, 0), ("250 3\n", 40, 40),
                 ("invalid\n", 40, 40), ("40 999\n", 40, 40),
                 ("40 009\n", 40, 10), ("40 8\nextra\n", 40, 40)]
        for previous, seed, expected in cases:
            with self.subTest(previous=previous, seed=seed):
                self.counter.unlink(missing_ok=True)
                if previous is not None:
                    self.counter.write_text(previous)
                calls, _ = self.run_settings(
                    {"srp_anycast": True, "srp_anycast_sequence_number": seed}
                )
                self.assertEqual(calls, [["srp", "server", "disable"],
                                        ["srp", "server", "seqnum", str(expected)],
                                        ["srp", "server", "addrmode", "anycast"],
                                        ["srp", "server", "auto", "enable"]])
                self.assertEqual(self.counter.read_text(), f"{seed} {expected}\n")
        calls, _ = self.run_settings({"srp_anycast": True})
        self.assertIn(["srp", "server", "seqnum", "0"], calls)
        calls, _ = self.run_settings({"srp_anycast": True})
        self.assertIn(["srp", "server", "seqnum", "1"], calls)
        before = self.counter.read_text()
        self.run_settings({"srp_anycast": False})
        self.assertEqual(self.counter.read_text(), before)

    def test_anycast_command_failures_restore_auto(self):
        for failed in (["srp", "server", "disable"],
                       ["srp", "server", "addrmode", "anycast"],
                       ["srp", "server", "seqnum", "0"]):
            for mode in ("cli", "exit"):
                with self.subTest(failed=failed, mode=mode):
                    self.counter.unlink(missing_ok=True)
                    calls, warning = self.run_settings(
                        {"srp_anycast": True}, FAIL_COMMAND=failed, FAIL_MODE=mode
                    )
                    self.assertEqual(calls[-1], ["srp", "server", "auto", "enable"])
                    self.assertIn("WARNING", warning)
                    if failed[:3] == ["srp", "server", "seqnum"]:
                        self.assertNotIn(["srp", "server", "addrmode", "anycast"], calls)
        restore = ["srp", "server", "auto", "enable"]
        for limit, attempts in (("1", 2), ("0", 3)):
            for mode in ("cli", "exit"):
                with self.subTest(restore_failures=limit, mode=mode):
                    calls, warning = self.run_settings(
                        {"srp_anycast": True, "omr_preference": "low"},
                        FAIL_COMMAND=restore, FAIL_MODE=mode, FAIL_COUNT=limit,
                    )
                    self.assertEqual(calls.count(restore), attempts)
                    self.assertEqual("Could not restore SRP auto-enable" in warning, limit == "0")
                    self.assertIn(["br", "omrconfig", "custom", "fd00:1::/64", "low"], calls)
                    self.assertNotIn(["srp", "server", "enable"], calls)

    def test_unwritable_counter_keeps_default_srp(self):
        self.data.rmdir()
        calls, warning = self.run_settings({"srp_anycast": True})
        self.assertEqual(calls, [])
        self.assertIn("Cannot save", warning)

    def test_rejected_and_hanging_commands_are_nonfatal(self):
        for mode in ("cli", "exit", "hang"):
            with self.subTest(mode=mode):
                calls, warning = self.run_settings(
                    {"tx_power": 127}, script="configure",
                    FAIL_COMMAND=["txpower", "127"], FAIL_MODE=mode,
                )
                self.assertEqual(calls[-1], ["txpower", "127"])
                self.assertIn("WARNING", warning)


if __name__ == "__main__":
    unittest.main()

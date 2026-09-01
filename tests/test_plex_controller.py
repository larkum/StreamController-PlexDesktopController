import json
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import host_bridge
import plex_x11_helper


class HostBridgeTests(unittest.TestCase):
    @patch("host_bridge.launch_plex")
    @patch("host_bridge.subprocess.run")
    def test_open_plex_focuses_an_existing_window_without_launching_another(self, run, launch):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        host_bridge.send_plex_command(
            "/plugins/plex", "launch", in_flatpak=True
        )
        launch.assert_not_called()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-1], "focus")

    @patch("host_bridge.launch_plex")
    @patch("host_bridge.is_plex_installed", return_value=True)
    @patch("host_bridge.time.sleep")
    @patch("host_bridge.subprocess.run")
    def test_open_plex_launches_once_when_closed(self, run, _sleep, _installed, launch):
        run.side_effect = [
            subprocess.CompletedProcess([], 3, "", "Plex Desktop is not running."),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        host_bridge.send_plex_command(
            "/plugins/plex", "launch", in_flatpak=True
        )
        launch.assert_called_once_with(in_flatpak=True)
        self.assertEqual(run.call_count, 2)

    def test_flatpak_helper_runs_on_the_host_without_a_shell(self):
        command = host_bridge.helper_command("/plugins/plex", "play_pause", in_flatpak=True)
        self.assertEqual(
            command,
            [
                "flatpak-spawn",
                "--host",
                "--directory=/tmp",
                "python3",
                "/plugins/plex/plex_x11_helper.py",
                "play_pause",
            ],
        )

    def test_host_commands_never_inherit_streamcontrollers_private_app_directory(self):
        prefix = host_bridge.host_prefix(in_flatpak=True)
        self.assertIn("--directory=/tmp", prefix)
        self.assertNotIn("/app/bin/StreamController", " ".join(prefix))

    def test_native_helper_uses_the_current_interpreter(self):
        command = host_bridge.helper_command("/plugins/plex", "next", in_flatpak=False)
        self.assertEqual(command[:1], [sys.executable])
        self.assertEqual(command[-1], "next")

    def test_unknown_commands_are_rejected(self):
        with self.assertRaises(ValueError):
            host_bridge.helper_command("/plugins/plex", "delete_everything", in_flatpak=True)

    @patch("host_bridge.subprocess.run")
    def test_status_check_reports_when_plex_is_running(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertTrue(host_bridge.is_plex_running("/plugins/plex", in_flatpak=True))
        self.assertEqual(run.call_args.args[0][-1], "status")

    @patch("host_bridge.subprocess.run")
    def test_status_check_reports_when_plex_is_closed(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 3, "", "Plex Desktop is not running."
        )
        self.assertFalse(host_bridge.is_plex_running("/plugins/plex", in_flatpak=True))

    @patch("host_bridge.subprocess.run")
    def test_successful_control_command_is_sent_once(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        host_bridge.send_plex_command(
            "/plugins/plex", "play_pause", in_flatpak=True
        )
        run.assert_called_once()
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("host_bridge.subprocess.run")
    def test_closed_playback_control_does_not_launch_plex(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 3, "", "Plex Desktop is not running."
        )
        with self.assertRaisesRegex(host_bridge.PlexControlError, "not running"):
            host_bridge.send_plex_command(
                "/plugins/plex", "play_pause", in_flatpak=True
            )
        self.assertEqual(run.call_count, 1)


class X11HelperTests(unittest.TestCase):
    def test_all_commands_have_an_explicit_local_mapping(self):
        mapped = {
            *plex_x11_helper.KEY_COMMANDS,
            *plex_x11_helper.MODIFIED_KEY_COMMANDS,
            *plex_x11_helper.MEDIA_COMMANDS,
            "focus",
            "launch",
        }
        self.assertEqual(mapped, host_bridge.SUPPORTED_COMMANDS - {"status"})

    def test_seek_and_playback_shortcuts_are_stable(self):
        self.assertEqual(plex_x11_helper.KEY_COMMANDS["play_pause"], "space")
        self.assertEqual(plex_x11_helper.KEY_COMMANDS["seek_backward"], "Left")
        self.assertEqual(plex_x11_helper.KEY_COMMANDS["seek_forward"], "Right")

    def test_previous_and_next_use_plex_window_shortcuts_on_linux(self):
        self.assertEqual(
            plex_x11_helper.MODIFIED_KEY_COMMANDS["previous"],
            ("Left", ("Shift_L",)),
        )
        self.assertEqual(
            plex_x11_helper.MODIFIED_KEY_COMMANDS["next"],
            ("Right", ("Shift_L",)),
        )
        self.assertNotIn("previous", plex_x11_helper.MEDIA_COMMANDS)
        self.assertNotIn("next", plex_x11_helper.MEDIA_COMMANDS)

    def test_kde_wayland_uses_ewmh_activation_not_direct_x_focus(self):
        source = (ROOT / "plex_x11_helper.py").read_text(encoding="utf-8")
        self.assertIn("_NET_ACTIVE_WINDOW", source)
        self.assertNotIn("XSetInputFocus", source)


class PackageTests(unittest.TestCase):
    def test_open_action_replaces_the_separate_focus_action(self):
        actions = json.loads((ROOT / "actions.json").read_text(encoding="utf-8"))["actions"]
        self.assertIn("Launch", actions)
        self.assertNotIn("Focus", actions)

    def test_only_open_plex_can_launch_the_application(self):
        actions = json.loads((ROOT / "actions.json").read_text(encoding="utf-8"))["actions"]
        self.assertTrue(all(not action["settings"] for action in actions.values()))
        source = (ROOT / "actions" / "control.py").read_text(encoding="utf-8")
        self.assertNotIn("Launch Plex if closed", source)
        self.assertIn('NOT_RUNNING_MESSAGE = "Plex not running"', source)

    def test_manifest_is_store_ready_version_010(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "com_larkum_PlexDesktopController")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["minimum-app-version"], "1.5.0-beta.16")
        self.assertTrue((ROOT / manifest["thumbnail"]).is_file())

    def test_brand_artwork_is_packaged(self):
        self.assertTrue((ROOT / "assets" / "plex-desktop-controller-icon.png").is_file())
        self.assertTrue((ROOT / "store" / "Thumbnail.png").is_file())

    def test_metadata_json_is_valid(self):
        for name in ("manifest.json", "actions.json", "about.json", "attribution.json"):
            with self.subTest(name=name):
                json.loads((ROOT / name).read_text(encoding="utf-8"))

    def test_store_attribution_has_generic_metadata(self):
        attribution = json.loads((ROOT / "attribution.json").read_text(encoding="utf-8"))
        self.assertEqual(attribution["generic"]["license"], "GPL-3.0")
        self.assertIn("original-url", attribution["generic"])

    def test_every_action_icon_is_valid_svg(self):
        expected = {
            "launch.svg",
            "focus.svg",
            "play-pause.svg",
            "back.svg",
            "forward.svg",
            "previous.svg",
            "next.svg",
            "stop.svg",
            "mute.svg",
            "fullscreen.svg",
        }
        self.assertTrue(expected.issubset({path.name for path in (ROOT / "assets").glob("*.svg")}))
        for name in expected:
            with self.subTest(name=name):
                self.assertEqual(ET.parse(ROOT / "assets" / name).getroot().tag, "{http://www.w3.org/2000/svg}svg")

    def test_plugin_has_no_third_party_python_dependencies(self):
        bridge_source = (ROOT / "host_bridge.py").read_text(encoding="utf-8")
        helper_source = (ROOT / "plex_x11_helper.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", bridge_source)
        self.assertNotIn("xdotool", bridge_source + helper_source)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


PLEX_APP_ID = "tv.plex.PlexDesktop"
SUPPORTED_COMMANDS = {
    "launch",
    "focus",
    "play_pause",
    "stop",
    "seek_backward",
    "seek_forward",
    "previous",
    "next",
    "mute",
    "fullscreen",
}


class PlexControlError(RuntimeError):
    pass


def running_in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def host_prefix(in_flatpak: bool | None = None) -> list[str]:
    if in_flatpak is None:
        in_flatpak = running_in_flatpak()
    return ["flatpak-spawn", "--host", "--directory=/tmp"] if in_flatpak else []


def helper_command(plugin_path: str, command: str, in_flatpak: bool | None = None) -> list[str]:
    if command not in SUPPORTED_COMMANDS - {"launch"}:
        raise ValueError(f"Unsupported Plex command: {command}")
    prefix = host_prefix(in_flatpak)
    interpreter = "python3" if prefix else sys.executable
    helper = os.path.join(plugin_path, "plex_x11_helper.py")
    return [*prefix, interpreter, helper, command]


def flatpak_command(*arguments: str, in_flatpak: bool | None = None) -> list[str]:
    return [*host_prefix(in_flatpak), "flatpak", *arguments]


def is_plex_installed(in_flatpak: bool | None = None) -> bool:
    command = flatpak_command("info", PLEX_APP_ID, in_flatpak=in_flatpak)
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def launch_plex(in_flatpak: bool | None = None) -> None:
    command = flatpak_command("run", PLEX_APP_ID, in_flatpak=in_flatpak)
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise PlexControlError(f"Could not launch Plex Desktop: {exc}") from exc


def send_plex_command(
    plugin_path: str,
    command: str,
    *,
    launch_if_closed: bool = False,
    in_flatpak: bool | None = None,
) -> None:
    if command == "launch":
        # "Open Plex" is intentionally idempotent: focus the existing window,
        # or launch the Flatpak once and wait for that window to become ready.
        send_plex_command(
            plugin_path,
            "focus",
            launch_if_closed=True,
            in_flatpak=in_flatpak,
        )
        return

    if command not in SUPPORTED_COMMANDS:
        raise PlexControlError(f"Unsupported Plex command: {command}")

    helper = helper_command(plugin_path, command, in_flatpak=in_flatpak)
    attempts = 13 if launch_if_closed else 1
    launched = False
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                helper,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise PlexControlError(f"Could not send the Plex command: {exc}") from exc

        if result.returncode == 0:
            return
        if result.returncode != 3 or not launch_if_closed:
            detail = (result.stderr or result.stdout).strip()
            raise PlexControlError(detail or "Plex Desktop did not accept the command.")
        if not launched:
            if not is_plex_installed(in_flatpak=in_flatpak):
                raise PlexControlError("Plex Desktop is not installed from Flathub.")
            launch_plex(in_flatpak=in_flatpak)
            launched = True
        if attempt + 1 < attempts:
            time.sleep(1)

    raise PlexControlError("Plex Desktop did not open in time.")

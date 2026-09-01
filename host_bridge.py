from __future__ import annotations

import os
import re
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
    "status",
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


def is_plex_running(
    plugin_path: str,
    in_flatpak: bool | None = None,
) -> bool:
    command = helper_command(plugin_path, "status", in_flatpak=in_flatpak)
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise PlexControlError(f"Could not check Plex Desktop: {exc}") from exc
    if result.returncode == 0:
        return True
    if result.returncode == 3:
        return False
    detail = (result.stderr or result.stdout).strip()
    raise PlexControlError(detail or "Could not check whether Plex Desktop is running.")


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


def _run_wpctl(
    *arguments: str,
    in_flatpak: bool | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [*host_prefix(in_flatpak), "wpctl", *arguments]
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise PlexControlError(f"Could not control Plex audio: {exc}") from exc


def _audio_stream_ids(status_output: str) -> list[str]:
    """Return PipeWire node IDs from the Audio/Streams section."""
    in_audio = False
    in_streams = False
    candidates: list[tuple[int, str]] = []
    for line in status_output.splitlines():
        stripped = line.strip()
        if stripped == "Audio":
            in_audio = True
            continue
        if in_audio and stripped == "Video":
            break
        if in_audio and "Streams:" in stripped:
            in_streams = True
            continue
        if not in_streams:
            continue
        match = re.search(r"(?:^|[\s*])([0-9]+)\.", line)
        if match:
            # Channel ports are printed below their parent application stream.
            # Keep only entries at the shallowest indentation level.
            candidates.append((match.start(1), match.group(1)))
    if not candidates:
        return []
    parent_column = min(column for column, _stream_id in candidates)
    return [stream_id for column, stream_id in candidates if column == parent_column]


def _plex_audio_streams(in_flatpak: bool | None = None) -> list[str]:
    status = _run_wpctl("status", "--name", in_flatpak=in_flatpak)
    if status.returncode != 0:
        detail = (status.stderr or status.stdout).strip()
        raise PlexControlError(detail or "Could not read Linux audio streams.")

    plex_streams = []
    for stream_id in _audio_stream_ids(status.stdout):
        inspected = _run_wpctl("inspect", stream_id, in_flatpak=in_flatpak)
        identity = f"{inspected.stdout}\n{inspected.stderr}".lower()
        if inspected.returncode == 0 and "plex" in identity and "plexamp" not in identity:
            plex_streams.append(stream_id)

    return plex_streams


def _streams_muted(
    plex_streams: list[str],
    in_flatpak: bool | None = None,
) -> bool:
    mute_states: list[bool] = []
    for stream_id in plex_streams:
        volume = _run_wpctl("get-volume", stream_id, in_flatpak=in_flatpak)
        if volume.returncode != 0:
            detail = (volume.stderr or volume.stdout).strip()
            raise PlexControlError(detail or "Could not read Plex Desktop's mute state.")
        mute_states.append("[MUTED]" in volume.stdout.upper())
    return all(mute_states)


def plex_audio_muted(in_flatpak: bool | None = None) -> bool | None:
    """Return Plex's application-stream mute state, or None before audio exists."""
    plex_streams = _plex_audio_streams(in_flatpak=in_flatpak)
    if not plex_streams:
        return None
    return _streams_muted(plex_streams, in_flatpak=in_flatpak)


def mute_plex_audio(in_flatpak: bool | None = None) -> bool:
    """Toggle only Plex Desktop's PipeWire audio streams and return the new state."""
    plex_streams = _plex_audio_streams(in_flatpak=in_flatpak)
    if not plex_streams:
        raise PlexControlError(
            "Plex Desktop is not currently providing an audio stream. Start playback and try again."
        )

    current_state = _streams_muted(plex_streams, in_flatpak=in_flatpak)

    target_muted = not current_state
    target = "1" if target_muted else "0"
    for stream_id in plex_streams:
        changed = _run_wpctl("set-mute", stream_id, target, in_flatpak=in_flatpak)
        if changed.returncode != 0:
            detail = (changed.stderr or changed.stdout).strip()
            raise PlexControlError(detail or "Could not change Plex Desktop's mute state.")
    return target_muted


def send_plex_command(
    plugin_path: str,
    command: str,
    *,
    launch_if_closed: bool = False,
    in_flatpak: bool | None = None,
) -> bool | None:
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

    if command == "mute":
        if not is_plex_running(plugin_path, in_flatpak=in_flatpak):
            raise PlexControlError("Plex Desktop is not running.")
        return mute_plex_audio(in_flatpak=in_flatpak)

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

from __future__ import annotations

import os
import threading

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib
from loguru import logger as log

from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner
from src.backend.PluginManager.InputBases import Input as EventInput

from ..host_bridge import (
    PlexControlError,
    is_plex_running,
    plex_audio_muted,
    send_plex_command,
)


PLEX_ORANGE = [229, 160, 13, 255]
SUCCESS_GREEN = [94, 214, 126, 255]
ERROR_RED = [255, 82, 82, 255]
STATUS_INTERVAL_SECONDS = 3
NOT_RUNNING_MESSAGE = "Plex not running"


class PlexCommandAction(ActionCore):
    COMMAND = ""
    BUTTON_LABEL = "Plex"
    ICON_NAME = "plex"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.allow_event_configuration = True
        self._running = False
        self._plex_running = None
        self._muted = None
        self._status_check_running = False
        self._status_timer_id = None
        self.event_manager.add_event_assigner(
            EventAssigner(
                id=f"plex-{self.COMMAND.replace('_', '-')}",
                ui_label=self.BUTTON_LABEL,
                default_event=EventInput.Key.Events.SHORT_UP,
                callback=lambda _event: self._trigger(),
            )
        )

    def on_ready(self):
        self._render_idle()
        self._start_status_monitor()

    def on_update(self):
        self._render_idle()
        self._start_status_monitor()

    def get_config_rows(self):
        return []

    def _trigger(self):
        if self._running:
            return
        self._running = True
        self.hide_error()
        self.set_bottom_label("Sending…", color=PLEX_ORANGE, font_size=8)
        threading.Thread(
            target=self._worker,
            daemon=True,
        ).start()

    def _worker(self):
        error = ""
        result = None
        try:
            result = send_plex_command(
                self.plugin_base.PATH,
                self.COMMAND,
            )
        except PlexControlError as exc:
            error = str(exc)
        except Exception as exc:
            log.exception("Unexpected Plex Desktop Controller failure")
            error = f"Unexpected error: {exc}"
        GLib.idle_add(self._finish, error, result)

    def _finish(self, error: str, result: bool | None = None):
        self._running = False
        if error:
            log.error(f"Plex Desktop Controller: {error}")
            if error == "Plex Desktop is not running." and self.COMMAND != "launch":
                self._plex_running = False
                self._render_idle()
                return False
            self.set_bottom_label(error[:24], color=ERROR_RED, font_size=7)
            self.show_error()
        else:
            self._plex_running = True
            if self.COMMAND == "mute" and result is not None:
                self._muted = result
                label = "Muted" if result else "Unmuted"
                self.set_bottom_label(label, color=SUCCESS_GREEN, font_size=8)
            else:
                self.set_bottom_label("Sent", color=SUCCESS_GREEN, font_size=8)
            GLib.timeout_add(900, self._restore_idle)
        return False

    def _start_status_monitor(self):
        if self.COMMAND == "launch" or self._status_timer_id is not None:
            return
        self._request_status_check()
        self._status_timer_id = GLib.timeout_add_seconds(
            STATUS_INTERVAL_SECONDS,
            self._poll_status,
        )

    def _poll_status(self):
        if self.get_state() is None:
            self._status_timer_id = None
            return False
        self._request_status_check()
        return True

    def _request_status_check(self):
        if self._status_check_running:
            return
        self._status_check_running = True
        threading.Thread(target=self._status_worker, daemon=True).start()

    def _status_worker(self):
        running = None
        muted = None
        try:
            running = is_plex_running(self.plugin_base.PATH)
            if running and self.COMMAND == "mute":
                muted = plex_audio_muted()
        except PlexControlError as exc:
            log.debug(f"Could not refresh Plex Desktop status: {exc}")
        GLib.idle_add(self._finish_status_check, running, muted)

    def _finish_status_check(self, running: bool | None, muted: bool | None = None):
        self._status_check_running = False
        if running is not None:
            self._plex_running = running
            if self.COMMAND == "mute":
                self._muted = muted
            if not self._running:
                self._render_idle()
        return False

    def _restore_idle(self):
        self._render_idle()
        return False

    def _render_idle(self):
        self.hide_error()
        self._claim_unassigned_image_control()
        icon_name = self.ICON_NAME
        if self.COMMAND == "mute" and self._muted:
            icon_name = "mute"
        self.set_media(
            media_path=os.path.join(
                self.plugin_base.PATH, "assets", f"{icon_name}.svg"
            ),
            size=0.62,
            valign=-0.45,
            update=False,
        )
        self.set_top_label(None, update=False)
        self.set_center_label(None, update=False)
        if self.COMMAND != "launch" and self._plex_running is False:
            self.set_bottom_label(NOT_RUNNING_MESSAGE, color=ERROR_RED, font_size=7)
        elif self.COMMAND == "mute" and self._muted:
            self.set_bottom_label("Muted", color=ERROR_RED, font_size=8)
        else:
            self.set_bottom_label(self.BUTTON_LABEL, color=PLEX_ORANGE, font_size=8)

    def _claim_unassigned_image_control(self):
        state = self.get_state()
        if state is None or self.get_is_multi_action() or self.has_custom_user_asset():
            return
        manager = getattr(state, "action_permission_manager", None)
        if manager is None or manager.get_image_control_index() is not None:
            return
        action_index = self.get_own_action_index()
        if action_index is not None and action_index >= 0:
            manager.set_image_control_index(
                action_index, reload_pages=False, reload_self=False
            )


class LaunchPlexAction(PlexCommandAction):
    COMMAND = "launch"
    BUTTON_LABEL = "Open Plex"
    ICON_NAME = "launch"


class PlayPauseAction(PlexCommandAction):
    COMMAND = "play_pause"
    BUTTON_LABEL = "Play / Pause"
    ICON_NAME = "play-pause"


class StopAction(PlexCommandAction):
    COMMAND = "stop"
    BUTTON_LABEL = "Stop"
    ICON_NAME = "stop"


class SeekBackwardAction(PlexCommandAction):
    COMMAND = "seek_backward"
    BUTTON_LABEL = "Back"
    ICON_NAME = "back"


class SeekForwardAction(PlexCommandAction):
    COMMAND = "seek_forward"
    BUTTON_LABEL = "Forward"
    ICON_NAME = "forward"


class PreviousAction(PlexCommandAction):
    COMMAND = "previous"
    BUTTON_LABEL = "Previous"
    ICON_NAME = "previous"


class NextAction(PlexCommandAction):
    COMMAND = "next"
    BUTTON_LABEL = "Next"
    ICON_NAME = "next"


class MuteAction(PlexCommandAction):
    COMMAND = "mute"
    BUTTON_LABEL = "Mute"
    ICON_NAME = "volume"


class FullscreenAction(PlexCommandAction):
    COMMAND = "fullscreen"
    BUTTON_LABEL = "Fullscreen"
    ICON_NAME = "fullscreen"

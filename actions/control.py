from __future__ import annotations

import os
import threading

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib
from loguru import logger as log

from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner
from src.backend.PluginManager.InputBases import Input as EventInput

from ..host_bridge import PlexControlError, send_plex_command


PLEX_ORANGE = [229, 160, 13, 255]
SUCCESS_GREEN = [94, 214, 126, 255]
ERROR_RED = [255, 82, 82, 255]


class PlexCommandAction(ActionCore):
    COMMAND = ""
    BUTTON_LABEL = "Plex"
    ICON_NAME = "plex"
    DEFAULT_LAUNCH_IF_CLOSED = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self.allow_event_configuration = True
        self._running = False
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

    def on_update(self):
        self._render_idle()

    def get_config_rows(self):
        if self.COMMAND == "launch":
            return []
        settings = self.get_settings() or {}
        row = Adw.SwitchRow(
            title="Launch Plex if closed",
            subtitle="Start the Plex Desktop Flatpak before sending this command.",
        )
        row.set_active(
            bool(settings.get("launch_if_closed", self.DEFAULT_LAUNCH_IF_CLOSED))
        )
        row.connect("notify::active", self._on_launch_if_closed_changed)
        return [row]

    def _on_launch_if_closed_changed(self, row, _property):
        settings = dict(self.get_settings() or {})
        settings["launch_if_closed"] = row.get_active()
        self.set_settings(settings)

    def _trigger(self):
        if self._running:
            return
        self._running = True
        self.hide_error()
        self.set_bottom_label("Sending…", color=PLEX_ORANGE, font_size=8)
        settings = self.get_settings() or {}
        launch_if_closed = bool(
            settings.get("launch_if_closed", self.DEFAULT_LAUNCH_IF_CLOSED)
        )
        threading.Thread(
            target=self._worker,
            args=(launch_if_closed,),
            daemon=True,
        ).start()

    def _worker(self, launch_if_closed: bool):
        error = ""
        try:
            send_plex_command(
                self.plugin_base.PATH,
                self.COMMAND,
                launch_if_closed=launch_if_closed,
            )
        except PlexControlError as exc:
            error = str(exc)
        except Exception as exc:
            log.exception("Unexpected Plex Desktop Controller failure")
            error = f"Unexpected error: {exc}"
        GLib.idle_add(self._finish, error)

    def _finish(self, error: str):
        self._running = False
        if error:
            log.error(f"Plex Desktop Controller: {error}")
            self.set_bottom_label(error[:24], color=ERROR_RED, font_size=7)
            self.show_error()
        else:
            self.set_bottom_label("Sent", color=SUCCESS_GREEN, font_size=8)
            GLib.timeout_add(900, self._restore_idle)
        return False

    def _restore_idle(self):
        self._render_idle()
        return False

    def _render_idle(self):
        self.hide_error()
        self._claim_unassigned_image_control()
        self.set_media(
            media_path=os.path.join(
                self.plugin_base.PATH, "assets", f"{self.ICON_NAME}.svg"
            ),
            size=0.62,
            valign=-0.45,
            update=False,
        )
        self.set_top_label(None, update=False)
        self.set_center_label(None, update=False)
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


class FocusPlexAction(PlexCommandAction):
    COMMAND = "focus"
    BUTTON_LABEL = "Focus Plex"
    ICON_NAME = "focus"
    DEFAULT_LAUNCH_IF_CLOSED = True


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
    ICON_NAME = "mute"


class FullscreenAction(PlexCommandAction):
    COMMAND = "fullscreen"
    BUTTON_LABEL = "Fullscreen"
    ICON_NAME = "fullscreen"

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

from .actions import (
    FullscreenAction,
    LaunchPlexAction,
    MuteAction,
    NextAction,
    PlayPauseAction,
    PreviousAction,
    SeekBackwardAction,
    SeekForwardAction,
    StopAction,
)


ACTIONS = (
    (LaunchPlexAction, "Launch", "Open Plex", "launch", "Open Plex Desktop or bring its existing window to the front."),
    (PlayPauseAction, "PlayPause", "Play / Pause", "play-pause", "Toggle local Plex playback."),
    (SeekBackwardAction, "SeekBackward", "Skip Back", "back", "Seek backward in the current item."),
    (SeekForwardAction, "SeekForward", "Skip Forward", "forward", "Seek forward in the current item."),
    (PreviousAction, "Previous", "Previous", "previous", "Go to the previous queue item."),
    (NextAction, "Next", "Next", "next", "Go to the next queue item."),
    (StopAction, "Stop", "Stop", "stop", "Stop local Plex playback."),
    (MuteAction, "Mute", "Mute", "mute", "Toggle mute in Plex Desktop."),
    (FullscreenAction, "Fullscreen", "Fullscreen", "fullscreen", "Toggle Plex fullscreen mode."),
)


class PlexDesktopControllerPlugin(PluginBase):
    def __init__(self):
        super().__init__(use_legacy_locale=False)

        for action_core, suffix, name, icon_name, description in ACTIONS:
            self.add_action_holder(
                ActionHolder(
                    plugin_base=self,
                    action_core=action_core,
                    action_id_suffix=suffix,
                    action_name=name,
                    icon=Gtk.Picture.new_for_filename(
                        os.path.join(self.PATH, "assets", f"{icon_name}.svg")
                    ),
                    description=description,
                    requirements=(
                        "The Flathub Plex Desktop app (tv.plex.PlexDesktop) "
                        "running in an X11/XWayland desktop session."
                    ),
                    settings_schema={},
                    action_support={
                        Input.Key: ActionInputSupport.SUPPORTED,
                        Input.Dial: ActionInputSupport.UNSUPPORTED,
                        Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
                    },
                )
            )

        self.register(
            plugin_name="Plex Desktop Controller",
            github_repo="https://github.com/larkum/StreamController-PlexDesktopController",
            plugin_version="0.1.0",
            app_version="1.5.0-beta.16",
        )

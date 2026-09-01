#!/usr/bin/env python3
"""Host-side, dependency-free X11 control helper for Plex Desktop."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import time


CURRENT_TIME = 0
CLIENT_MESSAGE = 33
SUBSTRUCTURE_NOTIFY_MASK = 1 << 19
SUBSTRUCTURE_REDIRECT_MASK = 1 << 20

KEY_COMMANDS = {
    "play_pause": "space",
    "seek_backward": "Left",
    "seek_forward": "Right",
    "mute": "m",
    "fullscreen": "f",
}
MEDIA_COMMANDS = {
    "stop": "XF86AudioStop",
    "previous": "XF86AudioPrev",
    "next": "XF86AudioNext",
}


class XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class XClientMessageData(ctypes.Union):
    _fields_ = [
        ("bytes", ctypes.c_char * 20),
        ("shorts", ctypes.c_short * 10),
        ("longs", ctypes.c_long * 5),
    ]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", XClientMessageData),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("client", XClientMessageEvent),
        ("padding", ctypes.c_long * 24),
    ]


def _load_library(name: str, fallback: str):
    return ctypes.CDLL(ctypes.util.find_library(name) or fallback)


def _configure_x11():
    x11 = _load_library("X11", "libX11.so.6")
    xtst = _load_library("Xtst", "libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XClassHint)]
    x11.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
    x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_long,
        ctypes.POINTER(XEvent),
    ]
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    return x11, xtst


def _window_text(x11, display, window: int) -> str:
    values = []
    hint = XClassHint()
    if x11.XGetClassHint(display, window, ctypes.byref(hint)):
        for value in (hint.res_name, hint.res_class):
            if value:
                values.append(ctypes.string_at(value).decode("utf-8", "ignore"))
                x11.XFree(value)
    title = ctypes.c_void_p()
    if x11.XFetchName(display, window, ctypes.byref(title)) and title.value:
        values.append(ctypes.string_at(title.value).decode("utf-8", "ignore"))
        x11.XFree(title.value)
    return " ".join(values).casefold()


def _children(x11, display, window: int) -> list[int]:
    root = ctypes.c_ulong()
    parent = ctypes.c_ulong()
    children = ctypes.POINTER(ctypes.c_ulong)()
    count = ctypes.c_uint()
    if not x11.XQueryTree(
        display,
        window,
        ctypes.byref(root),
        ctypes.byref(parent),
        ctypes.byref(children),
        ctypes.byref(count),
    ):
        return []
    try:
        return [children[index] for index in range(count.value)]
    finally:
        if children:
            x11.XFree(children)


def find_plex_window(x11, display, root: int) -> int | None:
    for window in reversed(_children(x11, display, root)):
        identity = _window_text(x11, display, window)
        if "plex" in identity and "plexamp" not in identity:
            return window
    return None


def top_level_window(x11, display, root: int, window: int) -> int | None:
    current = window
    while current and current != root:
        root_return = ctypes.c_ulong()
        parent = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        if not x11.XQueryTree(
            display,
            current,
            ctypes.byref(root_return),
            ctypes.byref(parent),
            ctypes.byref(children),
            ctypes.byref(count),
        ):
            return None
        if children:
            x11.XFree(children)
        if parent.value == root:
            return current
        current = parent.value
    return None


def activate_window(x11, display, root: int, window: int) -> None:
    active_atom = x11.XInternAtom(display, b"_NET_ACTIVE_WINDOW", 0)
    if not active_atom:
        raise RuntimeError("The desktop does not support _NET_ACTIVE_WINDOW.")
    event = XEvent()
    event.client.type = CLIENT_MESSAGE
    event.client.serial = 0
    event.client.send_event = 1
    event.client.display = display
    event.client.window = window
    event.client.message_type = active_atom
    event.client.format = 32
    event.client.data.longs[0] = 2
    event.client.data.longs[1] = CURRENT_TIME
    event.client.data.longs[2] = 0
    x11.XRaiseWindow(display, window)
    status = x11.XSendEvent(
        display,
        root,
        0,
        SUBSTRUCTURE_NOTIFY_MASK | SUBSTRUCTURE_REDIRECT_MASK,
        ctypes.byref(event),
    )
    x11.XFlush(display)
    if not status:
        raise RuntimeError("The desktop rejected the Plex window activation request.")


def send_key(x11, xtst, display, keysym_name: str) -> None:
    keysym = x11.XStringToKeysym(keysym_name.encode("ascii"))
    keycode = x11.XKeysymToKeycode(display, keysym)
    if not keysym or not keycode:
        raise RuntimeError(f"X11 does not recognise {keysym_name}.")
    xtst.XTestFakeKeyEvent(display, keycode, 1, CURRENT_TIME)
    x11.XFlush(display)
    time.sleep(0.04)
    xtst.XTestFakeKeyEvent(display, keycode, 0, CURRENT_TIME)
    x11.XFlush(display)


def main(command: str) -> int:
    if command not in {*KEY_COMMANDS, *MEDIA_COMMANDS, "focus"}:
        print(f"Unsupported command: {command}", file=sys.stderr)
        return 2
    try:
        x11, xtst = _configure_x11()
        display = x11.XOpenDisplay(None)
        if not display:
            print("Could not connect to the desktop display.", file=sys.stderr)
            return 4
        try:
            root = x11.XDefaultRootWindow(display)
            plex_window = find_plex_window(x11, display, root)
            if not plex_window:
                print("Plex Desktop is not running.", file=sys.stderr)
                return 3

            if command == "focus":
                activate_window(x11, display, root, plex_window)
                return 0

            previous_focus = ctypes.c_ulong()
            revert_to = ctypes.c_int()
            x11.XGetInputFocus(display, ctypes.byref(previous_focus), ctypes.byref(revert_to))
            previous_window = top_level_window(
                x11, display, root, previous_focus.value
            )
            activate_window(x11, display, root, plex_window)
            time.sleep(0.12)
            keysym = MEDIA_COMMANDS.get(command) or KEY_COMMANDS[command]
            send_key(x11, xtst, display, keysym)
            time.sleep(0.08)
            if previous_window and previous_window != plex_window:
                activate_window(x11, display, root, previous_window)
            return 0
        finally:
            x11.XCloseDisplay(display)
    except Exception as exc:
        print(f"Plex control failed: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))

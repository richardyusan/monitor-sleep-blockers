#!/usr/bin/env python3
# Copyright (c) 2026 richardyusan
# SPDX-License-Identifier: MIT
"""Monitor Sleep Blockers (Linux).

A small GTK 4 application that lists every application currently preventing
a Linux desktop from going to sleep, dimming or blanking the screen.

Two sources are queried over D-Bus:

* GNOME Session Manager (session bus): the requests that stop *idle* sleep
  and screen blanking, such as video players, browsers and Electron apps.
* systemd-logind (system bus): low-level sleep, shutdown and key-handling
  locks taken by services and applications.

Dependencies: Python 3, PyGObject and GTK 4
(Debian/Ubuntu: ``sudo apt install python3-gi gir1.2-gtk-4.0``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

APP_ID = "io.github.richardyusan.MonitorSleepBlockers"
APP_NAME = "Monitor Sleep Blockers"
APP_VERSION = "1.0.0"
AUTO_REFRESH_SECONDS = 5
DBUS_TIMEOUT_MS = 3000

# Flags used by org.gnome.SessionManager.Inhibit
GNOME_FLAGS = {
    1: "logout",
    2: "switch-user",
    4: "suspend",
    8: "idle (screen)",
}
GNOME_FLAG_SUSPEND = 4
GNOME_FLAG_IDLE = 8

CSS = b"""
.blocking { color: #c01c28; }
.summary { font-weight: bold; font-size: 1.1em; }
.status-blocked { color: #c01c28; font-weight: bold; }
.status-allowed { color: #26a269; font-weight: bold; }
"""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@dataclass
class Inhibitor:
    source: str      # "Desktop" or "System"
    app: str         # application or service name
    what: str        # what is being inhibited
    reason: str      # human readable reason
    mode: str        # "block", "block-weak" or "delay"
    pid: str         # process id (if known)
    process: str     # process name (if known)

    @property
    def is_blocking(self) -> bool:
        return self.mode.startswith("block")


def _call(bus: Gio.DBusConnection, name: str, path: str, iface: str,
          method: str, params: GLib.Variant | None, reply: str) -> tuple:
    result = bus.call_sync(
        name, path, iface, method, params, GLib.VariantType(reply),
        Gio.DBusCallFlags.NONE, DBUS_TIMEOUT_MS, None,
    )
    return result.unpack()


def process_name(pid: int) -> str:
    """Return the command name of a process, or an empty string."""
    if not pid:
        return ""
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def describe_gnome_flags(flags: int) -> str:
    names = [name for bit, name in GNOME_FLAGS.items() if flags & bit]
    return ", ".join(names) or f"flags={flags}"


def gnome_inhibitors() -> list[Inhibitor]:
    """Inhibitors registered with the GNOME Session Manager."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    service = "org.gnome.SessionManager"
    iface = "org.gnome.SessionManager.Inhibitor"
    (paths,) = _call(bus, service, "/org/gnome/SessionManager", service,
                     "GetInhibitors", None, "(ao)")

    items = []
    for path in paths:
        try:
            (app,) = _call(bus, service, path, iface, "GetAppId", None, "(s)")
            (reason,) = _call(bus, service, path, iface, "GetReason", None, "(s)")
            (flags,) = _call(bus, service, path, iface, "GetFlags", None, "(u)")
        except GLib.Error:
            continue  # the inhibitor went away while we were reading it
        if app == "mutter" and reason == "idle-inhibit":
            app = "mutter (a visible window)"
            reason = "A window asked the compositor to keep the screen on"
        items.append(Inhibitor("Desktop", app, describe_gnome_flags(flags),
                               reason, "block", "", ""))
    return items


def logind_inhibitors() -> list[Inhibitor]:
    """Inhibitors registered with systemd-logind."""
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    (rows,) = _call(bus, "org.freedesktop.login1", "/org/freedesktop/login1",
                    "org.freedesktop.login1.Manager", "ListInhibitors",
                    None, "(a(ssssuu))")
    return [
        Inhibitor("System", who, what.replace(":", ", "), why, mode,
                  str(pid), process_name(pid))
        for what, who, why, mode, _uid, pid in rows
    ]


def gnome_is_inhibited(flag: int) -> bool | None:
    """Return whether GNOME reports the given action as inhibited."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        (value,) = _call(bus, "org.gnome.SessionManager",
                         "/org/gnome/SessionManager", "org.gnome.SessionManager",
                         "IsInhibited", GLib.Variant("(u)", (flag,)), "(b)")
        return bool(value)
    except GLib.Error:
        return None


# --------------------------------------------------------------------------
# User interface
# --------------------------------------------------------------------------
class InhibitorItem(GObject.Object):
    def __init__(self, inhibitor: Inhibitor) -> None:
        super().__init__()
        self.inhibitor = inhibitor


COLUMNS = (
    # attribute, title, fixed width (-1 = expand)
    ("source", "Source", 80),
    ("app", "Application", 210),
    ("what", "Inhibits", 190),
    ("mode", "Mode", 110),
    ("pid", "PID", 70),
    ("process", "Process", 140),
    ("reason", "Reason", -1),
)


class MonitorWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1100, 540)
        self.set_icon_name(APP_ID)
        self._timer_id = 0

        # Header bar
        header = Gtk.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic",
                             tooltip_text="Refresh (F5)")
        refresh.set_action_name("win.refresh")
        header.pack_start(refresh)

        menu = Gio.Menu()
        menu.append("About Monitor Sleep Blockers", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic",
                                       menu_model=menu, tooltip_text="Menu"))
        self.set_titlebar(header)

        self.add_action_entries([("refresh", lambda *_: self.refresh())])

        # Body
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=10, margin_bottom=10,
                      margin_start=12, margin_end=12)
        self.set_child(box)

        toolbar = Gtk.Box(spacing=18)
        self.blocking_only = Gtk.CheckButton(label="Show blocking only")
        self.blocking_only.connect("toggled", lambda *_: self.refresh())
        self.auto_refresh = Gtk.CheckButton(
            label=f"Auto-refresh every {AUTO_REFRESH_SECONDS} s")
        self.auto_refresh.connect("toggled", self._on_auto_refresh)
        toolbar.append(self.blocking_only)
        toolbar.append(self.auto_refresh)
        box.append(toolbar)

        summary = Gtk.Box(spacing=6)
        summary.add_css_class("summary")
        summary.append(Gtk.Label(label="Screen blanking / idle:"))
        self.idle_label = Gtk.Label()
        summary.append(self.idle_label)
        summary.append(Gtk.Label(label="      Automatic suspend:"))
        self.suspend_label = Gtk.Label()
        summary.append(self.suspend_label)
        box.append(summary)

        self.store = Gio.ListStore(item_type=InhibitorItem)
        view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.store))
        view.set_show_row_separators(True)
        view.set_show_column_separators(True)
        for attr, title, width in COLUMNS:
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup_cell)
            factory.connect("bind", self._bind_cell, attr)
            column = Gtk.ColumnViewColumn(title=title, factory=factory,
                                          resizable=True)
            if width < 0:
                column.set_expand(True)
            else:
                column.set_fixed_width(width)
            view.append_column(column)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(view)
        frame = Gtk.Frame()
        frame.set_child(scroller)
        box.append(frame)

        hint = Gtk.Label(
            label="Red rows block the action. Grey 'delay' rows only postpone "
                  "it briefly and do not prevent sleep.",
            xalign=0)
        hint.add_css_class("dim-label")
        box.append(hint)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        box.append(self.status)

        self.refresh()

    # ----- table cells -------------------------------------------------
    @staticmethod
    def _setup_cell(_factory, list_item) -> None:
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                          margin_start=4, margin_end=4)
        list_item.set_child(label)

    @staticmethod
    def _bind_cell(_factory, list_item, attr: str) -> None:
        label = list_item.get_child()
        inhibitor = list_item.get_item().inhibitor
        text = getattr(inhibitor, attr)
        label.set_text(text)
        label.set_tooltip_text(text or None)
        if inhibitor.is_blocking:
            label.remove_css_class("dim-label")
            label.add_css_class("blocking")
        else:
            label.remove_css_class("blocking")
            label.add_css_class("dim-label")

    # ----- data --------------------------------------------------------
    def refresh(self) -> None:
        items: list[Inhibitor] = []
        errors: list[str] = []
        for name, loader in (("GNOME", gnome_inhibitors),
                             ("logind", logind_inhibitors)):
            try:
                items.extend(loader())
            except GLib.Error as exc:
                errors.append(f"{name}: {exc.message}")

        if self.blocking_only.get_active():
            items = [i for i in items if i.is_blocking]
        self.store.splice(0, self.store.get_n_items(),
                          [InhibitorItem(i) for i in items])

        self._set_state(self.idle_label, gnome_is_inhibited(GNOME_FLAG_IDLE))
        self._set_state(self.suspend_label,
                        gnome_is_inhibited(GNOME_FLAG_SUSPEND))

        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"{len(items)} inhibitor(s) - last refreshed {stamp}"
        if errors:
            text += "   |   Unavailable: " + "; ".join(errors)
        self.status.set_text(text)

    @staticmethod
    def _set_state(label: Gtk.Label, value: bool | None) -> None:
        for css in ("status-blocked", "status-allowed"):
            label.remove_css_class(css)
        if value is None:
            label.set_text("unknown")
        elif value:
            label.set_text("BLOCKED")
            label.add_css_class("status-blocked")
        else:
            label.set_text("allowed")
            label.add_css_class("status-allowed")

    def _on_auto_refresh(self, button: Gtk.CheckButton) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        if button.get_active():
            self._timer_id = GLib.timeout_add_seconds(
                AUTO_REFRESH_SECONDS, self._tick)

    def _tick(self) -> bool:
        self.refresh()
        return GLib.SOURCE_CONTINUE


class MonitorApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        GLib.set_application_name(APP_NAME)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Let the icon be found when running from the source folder.
        here = os.path.dirname(os.path.realpath(__file__))
        icons = os.path.join(here, "data", "icons")
        if os.path.isdir(icons):
            Gtk.IconTheme.get_for_display(display).add_search_path(icons)
        Gtk.Window.set_default_icon_name(APP_ID)

        self.add_action_entries([
            ("about", lambda *_: self._show_about()),
            ("quit", lambda *_: self.quit()),
        ])
        self.set_accels_for_action("win.refresh", ["F5", "<Control>r"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self) -> None:
        window = self.get_active_window() or MonitorWindow(self)
        window.present()

    def _show_about(self) -> None:
        Gtk.AboutDialog(
            transient_for=self.get_active_window(), modal=True,
            program_name=APP_NAME, logo_icon_name=APP_ID,
            version=APP_VERSION,
            comments="See which applications keep your Linux computer "
                     "from sleeping.",
            website="https://github.com/richardyusan/monitor-sleep-blockers",
            copyright="Copyright (c) 2026 richardyusan",
            license_type=Gtk.License.MIT_X11,
        ).present()


def main() -> int:
    return MonitorApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

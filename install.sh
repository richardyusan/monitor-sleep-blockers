#!/bin/sh
# Copyright (c) 2026 richardyusan
# SPDX-License-Identifier: MIT
#
# Install Monitor Sleep Blockers.
#
#   ./install.sh                  install for the current user (~/.local)
#   sudo ./install.sh /usr/local  install for all users
set -eu

APP_ID="io.github.richardyusan.MonitorSleepBlockers"
PREFIX="${1:-$HOME/.local}"
SRC="$(cd "$(dirname "$0")" && pwd)"

BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/share/monitor-sleep-blockers"
APPDIR="$PREFIX/share/applications"
ICONDIR="$PREFIX/share/icons/hicolor/scalable/apps"

# Check dependencies
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2>/dev/null; then
    echo "PyGObject with GTK 4 is missing. Install it first:"
    echo "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0"
    echo "  Fedora:        sudo dnf install python3-gobject gtk4"
    echo "  Arch Linux:    sudo pacman -S python-gobject gtk4"
    exit 1
fi

echo "Installing to $PREFIX"
install -Dm755 "$SRC/monitor_sleep_blockers.py" "$LIBDIR/monitor_sleep_blockers.py"
install -Dm644 "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICONDIR/$APP_ID.svg"

mkdir -p "$BINDIR"
ln -sf "$LIBDIR/monitor_sleep_blockers.py" "$BINDIR/monitor-sleep-blockers"

mkdir -p "$APPDIR"
sed "s|@BINDIR@|$BINDIR|g" "$SRC/data/$APP_ID.desktop" > "$APPDIR/$APP_ID.desktop"
chmod 644 "$APPDIR/$APP_ID.desktop"

# Refresh caches (optional tools)
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -q "$PREFIX/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database -q "$APPDIR" 2>/dev/null || true

echo "Done. Open \"Monitor Sleep Blockers\" from the app menu,"
echo "or run: $BINDIR/monitor-sleep-blockers"

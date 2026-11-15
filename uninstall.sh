#!/bin/sh
# Copyright (c) 2026 richardyusan
# SPDX-License-Identifier: MIT
#
# Remove Monitor Sleep Blockers.
#
#   ./uninstall.sh                  remove the per-user install (~/.local)
#   sudo ./uninstall.sh /usr/local  remove a system-wide install
set -eu

APP_ID="io.github.richardyusan.MonitorSleepBlockers"
PREFIX="${1:-$HOME/.local}"

rm -f  "$PREFIX/bin/monitor-sleep-blockers"
rm -rf "$PREFIX/share/monitor-sleep-blockers"
rm -f  "$PREFIX/share/applications/$APP_ID.desktop"
rm -f  "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg"

command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -q "$PREFIX/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true

echo "Monitor Sleep Blockers removed from $PREFIX"

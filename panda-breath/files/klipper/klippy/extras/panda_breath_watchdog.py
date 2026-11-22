# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Watch Klipper and the Panda Breath link from a thread of its own.

Klipper's reactor drives everything else in the plugin, so when the reactor hangs nothing else is
left to switch the heater off. This thread does not depend on the reactor.
"""

import logging
import socket
import threading
import time

WATCH_TICK_SECONDS = 1.
# The stock firmware sends the chamber temperature about twice a second, so ten silent seconds
# mean the connection is dead even when the operating system has not noticed yet.
LINK_KICK_SECONDS = 10.


def reactor_hung(now, last_heartbeat, hang_timeout):
    """Tell whether the reactor has missed its heartbeat for longer than hang_timeout."""
    return now - last_heartbeat > hang_timeout


def link_silent(now, last_sign_of_life, silence_limit):
    """Tell whether the device has been silent for longer than silence_limit."""
    return now - last_sign_of_life > silence_limit


def device_may_heat(module):
    """Tell whether the Panda Breath may be heating, from what the plugin sent and heard."""
    transport = module._transport
    auto_wanted = transport._last_auto is not None and transport._last_auto[0]
    return bool(
        transport._last_target > 0
        or auto_wanted
        or transport._last_drying is not None
        or module.work_on
    )


class DeviceWatchdog:
    """Switch the Panda Breath off when Klipper hangs, and drop a connection that went silent."""

    def __init__(self, module, hang_timeout):
        self.module = module
        self.hang_timeout = hang_timeout
        self.stop_event = threading.Event()
        self.watch_thread = None
        self.last_heartbeat = time.monotonic()
        self.last_frame_time = time.monotonic()
        self.connected_since = time.monotonic()
        self.watched_socket = None
        self.hang_tripped = False

    def start(self):
        self.beat()
        self.note_frame()
        self.stop_event.clear()
        self.watch_thread = threading.Thread(
            target=self._watch, name="panda_breath_watchdog", daemon=True)
        self.watch_thread.start()

    def stop(self):
        self.stop_event.set()

    def beat(self):
        """Called by the reactor: proof that Klipper still runs."""
        self.last_heartbeat = time.monotonic()

    def note_frame(self):
        """Called for every frame the device sends: proof that the link still works."""
        self.last_frame_time = time.monotonic()

    def take_hang_trip(self):
        """Return True once after the watchdog switched the device off for a hang."""
        tripped = self.hang_tripped
        self.hang_tripped = False
        return tripped

    def check(self, now):
        self._check_hang(now)
        self._check_link(now)

    def _watch(self):
        while not self.stop_event.wait(WATCH_TICK_SECONDS):
            self.check(time.monotonic())

    def _check_hang(self, now):
        if self.hang_tripped or not reactor_hung(now, self.last_heartbeat, self.hang_timeout):
            return
        if not device_may_heat(self.module):
            return
        self.hang_tripped = True
        logging.error("panda_breath: Klipper stopped responding, switching the Panda Breath off")
        self.module._transport.force_off()

    def _check_link(self, now):
        device_socket = self.module._transport._sock
        if device_socket is not None and device_socket is not self.watched_socket:
            self.watched_socket = device_socket
            self.connected_since = now
            return
        last_sign_of_life = max(self.last_frame_time, self.connected_since)
        if device_socket is None or not link_silent(now, last_sign_of_life, LINK_KICK_SECONDS):
            return
        drop_silent_connection(device_socket)


def drop_silent_connection(device_socket):
    """Wake the transport thread out of its blocked read so it reconnects.

    close() from another thread does not wake a blocked recv() on Linux; shutdown() does.
    """
    logging.warning("panda_breath: no data from the Panda Breath, reconnecting")
    try:
        device_socket.shutdown(socket.SHUT_RDWR)
    except OSError as error:
        logging.info("panda_breath: silent connection already closed: %s", error)

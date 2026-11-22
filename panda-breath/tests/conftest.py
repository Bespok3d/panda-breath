# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""A Klipper bench with the plugin loaded and a fake Panda Breath on localhost."""

import functools
import json
import pathlib
import sys
import threading
import time

import pytest

KLIPPY_DIR = pathlib.Path(__file__).resolve().parent.parent / "files" / "klipper" / "klippy"
sys.path.insert(0, str(KLIPPY_DIR))

# The plugin modules import as Klipper loads them, from klippy/, so the path goes in first.
from extras import panda_breath  # noqa: E402
from fake_panda_breath import FakePandaBreath  # noqa: E402
from klipper_fakes import FakeConfig, FakePrinter  # noqa: E402

FAST_RECONNECT_SECONDS = 0.05
# The [heater_generic panda_breath] the plugin's config template ships.
HEATER_OPTIONS = {
    "sensor_type": "panda_breath",
    "min_temp": "15",
    "max_temp": "60",
    "max_delta": "0.5",
}
FORCE_OFF_THREAD_NAME = "panda_breath_force_off"
STARTUP_OFF_FRAMES = 2
THREAD_WAIT_SECONDS = 5.
THREAD_POLL_SECONDS = 0.01


def switched_off_frames(received_settings):
    return [settings for settings in received_settings if settings.get("work_on") is False]


def device_told_off_at_start(device):
    """Both the connect force off and the reconnect resend end with work_on false."""
    return len(switched_off_frames(device.received_settings)) >= STARTUP_OFF_FRAMES


def wait_for(condition_holds, timeout=THREAD_WAIT_SECONDS):
    """Wait for a background thread's effect that sends no signal; return whether it showed."""
    deadline = time.monotonic() + timeout
    while not condition_holds():
        if time.monotonic() > deadline:
            return False
        time.sleep(THREAD_POLL_SECONDS)
    return True


def join_background_force_offs():
    for running_thread in threading.enumerate():
        if running_thread.name == FORCE_OFF_THREAD_NAME:
            running_thread.join()


def received_frames(mark, frame_count, device):
    return len(device.received_since(mark)) >= frame_count


class PandaBreathBench:
    """One Klipper with [panda_breath], [panda_breath_guard] and the chamber heater, connected."""

    def __init__(self, device):
        self.device = device
        self.printer = None

    def start(self, guard_options=None):
        return self.load(guard_options).connect()

    def load(self, guard_options=None, user_sections=None):
        """Read the config sections, as Klipper does before it connects."""
        device_options = {"firmware": "stock", "host": "127.0.0.1", "port": str(self.device.port)}
        self.printer = FakePrinter({
            "panda_breath": device_options,
            "panda_breath_guard": dict(guard_options or {}),
            **(user_sections or {}),
        })
        self.printer.load_object(FakeConfig(self.printer, "printer", {}), "panda_breath_guard")
        self.printer.lookup_object("heaters").setup_heater("panda_breath", HEATER_OPTIONS)
        return self

    def connect(self):
        """Connect, wait until the device heard "off", and run the first reactor timers."""
        self.printer.send_event("klippy:connect")
        assert self.device.wait_until(device_told_off_at_start)
        join_background_force_offs()
        self.advance(0.)
        return self

    def stop(self):
        if self.printer is not None:
            self.printer.send_event("klippy:disconnect")
        join_background_force_offs()

    @property
    def guard(self):
        return self.printer.lookup_object("panda_breath_guard")

    @property
    def module(self):
        return self.printer.lookup_object("panda_breath")

    @property
    def transport(self):
        return self.module._transport

    @property
    def heater(self):
        return self.printer.lookup_object("heaters").lookup_heater("panda_breath")

    @property
    def gcode(self):
        return self.printer.lookup_object("gcode")

    @property
    def reactor(self):
        return self.printer.get_reactor()

    def run_gcode(self, commandline):
        self.gcode.run(commandline)

    def run_gcode_and_wait_for_frames(self, commandline, frame_count):
        """Run a command and return the settings frames the device received for it."""
        mark = self.device.mark()
        self.run_gcode(commandline)
        assert self.device.wait_until(functools.partial(received_frames, mark, frame_count))
        return self.device.received_since(mark)

    def advance(self, seconds):
        self.reactor.advance(seconds)

    def device_frame_after(self, delay_seconds, settings):
        """Hand a device frame to the transport at a simulated time, as its thread would."""
        payload = json.dumps({"settings": settings}).encode()
        self.reactor.call_at(
            self.reactor.monotonic() + delay_seconds,
            functools.partial(self.transport._dispatch, payload))


@pytest.fixture
def fake_device():
    device = FakePandaBreath()
    yield device
    device.stop()


@pytest.fixture
def bench(fake_device, monkeypatch):
    monkeypatch.setattr(panda_breath, "RECONNECT_DELAY", FAST_RECONNECT_SECONDS)
    panda_breath_bench = PandaBreathBench(fake_device)
    yield panda_breath_bench
    panda_breath_bench.stop()

# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Alarms, the latched fault, the watchdog and recovery, against a fake Panda Breath."""

import functools
import time

import pytest
from conftest import (
    device_told_off_at_start,
    join_background_force_offs,
    switched_off_frames,
    wait_for,
)
from extras import panda_breath_guard, panda_breath_watchdog
from klipper_fakes import CommandError, ConfigError

HEAT_TO_40_FRAMES = [{"isrunning": 0}, {"work_mode": 2}, {"set_temp": 40}, {"work_on": True}]
HEAT_TO_40_FRAME_COUNT = len(HEAT_TO_40_FRAMES)
FAST_WATCH_TICK_SECONDS = 0.05
SHORT_TIMEOUT = "0.5"
LONGER_THAN_SHORT_TIMEOUT = 0.6
GUARD_TICKS = 2.


def heat_to_40(bench):
    bench.run_gcode_and_wait_for_frames("M141 S40", HEAT_TO_40_FRAME_COUNT)


def latch_sensor_fault(bench):
    bench.device_frame_after(0., {"ptc_sensor_status": 1})
    bench.advance(GUARD_TICKS)


def told_off_since(mark, device):
    return bool(switched_off_frames(device.received_since(mark)))


def heat_resent_since(mark, device):
    received = device.received_since(mark)
    return {"set_temp": 40} in received and {"work_on": True} in received


def ends_heating_at_40(mark, device):
    return device.received_since(mark)[-HEAT_TO_40_FRAME_COUNT:] == HEAT_TO_40_FRAMES


def only_the_main_link_open(device):
    """A closed one-shot connection means the fake recorded its frame."""
    return len(device.open_connections) == 1


def reboot_device(bench):
    bench.device.reboot()


def go_silent(bench):
    """Make the watchdog see a connection with no frame for longer than its kick limit.

    The last frame moves into the past instead of the clock into the future, so the reactor
    heartbeat stays fresh and only the link check fires.
    """
    watchdog = bench.guard.watchdog
    now = time.monotonic()
    watchdog.check(now)
    silent_since = now - panda_breath_watchdog.LINK_KICK_SECONDS - 1.
    watchdog.last_frame_time = silent_since
    watchdog.connected_since = silent_since
    watchdog.check(now)


@pytest.mark.parametrize(("alarm", "fault_reason"), [
    ({"ptc_sensor_status": 1}, "heater sensor is short-circuited"),
    ({"ptc_sensor_status": 2}, "heater sensor is open (unplugged or a broken wire)"),
    ({"warehouse_sensor_status": 1}, "chamber sensor is short-circuited"),
    ({"warehouse_sensor_status": 2}, "chamber sensor is open (unplugged or a broken wire)"),
    ({"ptc_heater_status": 1}, "heating element reports a fault"),
])
def test_a_device_alarm_stops_the_heat_and_says_what_broke(bench, alarm, fault_reason):
    bench.start()
    heat_to_40(bench)
    mark = bench.device.mark()
    bench.device.push(alarm)
    assert wait_for(functools.partial(bool, bench.guard.alarm_queue))
    bench.advance(GUARD_TICKS)
    assert bench.guard.get_status(0.) == {"fault": True, "fault_reason": fault_reason}
    assert bench.gcode.responses[-1] == "!! " + panda_breath_guard.fault_message(fault_reason)
    assert bench.heater.target_temp == 0.
    assert bench.device.wait_until(functools.partial(told_off_since, mark))


@pytest.mark.parametrize("commandline", [
    "M141 S40",
    "M191 S40",
    "PANDA_BREATH_AUTO ENABLE=1",
    "PANDA_BREATH_DRY_START",
])
def test_a_latched_fault_refuses_heat(bench, commandline):
    bench.start()
    latch_sensor_fault(bench)
    with pytest.raises(CommandError, match="PANDA_BREATH_CLEAR_FAULT"):
        bench.run_gcode(commandline)
    assert bench.heater.target_temp == 0.


def test_a_latched_fault_stays_when_the_alarm_goes_away(bench):
    bench.start()
    latch_sensor_fault(bench)
    bench.device_frame_after(0., {"ptc_sensor_status": 0})
    bench.advance(GUARD_TICKS)
    assert bench.guard.fault_reason == "heater sensor is short-circuited"


def test_auto_mode_can_be_switched_off_while_faulted(bench):
    bench.start()
    latch_sensor_fault(bench)
    bench.run_gcode("PANDA_BREATH_AUTO ENABLE=0")
    assert bench.guard.fault_reason


def test_clear_fault_lets_the_chamber_heat_again(bench):
    bench.start()
    latch_sensor_fault(bench)
    bench.run_gcode("PANDA_BREATH_CLEAR_FAULT")
    heat_to_40(bench)
    assert bench.heater.target_temp == 40.
    assert bench.guard.get_status(0.) == {"fault": False, "fault_reason": ""}


def test_heat_asked_for_right_after_a_fault_survives_the_late_off(bench):
    bench.start()
    mark = bench.device.mark()
    latch_sensor_fault(bench)
    bench.run_gcode("PANDA_BREATH_CLEAR_FAULT")
    bench.run_gcode("M141 S40")
    join_background_force_offs()
    assert bench.device.wait_until(only_the_main_link_open)
    bench.advance(GUARD_TICKS)
    assert bench.device.wait_until(functools.partial(ends_heating_at_40, mark))


def test_clear_fault_without_a_fault_says_so(bench):
    bench.start()
    bench.run_gcode("PANDA_BREATH_CLEAR_FAULT")
    assert bench.gcode.responses[-1] == "// Panda Breath: no fault to clear"


@pytest.fixture
def short_limits_allowed(monkeypatch):
    """The real minimums are seconds long; these tests shrink them to keep the run fast."""
    monkeypatch.setattr(panda_breath_guard, "MIN_HANG_TIMEOUT", 0.)
    monkeypatch.setattr(panda_breath_guard, "MIN_LINK_TIMEOUT", 0.)


@pytest.mark.parametrize("guard_options", [{"hang_timeout": "1"}, {"link_timeout": "10"}])
def test_limits_below_the_minimum_are_refused(bench, guard_options):
    with pytest.raises(ConfigError, match="must have minimum of"):
        bench.load(guard_options)


@pytest.mark.usefixtures("short_limits_allowed")
def test_a_hung_klipper_switches_the_heating_device_off(bench, monkeypatch):
    monkeypatch.setattr(panda_breath_watchdog, "WATCH_TICK_SECONDS", FAST_WATCH_TICK_SECONDS)
    bench.start({"hang_timeout": "0.3"})
    heat_to_40(bench)
    mark = bench.device.mark()
    assert bench.device.wait_until(functools.partial(told_off_since, mark))
    bench.advance(GUARD_TICKS)
    assert bench.guard.fault_reason == panda_breath_guard.HANG_FAULT
    assert bench.heater.target_temp == 0.


@pytest.mark.usefixtures("short_limits_allowed")
def test_a_hung_klipper_with_the_device_idle_is_no_fault(bench, monkeypatch):
    monkeypatch.setattr(panda_breath_watchdog, "WATCH_TICK_SECONDS", FAST_WATCH_TICK_SECONDS)
    bench.start({"hang_timeout": "0.3"})
    time.sleep(LONGER_THAN_SHORT_TIMEOUT)
    bench.advance(GUARD_TICKS)
    assert not bench.guard.fault_reason


@pytest.mark.parametrize("drop_the_link", [reboot_device, go_silent])
def test_after_a_reconnect_the_device_heats_again(bench, drop_the_link):
    bench.start()
    heat_to_40(bench)
    mark = bench.device.mark()
    drop_the_link(bench)
    assert bench.device.wait_until(functools.partial(heat_resent_since, mark))
    assert not bench.guard.fault_reason


@pytest.mark.usefixtures("short_limits_allowed")
def test_a_link_lost_while_heating_latches_a_fault(bench):
    bench.start({"link_timeout": SHORT_TIMEOUT})
    heat_to_40(bench)
    bench.device.power_off()
    time.sleep(LONGER_THAN_SHORT_TIMEOUT)
    bench.advance(GUARD_TICKS)
    assert bench.guard.fault_reason == panda_breath_guard.LINK_FAULT
    assert bench.transport._last_target == 0.
    assert bench.heater.target_temp == 0.


@pytest.mark.usefixtures("short_limits_allowed")
def test_a_link_with_fresh_frames_is_no_fault(bench):
    bench.start({"link_timeout": SHORT_TIMEOUT})
    heat_to_40(bench)
    time.sleep(LONGER_THAN_SHORT_TIMEOUT)
    bench.device_frame_after(0., {"warehouse_temper": 30})
    bench.advance(GUARD_TICKS)
    assert not bench.guard.fault_reason


def test_at_klipper_start_the_device_is_switched_off(bench):
    bench.start()
    assert device_told_off_at_start(bench.device)
    assert bench.heater.target_temp == 0.
    assert bench.module.work_on is False

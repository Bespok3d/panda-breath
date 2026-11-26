# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""The plugin's pure decisions: alarm texts, the M191 wait, the watchdog checks."""

import functools
import threading
import time
import types

import pytest
from extras import (
    panda_breath_alarms,
    panda_breath_chamber,
    panda_breath_device_fixes,
    panda_breath_guard,
    panda_breath_watchdog,
)

QUICK_RETURN_SECONDS = 1.


@pytest.mark.parametrize(("settings", "expected_faults"), [
    ({"ptc_sensor_status": 1}, ["heater sensor is short-circuited"]),
    ({"ptc_sensor_status": 2}, ["heater sensor is open (unplugged or a broken wire)"]),
    ({"warehouse_sensor_status": 1}, ["chamber sensor is short-circuited"]),
    ({"warehouse_sensor_status": "2"}, ["chamber sensor is open (unplugged or a broken wire)"]),
    ({"ptc_heater_status": 0}, ["heating element reports a fault"]),
    ({"ptc_sensor_status": 0, "warehouse_sensor_status": 0}, []),
    ({"ptc_sensor_status": "junk", "warehouse_sensor_status": None}, []),
    ({"warehouse_temper": 31}, []),
])
def test_alarm_faults_name_what_broke(settings, expected_faults):
    assert panda_breath_alarms.alarm_faults(settings) == expected_faults


@pytest.mark.parametrize("payload", [
    b"\xff\xfe", b"not json", b"[1, 2]", b'{"settings": 5}', b'{"other": {}}',
])
def test_settings_from_frame_ignores_frames_without_settings(payload):
    assert panda_breath_alarms.settings_from_frame(payload) == {}


def chamber_snapshot(**changes):
    calm_wait = panda_breath_chamber.ChamberWaitSnapshot(
        klipper_shutdown=False, fault_reason="", heater_target=40.,
        target_not_reached=True, waited_seconds=10.)
    return calm_wait._replace(**changes)


@pytest.mark.parametrize(("snapshot", "expected_outcome"), [
    (chamber_snapshot(), panda_breath_chamber.KEEP_WAITING),
    (chamber_snapshot(target_not_reached=False), panda_breath_chamber.REACHED),
    (chamber_snapshot(waited_seconds=60.), panda_breath_chamber.TIMED_OUT),
    (chamber_snapshot(heater_target=0.), panda_breath_chamber.CANCELLED),
    (chamber_snapshot(klipper_shutdown=True, fault_reason="x"), panda_breath_chamber.CANCELLED),
    (chamber_snapshot(fault_reason="x", heater_target=0.), panda_breath_chamber.FAULTED),
    (chamber_snapshot(target_not_reached=False, waited_seconds=60.), panda_breath_chamber.REACHED),
])
def test_wait_outcome_checks_in_order(snapshot, expected_outcome):
    assert panda_breath_chamber.wait_outcome(snapshot, 40., 60.) == expected_outcome


@pytest.mark.parametrize(("printer_chamber_temp", "reached"), [
    (None, False),
    (39.9, False),
    (40., True),
    (41., True),
])
def test_printer_chamber_reached_at_the_target(printer_chamber_temp, reached):
    assert panda_breath_chamber.printer_chamber_reached(printer_chamber_temp, 40.) is reached


def test_timeout_message_speaks_minutes():
    assert panda_breath_chamber.timeout_message(40., 2.) == (
        "Panda Breath: the chamber did not reach 40 C within 2 minutes. Heating stopped")
    assert "within 0.5 minutes" in panda_breath_chamber.timeout_message(40., 0.5)


@pytest.mark.parametrize(("wait_limit_action", "expected_seconds"), [
    (panda_breath_chamber.NO_WAIT_LIMIT, float("inf")),
    (panda_breath_chamber.WARN_AT_WAIT_LIMIT, 120.),
    (panda_breath_chamber.STOP_AT_WAIT_LIMIT, 120.),
])
def test_wait_limit_seconds_follows_the_chosen_action(wait_limit_action, expected_seconds):
    assert panda_breath_chamber.wait_limit_seconds(wait_limit_action, 2.) == expected_seconds


def test_distinct_faults_keeps_arrival_order_without_repeats():
    fault_batches = [["chamber sensor is short-circuited"], ["heating element reports a fault",
                     "chamber sensor is short-circuited"]]
    assert panda_breath_guard.distinct_faults(fault_batches) == [
        "chamber sensor is short-circuited", "heating element reports a fault"]


def idle_module(**transport_state):
    transport = types.SimpleNamespace(
        _last_target=0., _last_auto=None, _last_drying=None, _sock=None)
    transport.__dict__.update(transport_state)
    return types.SimpleNamespace(_transport=transport, work_on=False, _in_shutdown=False)


@pytest.mark.parametrize(("module", "may_heat"), [
    (idle_module(), False),
    (idle_module(_last_target=40.), True),
    (idle_module(_last_auto=(True, 45, 30, 80)), True),
    (idle_module(_last_auto=(False, 45, 30, 80)), False),
    (idle_module(_last_drying=(55, 6)), True),
    (types.SimpleNamespace(_transport=idle_module()._transport, work_on=True), True),
])
def test_device_may_heat(module, may_heat):
    assert panda_breath_watchdog.device_may_heat(module) is may_heat


def test_hang_and_silence_limits_are_strict():
    assert not panda_breath_watchdog.reactor_hung(115., 100., 15.)
    assert panda_breath_watchdog.reactor_hung(115.1, 100., 15.)
    assert not panda_breath_watchdog.link_silent(130., 100., 30.)
    assert panda_breath_watchdog.link_silent(130.1, 100., 30.)


def block_until_released(release_one_shot, fields):
    release_one_shot.wait()


def test_force_off_sends_off_at_once_and_forgets_the_wanted_state():
    sent_on_the_main_link = []
    release_one_shot = threading.Event()
    module = idle_module(
        _last_target=40., _last_drying=(55, 6), _send_settings=sent_on_the_main_link.append,
        _send_settings_once=functools.partial(block_until_released, release_one_shot))
    module.reactor = types.SimpleNamespace(register_async_callback=list().append)
    started_at = time.monotonic()
    panda_breath_device_fixes.force_off_without_blocking(module, pytest.fail)
    returned_after = time.monotonic() - started_at
    transport = module._transport
    wanted_state = (transport._last_target, transport._last_auto, transport._last_drying)
    release_one_shot.set()
    assert returned_after < QUICK_RETURN_SECONDS
    assert wanted_state == (0., None, None)
    assert tuple(sent_on_the_main_link) == panda_breath_device_fixes.OFF_SEQUENCE


def test_force_off_while_klipper_goes_down_finishes_before_returning():
    module = idle_module(_last_target=40.)
    module._in_shutdown = True
    device_told_off = threading.Event()
    panda_breath_device_fixes.force_off_without_blocking(module, device_told_off.set)
    assert device_told_off.is_set()


def test_custom_drying_preset_matches_the_stock_web_ui():
    assert panda_breath_device_fixes.custom_drying_preset(50., 2.) == (
        {"work_mode": 3},
        {"filament_temp": 50},
        {"filament_drying_mode": 3},
        {"filament_timer": 2},
        {"filament_drying_mode": 3},
    )

# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""The G-code side: HELP texts, M141 and M191, drying and Auto mode on a fake device."""

import functools

import pytest
from conftest import HEATER_OPTIONS
from extras import panda_breath_device_fixes
from klipper_fakes import (
    CommandError,
    ConfigError,
    FakeConfig,
    FakePrinter,
    FakeTemperatureSensor,
)

PLUGIN_COMMANDS = (
    "PANDA_BREATH_AUTO",
    "PANDA_BREATH_DRY_START",
    "PANDA_BREATH_DRY_STOP",
    "PANDA_BREATH_CLEAR_FAULT",
    "M141",
    "M191",
)
HEAT_TO_40_FRAMES = [{"isrunning": 0}, {"work_mode": 2}, {"set_temp": 40}, {"work_on": True}]
SWITCH_OFF_FRAMES = [{"isrunning": 0}, {"work_on": False}]
DRYING_FRAME_COUNT = 12
AUTO_FRAME_COUNT = 7
AUTO_OFF_FRAME_COUNT = 6
CHAMBER_MAX_TEMP = float(HEATER_OPTIONS["max_temp"])
U1_CAVITY_SENSOR = "temperature_sensor cavity"
STOP_AFTER_2_MINUTES = {"wait_limit": "stop", "wait_limit_minutes": "2"}
SLOW_WARM_UP_SECONDS = 45 * 60.


def user_m141_macro(gcmd):
    return None


def test_every_plugin_command_has_a_help_text(bench):
    bench.start()
    assert all(bench.gcode.gcode_help.get(command) for command in PLUGIN_COMMANDS)


def test_an_m141_registered_before_the_guard_is_kept():
    printer = FakePrinter({
        "panda_breath": {"firmware": "stock", "host": "127.0.0.1"},
        "panda_breath_guard": {},
    })
    printer.lookup_object("gcode").register_command("M141", user_m141_macro)
    printer.load_object(FakeConfig(printer, "printer", {}), "panda_breath_guard")
    assert printer.lookup_object("gcode").ready_gcode_handlers["M141"] is user_m141_macro


def test_a_user_m141_macro_later_in_the_config_is_kept(bench):
    bench.load(user_sections={"gcode_macro m141": {"gcode": "SET_HEATER_TEMPERATURE"}})
    assert "M141" not in bench.gcode.ready_gcode_handlers
    assert "M191" in bench.gcode.ready_gcode_handlers


def test_a_user_m141_macro_that_renames_finds_the_plugin_command_at_connect(bench):
    bench.load(user_sections={
        "gcode_macro M141": {"rename_existing": "M141.1", "gcode": "M141.1 S{params.S}"},
    })
    assert "M141" in bench.gcode.ready_gcode_handlers


def test_the_guard_refuses_the_esphome_firmware():
    printer = FakePrinter({
        "panda_breath": {"firmware": "esphome", "host": "127.0.0.1", "mqtt_broker": "127.0.0.1"},
        "panda_breath_guard": {},
    })
    with pytest.raises(ConfigError, match="firmware: stock"):
        printer.load_object(FakeConfig(printer, "printer", {}), "panda_breath_guard")


def test_m141_sets_the_chamber_target(bench):
    bench.start()
    received = bench.run_gcode_and_wait_for_frames("M141 S40", len(HEAT_TO_40_FRAMES))
    assert received == HEAT_TO_40_FRAMES
    assert bench.heater.target_temp == 40.


def test_m141_s0_switches_the_device_off(bench):
    bench.start()
    bench.run_gcode_and_wait_for_frames("M141 S40", len(HEAT_TO_40_FRAMES))
    received = bench.run_gcode_and_wait_for_frames("M141 S0", len(SWITCH_OFF_FRAMES))
    assert received == SWITCH_OFF_FRAMES
    assert bench.heater.target_temp == 0.


def over_limit_warnings(responses):
    return [response for response in responses
            if "⚠️" in response and f"limit is {CHAMBER_MAX_TEMP:g} C" in response]


def test_m141_above_the_limit_warns_and_sets_the_limit(bench):
    bench.start()
    bench.run_gcode(f"M141 S{CHAMBER_MAX_TEMP + 5:g}")
    assert bench.heater.target_temp == CHAMBER_MAX_TEMP
    assert len(over_limit_warnings(bench.gcode.responses)) == 1


def test_m141_at_the_limit_does_not_warn(bench):
    bench.start()
    bench.run_gcode(f"M141 S{CHAMBER_MAX_TEMP:g}")
    assert bench.heater.target_temp == CHAMBER_MAX_TEMP
    assert not over_limit_warnings(bench.gcode.responses)


def test_m191_above_the_limit_warns_and_waits_for_the_limit(bench):
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.device_frame_after(3., {"warehouse_temper": CHAMBER_MAX_TEMP})
    bench.run_gcode(f"M191 S{CHAMBER_MAX_TEMP + 5:g}")
    assert bench.heater.target_temp == CHAMBER_MAX_TEMP
    assert bench.reactor.monotonic() - started_at >= 3.
    assert len(over_limit_warnings(bench.gcode.responses)) == 1


def test_m191_returns_when_the_chamber_is_warm(bench):
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.device_frame_after(3., {"warehouse_temper": 40})
    bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 40.
    assert bench.reactor.monotonic() - started_at >= 3.


def start_with_u1_cavity_thermometer(bench, cavity_temp):
    cavity_thermometer = FakeTemperatureSensor(cavity_temp)
    bench.load({"use_u1_cavity_thermometer": "true"})
    bench.printer.objects[U1_CAVITY_SENSOR] = cavity_thermometer
    bench.printer.lookup_object("heaters").available_sensors.append(U1_CAVITY_SENSOR)
    bench.connect()
    return cavity_thermometer


def test_m191_returns_when_the_u1_cavity_gets_there_first(bench):
    cavity_thermometer = start_with_u1_cavity_thermometer(bench, 20.)
    started_at = bench.reactor.monotonic()
    bench.reactor.call_at(
        started_at + 3., functools.partial(setattr, cavity_thermometer, "temperature", 40.))
    bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 40.
    assert bench.reactor.monotonic() - started_at >= 3.


def test_m191_returns_when_the_panda_breath_gets_there_first(bench):
    start_with_u1_cavity_thermometer(bench, 20.)
    started_at = bench.reactor.monotonic()
    bench.device_frame_after(3., {"warehouse_temper": 40})
    bench.run_gcode("M191 S40")
    assert bench.reactor.monotonic() - started_at >= 3.


def test_the_u1_cavity_option_on_a_printer_without_one_is_refused_at_connect(bench):
    bench.load({"use_u1_cavity_thermometer": "true"})
    with pytest.raises(ConfigError, match="no U1 cavity thermometer"):
        bench.connect()


def test_m191_with_the_u1_cavity_option_off_ignores_the_cavity(bench):
    bench.start(STOP_AFTER_2_MINUTES)
    bench.printer.objects[U1_CAVITY_SENSOR] = FakeTemperatureSensor(40.)
    with pytest.raises(CommandError, match="within 2 minutes"):
        bench.run_gcode("M191 S40")


def test_m191_s0_returns_at_once(bench):
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.run_gcode("M191 S0")
    assert bench.reactor.monotonic() == started_at
    assert bench.heater.target_temp == 0.


def test_m191_without_a_wait_limit_waits_until_the_chamber_is_warm(bench):
    """Junior, cold room: the chamber reached 55 C just after the old fixed 30 minutes."""
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.device_frame_after(SLOW_WARM_UP_SECONDS, {"warehouse_temper": 40})
    bench.run_gcode("M191 S40")
    assert bench.reactor.monotonic() - started_at >= SLOW_WARM_UP_SECONDS
    assert bench.heater.target_temp == 40.


def slow_heating_warnings(responses):
    return [response for response in responses
            if "⚠️" in response and "the print goes on" in response]


def test_m191_warn_limit_warns_keeps_heating_and_lets_the_print_go_on(bench):
    bench.start({"wait_limit": "warn", "wait_limit_minutes": "2"})
    started_at = bench.reactor.monotonic()
    bench.run_gcode("M191 S40")
    assert bench.reactor.monotonic() - started_at >= 120.
    assert bench.heater.target_temp == 40.
    warnings = slow_heating_warnings(bench.gcode.responses)
    assert len(warnings) == 1
    assert warnings[0].startswith("// ")


def test_m191_stop_limit_stops_heating_and_the_print(bench):
    bench.start(STOP_AFTER_2_MINUTES)
    with pytest.raises(CommandError, match="within 2 minutes. Heating stopped"):
        bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 0.


def guard_section(bench):
    guard_options = bench.printer.sections["panda_breath_guard"]
    return FakeConfig(bench.printer, "panda_breath_guard", guard_options)


@pytest.mark.parametrize("unused_minutes", ["", "0"])
def test_with_the_wait_limit_off_unused_minutes_do_not_stop_klipper(bench, unused_minutes):
    bench.load({"wait_limit": "off", "wait_limit_minutes": unused_minutes})
    assert not guard_section(bench).unread_options()


def test_the_old_heat_wait_timeout_option_does_not_stop_klipper(bench):
    bench.start({"heat_wait_timeout": "120"})
    assert not guard_section(bench).unread_options()
    bench.device_frame_after(SLOW_WARM_UP_SECONDS, {"warehouse_temper": 40})
    bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 40.


def test_an_unknown_wait_limit_choice_is_refused(bench):
    with pytest.raises(ConfigError, match="not a valid choice"):
        bench.load({"wait_limit": "maybe"})


def test_m191_stops_on_a_device_alarm(bench):
    bench.start()
    bench.device_frame_after(3., {"ptc_heater_status": 1})
    with pytest.raises(CommandError, match="heating element reports a fault"):
        bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 0.


@pytest.mark.parametrize("commandline", [
    "PANDA_BREATH_DRY_START TEMP=30",
    "PANDA_BREATH_DRY_START TEMP=70",
])
def test_drying_outside_the_stock_range_is_refused(bench, commandline):
    bench.start()
    with pytest.raises(CommandError):
        bench.run_gcode(commandline)


def test_drying_picks_the_custom_preset_then_starts(bench):
    bench.start()
    received = bench.run_gcode_and_wait_for_frames(
        "PANDA_BREATH_DRY_START TEMP=50 HOURS=2", DRYING_FRAME_COUNT)
    preset_length = len(panda_breath_device_fixes.custom_drying_preset(50., 2.))
    assert tuple(received[:preset_length]) == panda_breath_device_fixes.custom_drying_preset(
        50., 2.)
    assert received[-2:] == [{"isrunning": 1}, {"work_on": True}]


def test_auto_mode_sends_its_target_as_set_temp(bench):
    bench.start()
    received = bench.run_gcode_and_wait_for_frames(
        "PANDA_BREATH_AUTO ENABLE=1 TARGET=45", AUTO_FRAME_COUNT)
    assert {"work_mode": 1} in received
    assert received[-1] == {"set_temp": 45}


def test_auto_mode_off_sends_no_set_temp(bench):
    bench.start()
    received = bench.run_gcode_and_wait_for_frames(
        "PANDA_BREATH_AUTO ENABLE=0", AUTO_OFF_FRAME_COUNT)
    assert received[-1] == {"work_on": False}
    assert not any("set_temp" in settings for settings in received)

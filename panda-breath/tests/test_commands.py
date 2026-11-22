# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""The G-code side: HELP texts, M141 and M191, drying and Auto mode on a fake device."""

import pytest
from conftest import HEATER_OPTIONS
from extras import panda_breath_device_fixes
from klipper_fakes import CommandError, ConfigError, FakeConfig, FakePrinter

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


def test_m141_out_of_the_heater_range_is_refused(bench):
    bench.start()
    with pytest.raises(CommandError, match="out of range"):
        bench.run_gcode(f"M141 S{float(HEATER_OPTIONS['max_temp']) + 10:g}")


def test_m191_returns_when_the_chamber_is_warm(bench):
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.device_frame_after(3., {"warehouse_temper": 40})
    bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 40.
    assert bench.reactor.monotonic() - started_at >= 3.


def test_m191_s0_returns_at_once(bench):
    bench.start()
    started_at = bench.reactor.monotonic()
    bench.run_gcode("M191 S0")
    assert bench.reactor.monotonic() == started_at
    assert bench.heater.target_temp == 0.


def test_m191_gives_up_and_stops_heating_after_the_timeout(bench):
    bench.start({"heat_wait_timeout": "120"})
    with pytest.raises(CommandError, match="within 2 minutes. Heating stopped"):
        bench.run_gcode("M191 S40")
    assert bench.heater.target_temp == 0.


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

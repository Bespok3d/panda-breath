# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Safety and slicer commands for the Panda Breath on its stock firmware.

The [panda_breath_guard] section adds, next to the vendored panda_breath module:
M141 and M191 for the chamber, device alarms that latch as faults until cleared, and a watchdog
that switches the device off when Klipper hangs or the link to the device dies.
"""

import collections
import logging
import time

from . import (
    panda_breath,
    panda_breath_chamber,
    panda_breath_device_fixes,
    panda_breath_watchdog,
)

GUARD_TICK_SECONDS = 1.
DEFAULT_HANG_TIMEOUT = 15.
DEFAULT_LINK_TIMEOUT = 30.
DEFAULT_WAIT_LIMIT_MINUTES = 30.
# The guard beats once a second and the watchdog checks once a second, so a shorter hang limit
# would mistake a busy moment for a hang.
MIN_HANG_TIMEOUT = 5.
# The vendored connect gives up after 10 s. A shorter link limit would latch a fault while the
# watchdog's kick, the reconnect pause and one connect attempt are still running.
DEVICE_CONNECT_SECONDS = 10.
MIN_LINK_TIMEOUT = (
    panda_breath_watchdog.LINK_KICK_SECONDS + panda_breath.RECONNECT_DELAY
    + DEVICE_CONNECT_SECONDS)
MACRO_SECTION_PREFIX = "gcode_macro "
HANG_FAULT = "Klipper stopped responding, so the plugin switched the Panda Breath off"
LINK_FAULT = "lost the link to the Panda Breath"
# The stock web UI accepts custom drying from 40 to 60 C only.
DRYING_MIN_TEMP = 40.
DRYING_MAX_TEMP = 60.
DRYING_DEFAULT_TEMP = 55.
CLEAR_FAULT_HELP = "Clear a latched Panda Breath fault so the chamber can heat again"


def fault_message(fault_reason):
    return (
        f"Panda Breath: {fault_reason}. Heating stopped."
        " Fix it, then run PANDA_BREATH_CLEAR_FAULT"
    )


def distinct_faults(fault_batches):
    """Flatten the fault lists of many frames into one list without repeats, in arrival order."""
    return list(dict.fromkeys(fault for faults in fault_batches for fault in faults))


def drain_alarm_batches(alarm_queue):
    """Take the fault batches the transport thread queued so far, oldest first."""
    batch_count = len(alarm_queue)
    return [alarm_queue.popleft() for _batch_number in range(batch_count)]


def plain_macro_commands(config):
    """The commands that [gcode_macro] sections define without rename_existing."""
    return {
        macro_section.get_name().split()[1].upper()
        for macro_section in config.get_prefix_sections(MACRO_SECTION_PREFIX)
        if macro_section.get("rename_existing", None) is None
    }


class PandaBreathGuard:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        self.module = self.printer.load_object(config, "panda_breath")
        if not isinstance(self.module._transport, panda_breath._WebSocketTransport):
            raise config.error("panda_breath_guard needs [panda_breath] with firmware: stock")
        self._read_options(config)
        self.watchdog = panda_breath_watchdog.DeviceWatchdog(self.module, self.hang_timeout)
        self.fault_reason = ""
        self.alarm_queue = collections.deque()
        self.pheaters = None
        self.heater = None
        self.heater_set_temp_before_guard = None
        self.printer_chamber_sensor = None
        panda_breath_device_fixes.install(self.module, self.watchdog, self.alarm_queue)
        self.guard_timer = self.reactor.register_timer(self._guard_tick, self.reactor.NEVER)
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler("klippy:disconnect", self._handle_disconnect)
        self._register_commands()
        self._register_chamber_commands(config)

    def _read_options(self, config):
        self.use_u1_cavity_thermometer = config.getboolean("use_u1_cavity_thermometer", False)
        self.hang_timeout = config.getfloat(
            "hang_timeout", DEFAULT_HANG_TIMEOUT, minval=MIN_HANG_TIMEOUT)
        self.link_timeout = config.getfloat(
            "link_timeout", DEFAULT_LINK_TIMEOUT, minval=MIN_LINK_TIMEOUT)
        self.wait_limit_action = config.getchoice(
            "wait_limit", panda_breath_chamber.WAIT_LIMIT_ACTIONS,
            panda_breath_chamber.NO_WAIT_LIMIT)
        self.wait_limit_minutes = self._read_wait_limit_minutes(config)
        self.wait_limit_seconds = panda_breath_chamber.wait_limit_seconds(
            self.wait_limit_action, self.wait_limit_minutes)
        # 0.2.0 documented this option; Klipper refuses to start on an option nobody reads.
        config.get("heat_wait_timeout", None)

    def _read_wait_limit_minutes(self, config):
        """With the limit off the minutes are unused, so a blank or 0 must not stop Klipper."""
        if self.wait_limit_action == panda_breath_chamber.NO_WAIT_LIMIT:
            config.get("wait_limit_minutes", None)
            return DEFAULT_WAIT_LIMIT_MINUTES
        return config.getfloat("wait_limit_minutes", DEFAULT_WAIT_LIMIT_MINUTES, above=0.)

    def _register_commands(self):
        """The vendored module registers its commands without a help text, so HELP hides them."""
        command_handlers = (
            ("PANDA_BREATH_AUTO", self._cmd_auto, self.module.cmd_PANDA_BREATH_AUTO_help),
            ("PANDA_BREATH_DRY_START", self._cmd_dry_start,
             self.module.cmd_PANDA_BREATH_DRY_START_help),
            ("PANDA_BREATH_DRY_STOP", self.module._cmd_panda_breath_dry_stop,
             self.module.cmd_PANDA_BREATH_DRY_STOP_help),
        )
        for command_name, handler, help_text in command_handlers:
            self.gcode.register_command(command_name, None)
            self.gcode.register_command(command_name, handler, desc=help_text)
        self.gcode.register_command(
            "PANDA_BREATH_CLEAR_FAULT", self._cmd_clear_fault, desc=CLEAR_FAULT_HELP)

    def _register_chamber_commands(self, config):
        """A user's own M141/M191 wins over the plugin's.

        Registered while the config loads, so a user macro with rename_existing finds the
        plugin's command at connect. A plain user macro that loads later would clash, so its
        section in the config already keeps the plugin's command out.
        """
        user_macro_commands = plain_macro_commands(config)
        chamber_handlers = (
            ("M141", self._cmd_m141, panda_breath_chamber.M141_HELP),
            ("M191", self._cmd_m191, panda_breath_chamber.M191_HELP),
        )
        for command_name, handler, help_text in chamber_handlers:
            self._register_unless_taken(command_name, handler, help_text, user_macro_commands)

    def _register_unless_taken(self, command_name, handler, help_text, user_macro_commands):
        taken = command_name in self.gcode.ready_gcode_handlers
        if taken or command_name in user_macro_commands:
            logging.info("panda_breath_guard: keeping the user's %s command", command_name)
            return
        self.gcode.register_command(command_name, handler, desc=help_text)

    # Klipper lifecycle

    def _handle_connect(self):
        self.pheaters = self.printer.lookup_object("heaters")
        self.printer_chamber_sensor = self._lookup_printer_chamber_sensor()
        self.heater = self.pheaters.lookup_heater(self.module.name)
        self.heater_set_temp_before_guard = self.heater.set_temp
        self.heater.set_temp = self._guarded_set_temp
        self.reactor.update_timer(self.guard_timer, self.reactor.NOW)
        self.watchdog.start()

    def _lookup_printer_chamber_sensor(self):
        if not self.use_u1_cavity_thermometer:
            return None
        if panda_breath_chamber.U1_CAVITY_SENSOR not in self.pheaters.available_sensors:
            raise self.printer.config_error(panda_breath_chamber.NO_U1_CAVITY_MESSAGE)
        return self.printer.lookup_object(panda_breath_chamber.U1_CAVITY_SENSOR)

    def _handle_disconnect(self):
        self.watchdog.stop()
        self.reactor.update_timer(self.guard_timer, self.reactor.NEVER)

    def _guarded_set_temp(self, degrees):
        if degrees > 0. and self.fault_reason:
            raise self.printer.command_error(fault_message(self.fault_reason))
        self.heater_set_temp_before_guard(degrees)

    def _guard_tick(self, eventtime):
        self.watchdog.beat()
        pending_faults = self._pending_faults()
        if pending_faults and not self.fault_reason:
            self._latch_fault("; ".join(pending_faults))
        return eventtime + GUARD_TICK_SECONDS

    def _pending_faults(self):
        pending_faults = distinct_faults(drain_alarm_batches(self.alarm_queue))
        if self.watchdog.take_hang_trip():
            pending_faults.append(HANG_FAULT)
        if self._link_lost_while_heating():
            pending_faults.append(LINK_FAULT)
        return pending_faults

    def _link_lost_while_heating(self):
        if self.fault_reason or not panda_breath_watchdog.device_may_heat(self.module):
            return False
        return panda_breath_watchdog.link_silent(
            time.monotonic(), self.watchdog.last_frame_time, self.link_timeout)

    def _latch_fault(self, fault_reason):
        self.fault_reason = fault_reason
        self.module._force_device_off(fault_reason)
        message = fault_message(fault_reason)
        logging.error(message)
        self.gcode.respond_raw("!! " + message)

    # G-code commands

    def _refuse_while_faulted(self):
        if self.fault_reason:
            raise self.printer.command_error(fault_message(self.fault_reason))

    def _cmd_auto(self, gcmd):
        enable_wanted = gcmd.get_int("ENABLE", int(self.module.auto_enabled), minval=0, maxval=1)
        if enable_wanted:
            self._refuse_while_faulted()
        self.module._cmd_panda_breath_auto(gcmd)

    def _cmd_dry_start(self, gcmd):
        self._refuse_while_faulted()
        gcmd.get_float(
            "TEMP", DRYING_DEFAULT_TEMP, minval=DRYING_MIN_TEMP, maxval=DRYING_MAX_TEMP)
        self.module._cmd_panda_breath_dry_start(gcmd)

    def _cmd_clear_fault(self, gcmd):
        if not self.fault_reason:
            gcmd.respond_info("Panda Breath: no fault to clear")
            return
        self.fault_reason = ""
        self.alarm_queue.clear()
        gcmd.respond_info(
            "Panda Breath: fault cleared. A device that still reports an alarm latches it again")

    def _chamber_target(self, gcmd):
        """A target above the heater's max_temp is lowered to it, so the print is not cancelled."""
        wanted_target = gcmd.get_float("S", 0., minval=0.)
        if wanted_target <= self.heater.max_temp:
            return wanted_target
        # Not the "!!" error prefix: OctoPrint disconnects on it, and the print stops.
        self.gcode.respond_info(
            panda_breath_chamber.over_limit_warning(wanted_target, self.heater.max_temp))
        return self.heater.max_temp

    def _cmd_m141(self, gcmd):
        self.pheaters.set_temperature(self.heater, self._chamber_target(gcmd))

    def _cmd_m191(self, gcmd):
        wanted_target = self._chamber_target(gcmd)
        self.pheaters.set_temperature(self.heater, wanted_target)
        if not wanted_target or self.printer.get_start_args().get("debugoutput") is not None:
            return
        self._finish_wait(self._wait_for_chamber(wanted_target), wanted_target)

    def _wait_for_chamber(self, wanted_target):
        toolhead = self.printer.lookup_object("toolhead")
        started_at = self.reactor.monotonic()
        eventtime = started_at
        outcome = self._wait_outcome(eventtime, started_at, wanted_target)
        while outcome == panda_breath_chamber.KEEP_WAITING:
            # Klipper's own M190 does the same, so the toolhead clock stays current during the wait.
            toolhead.get_last_move_time()
            eventtime = self.reactor.pause(eventtime + panda_breath_chamber.WAIT_STEP_SECONDS)
            outcome = self._wait_outcome(eventtime, started_at, wanted_target)
        return outcome

    def _wait_outcome(self, eventtime, started_at, wanted_target):
        snapshot = panda_breath_chamber.ChamberWaitSnapshot(
            klipper_shutdown=self.printer.is_shutdown(),
            fault_reason=self.fault_reason,
            heater_target=self.heater.get_temp(eventtime)[1],
            target_not_reached=self._chamber_target_not_reached(eventtime, wanted_target),
            waited_seconds=eventtime - started_at,
        )
        return panda_breath_chamber.wait_outcome(snapshot, wanted_target, self.wait_limit_seconds)

    def _chamber_target_not_reached(self, eventtime, wanted_target):
        """The wait ends when the Panda Breath or the printer's own thermometer gets there first."""
        reached_by_printer = panda_breath_chamber.printer_chamber_reached(
            self._printer_chamber_temp(eventtime), wanted_target)
        return self.heater.check_busy(eventtime) and not reached_by_printer

    def _printer_chamber_temp(self, eventtime):
        if self.printer_chamber_sensor is None:
            return None
        return self.printer_chamber_sensor.get_temp(eventtime)[0]

    def _finish_wait(self, outcome, wanted_target):
        if outcome == panda_breath_chamber.FAULTED:
            raise self.printer.command_error(fault_message(self.fault_reason))
        if outcome != panda_breath_chamber.TIMED_OUT:
            return
        if self.wait_limit_action == panda_breath_chamber.WARN_AT_WAIT_LIMIT:
            # Not the "!!" error prefix: OctoPrint disconnects on it, and the print stops.
            self.gcode.respond_info(
                panda_breath_chamber.slow_heating_warning(wanted_target, self.wait_limit_minutes))
            return
        self.pheaters.set_temperature(self.heater, 0.)
        raise self.printer.command_error(
            panda_breath_chamber.timeout_message(wanted_target, self.wait_limit_minutes))

    def get_status(self, eventtime):
        return {"fault": bool(self.fault_reason), "fault_reason": self.fault_reason}


def load_config(config):
    return PandaBreathGuard(config)

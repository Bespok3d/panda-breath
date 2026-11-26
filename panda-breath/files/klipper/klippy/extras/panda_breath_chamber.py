# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Decide, once per second, how an M191 chamber wait goes on."""

import collections
import math

M141_HELP = "Set the Panda Breath chamber temperature (S=<C>, S0 switches it off)"
M191_HELP = (
    "Set the Panda Breath chamber temperature and wait until the chamber reaches it (S=<C>)"
)

U1_CAVITY_SENSOR = "temperature_sensor cavity"
NO_U1_CAVITY_MESSAGE = (
    "Panda Breath: this printer has no U1 cavity thermometer."
    " Switch off \"Also use the U1 cavity thermometer\" in the plugin settings"
)

WAIT_STEP_SECONDS = 1.
TARGET_CHANGE_TOLERANCE = 0.01
SECONDS_PER_MINUTE = 60.

KEEP_WAITING = "keep waiting"
REACHED = "reached"
FAULTED = "faulted"
TIMED_OUT = "timed out"
CANCELLED = "cancelled"

NO_WAIT_LIMIT = "off"
WARN_AT_WAIT_LIMIT = "warn"
STOP_AT_WAIT_LIMIT = "stop"
WAIT_LIMIT_ACTIONS = {
    action: action for action in (NO_WAIT_LIMIT, WARN_AT_WAIT_LIMIT, STOP_AT_WAIT_LIMIT)
}

ChamberWaitSnapshot = collections.namedtuple(
    "ChamberWaitSnapshot",
    ("klipper_shutdown", "fault_reason", "heater_target", "target_not_reached", "waited_seconds"),
)


def wait_outcome(snapshot, wanted_target, timeout_seconds):
    """Return what an M191 wait does next, given one look at the chamber."""
    target_changed = abs(snapshot.heater_target - wanted_target) > TARGET_CHANGE_TOLERANCE
    outcome_checks = (
        (snapshot.klipper_shutdown, CANCELLED),
        (bool(snapshot.fault_reason), FAULTED),
        (target_changed, CANCELLED),
        (not snapshot.target_not_reached, REACHED),
        (snapshot.waited_seconds >= timeout_seconds, TIMED_OUT),
    )
    return next((outcome for happened, outcome in outcome_checks if happened), KEEP_WAITING)


def wait_limit_seconds(wait_limit_action, wait_limit_minutes):
    """With the limit off, M191 waits as long as Klipper's own M190 does: until the target."""
    if wait_limit_action == NO_WAIT_LIMIT:
        return math.inf
    return wait_limit_minutes * SECONDS_PER_MINUTE


def printer_chamber_reached(printer_chamber_temp, wanted_target):
    """None means no printer chamber thermometer is set, so only the Panda Breath counts."""
    return printer_chamber_temp is not None and printer_chamber_temp >= wanted_target


def over_limit_warning(wanted_target, chamber_max_temp):
    return (
        f"⚠️⚠️⚠️ Panda Breath: the print asked for a {wanted_target:g} C chamber,"
        f" but the limit is {chamber_max_temp:g} C. The chamber is set to"
        f" {chamber_max_temp:g} C and the print goes on ⚠️⚠️⚠️"
    )


def timeout_message(wanted_target, wait_limit_minutes):
    return (
        f"Panda Breath: the chamber did not reach {wanted_target:.0f} C"
        f" within {wait_limit_minutes:g} minutes. Heating stopped"
    )


def slow_heating_warning(wanted_target, wait_limit_minutes):
    return (
        f"⚠️⚠️⚠️ Panda Breath: the chamber did not reach {wanted_target:.0f} C"
        f" within {wait_limit_minutes:g} minutes. It keeps heating and the print goes on ⚠️⚠️⚠️"
    )

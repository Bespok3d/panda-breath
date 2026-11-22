# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Decide, once per second, how an M191 chamber wait goes on."""

import collections

M141_HELP = "Set the Panda Breath chamber temperature (S=<C>, S0 switches it off)"
M191_HELP = (
    "Set the Panda Breath chamber temperature and wait until the chamber reaches it (S=<C>)"
)

WAIT_STEP_SECONDS = 1.
TARGET_CHANGE_TOLERANCE = 0.01
SECONDS_PER_MINUTE = 60.

KEEP_WAITING = "keep waiting"
REACHED = "reached"
FAULTED = "faulted"
TIMED_OUT = "timed out"
CANCELLED = "cancelled"

ChamberWaitSnapshot = collections.namedtuple(
    "ChamberWaitSnapshot",
    ("klipper_shutdown", "fault_reason", "heater_target", "still_heating", "waited_seconds"),
)


def wait_outcome(snapshot, wanted_target, timeout_seconds):
    """Return what an M191 wait does next, given one look at the chamber."""
    target_changed = abs(snapshot.heater_target - wanted_target) > TARGET_CHANGE_TOLERANCE
    outcome_checks = (
        (snapshot.klipper_shutdown, CANCELLED),
        (bool(snapshot.fault_reason), FAULTED),
        (target_changed, CANCELLED),
        (not snapshot.still_heating, REACHED),
        (snapshot.waited_seconds >= timeout_seconds, TIMED_OUT),
    )
    return next((outcome for happened, outcome in outcome_checks if happened), KEEP_WAITING)


def timeout_message(wanted_target, timeout_seconds):
    timeout_minutes = round(timeout_seconds / SECONDS_PER_MINUTE, 1)
    return (
        f"Panda Breath: the chamber did not reach {wanted_target:.0f} C"
        f" within {timeout_minutes:g} minutes. Heating stopped"
    )

# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Turn the alarm fields the stock Panda Breath firmware sends into plain fault texts.

The vendored transport drops these fields, so the guard reads each frame a second time here.
"""

import json

SENSOR_ALARM_KEYS = (
    ("ptc_sensor_status", "heater sensor"),
    ("warehouse_sensor_status", "chamber sensor"),
)
SENSOR_PROBLEMS = {
    1: "is short-circuited",
    2: "is open (unplugged or a broken wire)",
}
# The stock web UI shows its "PTC Heater Abnormal" dialog whenever this key is present, whatever
# its value, so the device only sends it when the heating element is in trouble.
HEATER_ALARM_KEY = "ptc_heater_status"
HEATER_PROBLEM = "heating element reports a fault"


def settings_from_frame(payload):
    """Return the settings object of one WebSocket text frame, or {} when it has none."""
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(message, dict):
        return {}
    settings = message.get("settings")
    return settings if isinstance(settings, dict) else {}


def sensor_problem(raw_status):
    """Return what is wrong with a sensor for one status value, or None when it is fine."""
    try:
        status_code = int(raw_status)
    except (TypeError, ValueError):
        return None
    return SENSOR_PROBLEMS.get(status_code)


def alarm_faults(settings):
    """Return one plain text per alarm present in a settings object."""
    faults = [
        f"{sensor_name} {sensor_problem(settings[alarm_key])}"
        for alarm_key, sensor_name in SENSOR_ALARM_KEYS
        if alarm_key in settings and sensor_problem(settings[alarm_key])
    ]
    if HEATER_ALARM_KEY in settings:
        faults.append(HEATER_PROBLEM)
    return faults

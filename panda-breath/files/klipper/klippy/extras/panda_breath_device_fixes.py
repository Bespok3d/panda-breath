# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Add to the vendored WebSocket transport what the stock V1.0.4 firmware needs.

Each fix wraps one transport method on the instance and then calls the vendored method, so the
vendored file stays untouched and a re-vendor keeps working.
"""

import functools
import threading

from . import panda_breath_alarms

DRYING_WORK_MODE = 3
# The stock web UI picks the "custom" drying preset with filament_drying_mode 3 after it sets the
# drying temperature and again after it sets the timer; without it the device keeps its preset.
CUSTOM_DRYING_PRESET = 3
OFF_SEQUENCE = ({"isrunning": 0}, {"work_on": False})


def install(module, watchdog, alarm_queue):
    """Wrap the transport so frames feed the watchdog and alarms, and commands reach the device."""
    transport = module._transport
    transport._dispatch = functools.partial(
        dispatch_with_alarms, transport._dispatch, watchdog, alarm_queue)
    transport.set_auto_mode = functools.partial(
        set_auto_mode_with_target, transport, transport.set_auto_mode)
    transport.start_drying = functools.partial(
        start_drying_with_preset, transport, transport.start_drying)
    transport.force_off = functools.partial(
        force_off_without_blocking, module, transport.force_off)


def dispatch_with_alarms(vendored_dispatch, watchdog, alarm_queue, payload):
    """Runs on the transport thread for every frame from the device."""
    watchdog.note_frame()
    faults = panda_breath_alarms.alarm_faults(panda_breath_alarms.settings_from_frame(payload))
    if faults:
        alarm_queue.append(faults)
    vendored_dispatch(payload)


def set_auto_mode_with_target(transport, vendored_set_auto_mode, *auto_settings):
    """The vendored code sends the Auto target as "temp"; stock firmware reads "set_temp"."""
    vendored_set_auto_mode(*auto_settings)
    auto_enabled, auto_target, _filter_temp, _bed_temp = auto_settings
    if auto_enabled:
        transport._send_settings({"set_temp": int(auto_target)})


def start_drying_with_preset(transport, vendored_start_drying, drying_temp, drying_hours):
    for fields in custom_drying_preset(drying_temp, drying_hours):
        transport._send_settings(fields)
    vendored_start_drying(drying_temp, drying_hours)


def custom_drying_preset(drying_temp, drying_hours):
    """The settings the stock web UI sends to start a custom drying run, in its order."""
    return (
        {"work_mode": DRYING_WORK_MODE},
        {"filament_temp": int(drying_temp)},
        {"filament_drying_mode": CUSTOM_DRYING_PRESET},
        {"filament_timer": int(drying_hours)},
        {"filament_drying_mode": CUSTOM_DRYING_PRESET},
    )


def force_off_without_blocking(module, vendored_force_off):
    """Switch the device off without stalling a running Klipper.

    The vendored force off ends with one-shot sends that wait up to two seconds each for a device
    that does not answer, even while the main connection still looks alive, and a reactor that
    stalls that long mid-print makes Klipper shut down. So a running Klipper sends the off on the
    main connection at once and leaves the one-shot sends to a thread. A Klipper going down waits
    instead: right after this the vendored disconnect closes the connection and the process may
    exit, which would drop the "off" a thread had not sent yet.
    """
    if module._in_shutdown:
        vendored_force_off()
        return
    transport = module._transport
    forget_wanted_state(transport)
    for fields in OFF_SEQUENCE:
        transport._send_settings(fields)
    threading.Thread(
        target=functools.partial(send_off_once_then_restore, module),
        name="panda_breath_force_off", daemon=True).start()


def send_off_once_then_restore(module):
    """Runs on its own thread, so a silent device stalls only this thread."""
    for fields in OFF_SEQUENCE:
        module._transport._send_settings_once(fields)
    module.reactor.register_async_callback(
        functools.partial(restore_wanted_state, module._transport))


def restore_wanted_state(transport, eventtime):
    """Runs on the reactor once the late "off" landed.

    Heat asked for while the one-shot sends were still on their way reached the device first, so
    without this the device would end up off while Klipper thinks it heats. The order matches the
    vendored resend after a reconnect.
    """
    if transport._last_drying is not None:
        transport.start_drying(*transport._last_drying)
        return
    if transport._last_auto is not None and transport._last_auto[0]:
        transport.set_auto_mode(*transport._last_auto)
        return
    if transport._last_target > 0:
        transport.set_target(transport._last_target)


def forget_wanted_state(transport):
    """Make the next reconnect send "off", as the vendored force off does."""
    transport._last_target = 0.
    transport._last_auto = None
    transport._last_drying = None

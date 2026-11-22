# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""The Klipper config the plugin installs."""

import configparser
import pathlib

CONFIG_TEMPLATE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "files" / "cfg" / "klipper" / "panda-breath.cfg.tmpl"
)


def installed_config():
    klipper_config = configparser.ConfigParser(interpolation=None)
    klipper_config.read_string(CONFIG_TEMPLATE.read_text(encoding="utf-8"))
    return klipper_config


def test_heating_rate_check_never_shuts_the_printer_down():
    """Klipper counts a heating-rate error only below target minus hysteresis.

    The slicer's chamber fan held the Panda Breath reading at 49 C for three minutes at target 55,
    and the old hysteresis of 5 shut the printer down. Even the highest target must leave nothing
    to count above min_temp, below which Klipper stops the printer for its own reason.
    """
    klipper_config = installed_config()
    heater = klipper_config["heater_generic panda_breath"]
    rate_check = klipper_config["verify_heater panda_breath"]
    lowest_counted_temp = heater.getfloat("max_temp") - rate_check.getfloat("hysteresis")
    assert lowest_counted_temp <= heater.getfloat("min_temp")

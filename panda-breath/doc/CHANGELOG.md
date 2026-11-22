# Changelog

## 0.2.0

- New: `M141` and `M191` set the chamber temperature from your slicer's start G-code. `M191` waits
  until the chamber is warm.
- New: a broken sensor or heating element on the Panda Breath now stops the heat and shows a plain
  Klipper error. The error stays until you run `PANDA_BREATH_CLEAR_FAULT`.
- New: if Klipper hangs, or the Panda Breath goes silent while heating, the plugin switches the heat
  off.
- New: after the Panda Breath restarts, it gets back the temperature Klipper wants. When Klipper
  starts, the Panda Breath is switched off first.
- Every plugin command now shows in Klipper's `HELP` list.
- The plugin is now stable: it is in daily use on a real Panda Breath.
- Fix: a print no longer stops with "Heater panda_breath not heating at expected rate" when the
  slicer's chamber fan slows the warm up.
- Fix: Auto mode now sends its target temperature to the Panda Breath.
- Fix: filament drying now uses your temperature and hours. The stock firmware allows 40 to 60 C,
  so other values are refused.

## 0.1.1

- Licensing only, nothing about how the plugin works has changed. The files it installs that came
  from other projects now carry those projects' own licence notices, plus a line recording what
  Bespok3d changed in them and when.

## 0.1.0

- First release. Vendors the GPL-3.0 `panda_breath.py` Klipper extra (pinned upstream commit) and a
  `[heater_generic]` config so a BIQU Panda Breath works as a standard Klipper heater. Experimental,
  unproven on a real Panda Breath, which we do not have.

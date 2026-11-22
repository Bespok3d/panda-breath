# Panda Breath

Controls a [BIQU Panda Breath](https://github.com/justinh-rahb/pandabreath-klipper) chamber heater
from Klipper as a standard `heater_generic`. After installing, set the heater target from Fluidd or
Mainsail (or your slicer) like any other heater.

## What you need

- A Panda Breath device on your network (running stock OEM firmware). This plugin does not supply or
  flash the hardware; it teaches Klipper how to talk to a device you already have.
- Set **Panda Breath host** to its hostname or IP. If `.local` resolution fails, use the IP.

## Slicer start G-code

| Command | What it does |
| --- | --- |
| `M141 S45` | Set the chamber to 45 C and go on at once. `M141 S0` switches the heat off. |
| `M191 S45` | Set the chamber to 45 C and wait until it gets there. `M191 S0` switches off and goes on. |

If your printer config already has its own `M141` or `M191` macro, the plugin keeps yours. Remove
your macro if you want the plugin's version. A macro with `rename_existing` wraps the plugin's
version instead.

`M191` gives up after 30 minutes (set `heat_wait_timeout`, in seconds). Then it switches the heat
off and stops with a plain error.

**Warning, OrcaSlicer:** the filament's chamber **Minimal** temperature does nothing. Orca waits
for the **Target** temperature (`M191 S<target>`) before it prints. To start printing at a lower
temperature and keep heating, turn off Orca's chamber temperature control and put these two lines
in your start G-code. Snapmaker Orca has no Minimal setting and also waits for Target; the same
two lines work there:

```gcode
M191 S45 ; wait until the chamber reaches 45 C
M141 S55 ; keep heating to 55 C while it prints
```

## Other commands

All of them show in Klipper's `HELP` list.

| Command | What it does |
| --- | --- |
| `PANDA_BREATH_AUTO ENABLE=1 TARGET=45` | Turn on the Panda Breath's own Auto mode. `ENABLE=0` turns it off. |
| `PANDA_BREATH_DRY_START TEMP=55 HOURS=6` | Dry filament. The stock firmware allows 40 to 60 C. |
| `PANDA_BREATH_DRY_STOP` | Stop drying. |
| `PANDA_BREATH_CLEAR_FAULT` | Clear a fault once you fixed its cause, so the chamber can heat again. |

## Safety

- **Device alarms.** When the Panda Breath reports a broken sensor (short or open) or a heating
  element fault, Klipper switches the heat off and shows the problem in plain words. The fault stays
  until you run `PANDA_BREATH_CLEAR_FAULT`, even if the alarm goes away. While it stays, nothing can
  start the heat again.
- **Klipper hangs.** If Klipper stops responding for 15 seconds (`hang_timeout`), the plugin
  switches the Panda Breath off by itself.
- **Link lost.** If the Panda Breath goes silent while heating for 30 seconds (`link_timeout`),
  Klipper shows a fault and the heat stays off. A shorter drop just reconnects.
- **Panda Breath restarts.** The plugin reconnects and puts back the temperature Klipper wants.
- **Printer restarts.** When Klipper starts, the Panda Breath is switched off first.
- **Slow heating does not stop the print.** A fan can keep the chamber from warming for a while.
  Klipper's "not heating at expected rate" check is set so it never stops the printer for that.
  The checks above still stop a real fault.

The three timeouts go in the `[panda_breath_guard]` section, in seconds:

```ini
[panda_breath_guard]
hang_timeout: 15
link_timeout: 30
heat_wait_timeout: 1800
```

The shortest allowed values are 5 for `hang_timeout` and 25 for `link_timeout`. Shorter would
raise false alarms while the plugin is still reconnecting.

When the Panda Breath is powered from the printer, a printer power cut switches it off too.

What the plugin cannot cover: if Klipper is killed hard (for example by the out of memory killer),
the watchdog dies with it. Then the Panda Breath keeps the last setting it had.

## Status

**Stable.** In daily use on a real Panda Breath with the stock firmware.

## Credits / license

The Klipper module `panda_breath.py` is vendored from
[justinh-rahb/pandabreath-klipper](https://github.com/justinh-rahb/pandabreath-klipper) at commit
`2fc8c03b918519060f0a2cc6b40a56fbc232e74f`, licensed **GPL-3.0**. The only change is normalizing a
few dash characters in comments to satisfy our linter; no code was changed.

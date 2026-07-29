# Attributions - panda-breath

**Plugin author:** justinh-rahb (BIQU / BIGTREETECH hardware), packaged by Bespok3d; Panda Breath support on the U1 was first done by @justinh-rahb in the Extended Firmware overlay `37-feature-panda-breath`

Drives a BIQU Panda Breath chamber heater.

| Upstream project | Author | Licence | Needed at runtime | Code ships in this package |
| --- | --- | --- | --- | --- |
| pandabreath-klipper | justinh-rahb | GPL-3.0 | yes | yes |
| Panda Breath hardware | BIQU / BIGTREETECH | hardware | yes | no |

`panda_breath.py` is shipped inside this plugin at pinned commit
`2fc8c03b918519060f0a2cc6b40a56fbc232e74f`, unchanged apart from normalising a dash character.
Upstream: https://github.com/justinh-rahb/pandabreath-klipper

Ported from the Extended Firmware overlay `37-feature-panda-breath`, GPL-3.0, whose commits are by
paxx12 and one further contributor recorded in that project's own history; the chamber-heater work is
credited to @justinh-rahb.

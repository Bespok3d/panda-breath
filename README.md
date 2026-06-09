# panda-breath

A standalone Bespok3d plugin: drives a BIQU Panda Breath chamber heater as a standard Klipper heater
on any Klipper printer (not U1-specific). Solo repo - publishes a single atom into `Bespok3d/main-index`.

```text
panda-breath/
  panda-breath/         # the plugin (manifest + files + doc)
  scripts/{pack.sh,generate-atom.mjs}
  .github/workflows/release.yml
```

The Klipper module `panda_breath.py` is vendored from
[justinh-rahb/pandabreath-klipper](https://github.com/justinh-rahb/pandabreath-klipper) (GPL-3.0, pinned
commit). See the plugin's `doc/README.md` for credits.

## Releasing

Bump `panda-breath/manifest.json` `version` and push to `main`. CI packs the `.b3`, cuts a release,
generates the atom, and commits it into `Bespok3d/main-index/atoms/`. Secret: `MAIN_INDEX_TOKEN`.

## Maintainership

Published and maintained by the Bespok3d org. If you own the upstream source and would rather manage
this yourself, contact the org to claim it - on the condition it stays actively maintained.

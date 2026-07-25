# panda-breath

A standalone Bespok3d plugin: drives a BIQU Panda Breath chamber heater as a standard Klipper heater
on any Klipper printer (not U1-specific). Solo repo - publishes a single atom into `Bespok3d/main-index`.

```text
panda-breath/
  panda-breath/         # the plugin (manifest + files + doc)
  .github/workflows/release.yml
```

The Klipper module `panda_breath.py` is vendored from
[justinh-rahb/pandabreath-klipper](https://github.com/justinh-rahb/pandabreath-klipper) (GPL-3.0, pinned
commit). See the plugin's `doc/README.md` for credits.

## Build locally

Needs Node.js 20+. Builds run through the shared `Bespok3d/b3-builder` tool:

```sh
npm install github:Bespok3d/b3-builder
npx b3-builder build --source ./panda-breath --atom-repo Bespok3d/panda-breath
# -> dist/panda-breath-<ver>.b3 + dist/panda-breath.atom.json
```

## Releasing

Bump `panda-breath/manifest.json` `version` and push to `main`. CI runs the `Bespok3d/b3-builder`
Action, which packs the `.b3` and cuts a release; the `register-atoms` action from
`Bespok3d/main-index` then registers the atom. This repo contributes atoms only and publishes no list
of its own. Secrets: `MAIN_INDEX_TOKEN` (contents:write on main-index) and `REGISTRY_SIGNING_KEY` (the
org registry key the `b3-builder` Action signs each `.b3` and atom with).

## Maintainership

Published and maintained by the Bespok3d org. If you own the upstream source and would rather manage
this yourself, contact the org to claim it - on the condition it stays actively maintained.

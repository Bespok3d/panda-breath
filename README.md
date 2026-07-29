# panda-breath

[![licence](https://img.shields.io/badge/licence-GPL--3.0-blue)](LICENSE)
[![release](https://img.shields.io/github/v/release/Bespok3d/panda-breath)](https://github.com/Bespok3d/panda-breath/releases)
[![version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FBespok3d%2Fpanda-breath%2Fmain%2Fpanda-breath%2Fmanifest.json&query=%24.version&label=version&color=blue)](panda-breath/manifest.json)
![printer](https://img.shields.io/badge/printer-Snapmaker%20U1-informational)
![stock firmware](https://img.shields.io/badge/stock%20firmware-no%20flashing-brightgreen)

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

## Licence

Copyright (C) 2026 unlucio and the Bespok3d contributors

This repo ships code from other projects offered under version 3 of the GNU General Public License,
with no option to use a later version, so version 3 of that licence covers every file in this repo.

This program is free software: you can redistribute it and/or modify it under the terms of version 3
of the GNU General Public License as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not,
see <https://www.gnu.org/licenses/>. The full text is in [LICENSE](LICENSE).

Bespok3d's own code elsewhere is AGPL-3.0-or-later. One licence covering this whole repo is a clarity
choice, so that nobody has to work out which file carries which terms. Version 3 of the GPL and
version 3 of the AGPL may be combined in a single work, and section 13 of each licence says so; what
cannot happen is code offered under version 3 of the GPL alone being re-offered under the AGPL.

Bespok3d is a project of the Bespok3d Organisation, which is not a legal entity. Copyright is held by
the individual authors named above.

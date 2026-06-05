# Command line

Installing gmat-czml provides a `gmat-czml` console script with three subcommands — `convert`,
`serve`, and `upload`. Each reads a trajectory the format layer understands and assembles the same
CZML document the [`to_czml`][gmat_czml.to_czml] API produces; they are thin drivers over that one
call, so the CLI and the API stay byte-for-byte in step. The three share the rendering flags
(`--style`, `--playback-seconds`, `--ground-track`), so one input yields the same document whichever
you reach for.

## `gmat-czml convert`

Read a trajectory and write its `.czml` to disk.

```bash
gmat-czml convert INPUT -o OUTPUT [--style PRESET] [--playback-seconds SECONDS] [--ground-track]
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | the trajectory to convert — any file orbit-formats can read (OEM, GMAT report, SP3, STK ephemeris, …) |
| `-o`, `--output PATH` | where to write the `.czml` document (required) |
| `--style` | a style preset: `sat-default` (the default), `sat-red`, `sat-green`, or `sat-magenta` |
| `--playback-seconds SECONDS` | wall-clock seconds the whole trajectory plays back in (default: 60) |
| `--ground-track` | also emit each object's sub-satellite ground track (Earth-only) |

The CLI offers the named presets; the full colour / width / glyph customization API (custom colours,
widths, fonts, and image-billboard glyphs) is the Python [`Style`][gmat_czml.Style] — see
[Styling](styling.md).

```bash
# A GMAT OEM to CZML, with a ground track
gmat-czml convert mission.oem -o mission.czml --ground-track

# Slower playback (the span plays back over two minutes)
gmat-czml convert mission.oem -o mission.czml --playback-seconds 120

# A colour preset, to tell one object apart from another
gmat-czml convert mission.oem -o mission.czml --style sat-red
```

## `gmat-czml serve`

Assemble the same document and host it over http behind an embedded CesiumJS viewer, instead of
writing a file. Needs the optional `[server]` extra.

```bash
gmat-czml serve mission.oem --ground-track          # opens http://127.0.0.1:8080/
```

Full options and behaviour are on the [Server mode](server.md) page.

## `gmat-czml upload`

Assemble the same document and upload it to Cesium ion as a hosted asset, authenticated with a
Cesium ion access token (`--token` or the `CESIUM_ION_TOKEN` environment variable). Needs the
optional `[ion]` extra.

```bash
gmat-czml upload mission.oem --name "Mission LEO" --ground-track
```

Full options and behaviour are on the [Cesium ion upload](ion.md) page.

## Exit status and errors

Every subcommand returns `0` on success and `1` for a read failure, a non-trajectory input, or an
assembly error — each reported as a one-line `gmat-czml: …` message on standard error. An input that
orbit-formats reads as something other than a state ephemeris is reported as such rather than
producing an empty document. `serve` and `upload` add their own failure modes — a missing extra, a
missing token, an ion-side error — reported the same one-line way.

The document `convert` writes is byte-for-byte identical to `to_czml(read(INPUT), …).to_json()`, so
anything you can do from the CLI you can do from [the API](getting-started.md), and vice versa.

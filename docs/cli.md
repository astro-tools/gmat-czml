# Command line

Installing gmat-czml provides a `gmat-czml` console script. Its one subcommand, `convert`, reads any
trajectory the format layer can read and writes the same CZML document the
[`to_czml`][gmat_czml.to_czml] API produces — it is a thin driver over that one call, so the
CLI and the API stay byte-for-byte in step.

## `gmat-czml convert`

```bash
gmat-czml convert INPUT -o OUTPUT [--style sat-default] [--playback-seconds SECONDS] [--ground-track]
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | the trajectory to convert — any file orbit-formats can read (OEM, GMAT report, SP3, STK ephemeris, …) |
| `-o`, `--output PATH` | where to write the `.czml` document (required) |
| `--style` | the visual style; v0.1 offers the single `sat-default` (the default) |
| `--playback-seconds SECONDS` | wall-clock seconds the whole trajectory plays back in (default: 60) |
| `--ground-track` | also emit each object's sub-satellite ground track (Earth-only) |

## Examples

```bash
# A GMAT OEM to CZML, with a ground track
gmat-czml convert mission.oem -o mission.czml --ground-track

# Slower playback (the span plays back over two minutes)
gmat-czml convert mission.oem -o mission.czml --playback-seconds 120
```

## Exit status and errors

`convert` returns `0` on success and `1` for a read failure, a non-trajectory input, or an assembly
error — each reported as a one-line `gmat-czml: …` message on standard error. An input that
orbit-formats reads as something other than a state ephemeris is reported as such rather than
producing an empty document.

The written document is byte-for-byte identical to `to_czml(read(INPUT), …).to_json()`, so anything
you can do from the CLI you can do from [the API](getting-started.md), and vice versa.

# Contributing to gmat-czml

Thanks for your interest. This page is the one place to learn the workflow.

## Getting set up

```bash
git clone https://github.com/astro-tools/gmat-czml.git
cd gmat-czml
uv sync --all-groups
```

This installs the package, its runtime dependencies, and the dev and docs groups. The headless
CesiumJS checks also need a browser:

```bash
uv run playwright install chromium
```

## Branches and PRs

- One issue per branch. Branch names use a short prefix for type:
  - `feat/<slug>` — new capability, tied to a `type:feature` issue.
  - `fix/<slug>` — bug fix, tied to a `type:bug` issue.
  - `chore/<slug>` — infra / tooling / hygiene.
  - `docs/<slug>` — docs-only change.
- Open a PR against `main`. Put `Closes #<N>` in the PR description so the issue auto-closes on
  merge and the project board advances the card to Done.
- Squash-merge is the only merge method. The PR title becomes the squash commit subject — write
  it as a complete imperative sentence.

## Local checks before pushing

```bash
uv run pytest -m "not browser"   # tests (skip the browser checks)
uv run pytest -m browser         # the headless CesiumJS checks (needs chromium)
uv run ruff check                # lint
uv run ruff format --check       # formatting
uv run mypy                      # types
```

CI re-runs these on Ubuntu, Windows, and macOS across Python 3.10, 3.11, and 3.12, plus the CZML
validation and headless CesiumJS-parse jobs.

## Commit messages

Keep them short and imperative. One subject line, optional body.

Do not include AI or tool attribution trailers in commits, PR titles, PR descriptions, or
comments — see the repo-level convention.

## Scope discipline

gmat-czml converts an already-computed trajectory into CZML; it does not propagate, integrate, or
render. Reading trajectory files and the canonical schema are owned by the org's format-I/O
library. Before opening a feature issue, check the design decisions and existing issues to make
sure the work belongs here.

## Questions

Open a [discussion](https://github.com/orgs/astro-tools/discussions) rather than an issue for
open-ended questions, usage help, or brainstorming. The astro-tools org runs a single shared
discussions space — there is no per-repo discussions board.

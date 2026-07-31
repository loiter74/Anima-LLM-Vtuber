# CI Gate Strategy — Animetta (2026-08-01)

> Branch: `ci-gate-2026-08-01`. This document records the gate design, the
> three gaps it closes, what was implemented, and the one manual step
> (branch protection) that can't be set from repo files.

## Background: the gate was already mature — I was wrong

During the 2026-07-25 audit I called the CI gate "weak". That was a
measurement error — `ls .github/workflows` under Git Bash's pathspec parser
underreported the files. After reading `.github/workflows/quality.yml` and
`tooling/quality/` in full, the **remote** gate is in fact sophisticated:

- `quality.yml` runs a **matrixed, tiered (quick / affected / full / nightly),
  impact-aware** pipeline driven by `tooling/quality` (a custom planner with
  fingerprinting, a bounded weighted DAG scheduler, and trust-scoped caching).
- `tooling.quality.aggregate` (`tooling/quality/cli.py:631-652`) returns the
  correct exit code 0/1, and the `quality-gate` job really fails the run.
- Zeabur deploy (`deploy-zeabur.yml`) chains on `Quality` via `workflow_run`,
  so **the gate actually blocks release**.

So the gate's *remote enforcement* was already production-grade. The real
gaps were around it — feedback speed and contributor discipline.

## The three real gaps

| # | Gap | Symptom | Cost |
|---|---|---|---|
| 1 | **No local pre-commit hook** | Trivial lint/import/format errors only caught after push | Minute-scale feedback for sub-second problems |
| 2 | **No fast CI preflight** | PR runs straight into the affected-tier matrix (setup-python/node + plan download + per-group boot) before surfacing a trivial lint failure | Minute-scale CI waste on broken pushes |
| 3 | **No PR template / CODEOWNERS** | No structured self-check or review-request convention | Inconsistent review diligence; no prep for a 2nd contributor |

## What was implemented

### Part 1 — Local pre-commit gate (`.pre-commit-config.yaml`)

`make install-hooks` installs a sub-second hook that runs on every commit:

| Hook | What | Why |
|---|---|---|
| `ruff check --exit-non-zero-on-fix` | lint | catches import/usage errors; fails if it auto-fixes (forces a conscious re-stage) |
| `ruff format --check` | format | verify-only, never writes |
| `detect-private-key` | secrets | blocks unrecoverable secret commits |
| `check-added-large-files` (≤1 MB) | binaries | blocks model/large-file accidents (excludes `artifacts/`) |
| `check-merge-conflict` | git | blocks unresolved conflict markers |
| `prettier --check` (frontend only) | format | only when `frontend/**` changes |
| `mypy` (manual stage) | types | slow; `pre-commit run --hook-stage manual mypy` before push |

**Key design choice — narrow scope, no cosmetic fixers.** The repo is not
yet globally normalized for trailing-whitespace / EOF / CRLF. A first run of
`end-of-file-fixer` + `trailing-whitespace` reformatted **113 pre-existing
files** (measured during this work) — unacceptable churn. Those fixers are
deliberately omitted; the hook only fails on genuine problems. Global
conformance stays on CI (`make format-check`).

**`language: system`, not isolated env.** ruff/mypy reuse the project's
verified `py -3.13` interpreter and its already-installed ruff. This avoids
downloading an isolated ruff binary (unreliable on Windows, drifts from the
`pyproject.toml` pin).

**`pass_filenames: false` — two correctness bugs found in verification.** The
first config draft used `--exit-non-zero-on-fix` + `pass_filenames: true`.
Both were wrong:

1. `--exit-non-zero-on-fix` makes ruff exit non-zero *only when it applied a
   fix*. Non-auto-fixable errors (SIM115, ANN001, ANN201) returned exit 0, so
   the gate passed on real lint errors — too lenient. Dropped; plain
   `ruff check` fails on any error, matching `make lint`.
2. `pass_filenames: true` caused a silent false-positive on Windows:
   pre-commit passes every matching file as a CLI arg, and ~900 Python files
   overflow the ~32 k Windows command-line limit. ruff then received
   truncated/empty input and exited 0, reporting success while checking
   nothing. Switched to `pass_filenames: false` with the directory scope in
   the entry, so ruff walks the tree itself (honoring `pyproject.toml`).

**Side fix — pre-existing lint/format debt cleared.** The new gate runs ruff
across the full scope, which surfaced violations that `make lint` /
`make format-check` were *already failing on* on main (the remote gate was
red). Cleared in a separate commit so the gate is green on the existing tree:
`scripts/live_danmaku.py` (13 SIM/ANN errors → annotations added), and ruff
format / I001 import-sort drift in `glm_llm.py` + `llm_node.py` +
`qwen_preflight.py`. No behavior change; future violations are now caught at
commit/PR time.

### Part 2 — CI preflight job (`.github/workflows/quality.yml`)

A new `preflight` job sits between `plan` and the matrix jobs:

```text
plan → preflight (PR-only) → python/node/service matrix → docker → release-runtime → quality-gate
```

- **Trigger:** `pull_request` only. Push-to-main still runs the full tier
  (and the Zeabur deploy chain), so the preflight is skipped there.
- **Scope:** ruff check + ruff format --check + scoped mypy on the PR's
  **changed** files (`git diff --name-only` vs base sha), not the whole tree.
  Frontend changes trigger `pnpm format:check` (pnpm/node setup is conditional).
- **Hard gate:** no `continue-on-error`. preflight only checks "obviously
  broken"; real test coverage stays in the affected-tier matrix.

**Deliberately NOT added to `quality-gate`'s `needs`.** preflight is skipped
on push-to-main; adding a skipped job to `needs` would cascade-skip
`quality-gate` and break the Zeabur deploy chain. preflight stands alone as a
required PR check (set it as required in branch protection — see below).

### Part 3 — PR template + CODEOWNERS

- **`.github/PULL_REQUEST_TEMPLATE.md`** — summary, verification (the actual
  `make` targets), and an **impact checklist** mirroring the project's known
  high-risk boundaries from the audit (Socket.IO events, config schema, CLI,
  dialogue graph topology, probe filter, golden-soak).
- **`.github/CODEOWNERS`** — `* @loiter74` (single maintainer, matches the
  remote). Lets branch protection auto-request the maintainer once enabled.

### Part 4 — Docs

- **`CONTRIBUTING.md`** — new "Git Hooks (one-time setup)" section + expanded
  "Pull Request Process" referencing preflight + the branch-protection step.
- **This document.**

## Enabling branch protection (manual, one-time)

This is the **only** part that can't be set from repo files. In GitHub:

1. **Settings → Branches → Add rule** for `main`.
2. ✅ **Require a pull request before merging** (require approvals: 1 for now).
3. ✅ **Require status checks to pass** — add **`preflight`** and
   **`quality-gate`** as required checks. (They appear in the list after the
   first run reports them; until then the workflow must run once.)
4. ✅ **Require review from code owners** (uses `.github/CODEOWNERS`).
5. ✅ **Require branches to be up to date** before merging (keeps preflight
   honest against the latest main).
6. ✅ **Do not allow bypass** for the above (or restrict to admins only).

After this, no commit reaches `main` without preflight + quality-gate green.

## Verification

| Check | Result |
|---|---|
| `pre-commit run --all-files` | 6/6 hooks Passed, exit 0, **zero** working-tree churn |
| `make format-check` | green (after the `qwen_preflight.py` side-fix) |
| `quality.yml` YAML parse | `yaml.safe_load` OK; job order plan→preflight→python→…→quality-gate; quality-gate `needs` unchanged |
| `quality-gate` deploy chain | unaffected (preflight not in its `needs`) |
| `make health` | run as the final step of this pass |

## What this does NOT do (honest boundaries)

- **Does not change `tooling/quality` planning.** The impact-aware tier system
  is the existing, mature gate; preflight is a *faster outer layer*, not a
  replacement.
- **Does not enable branch protection automatically.** That is a GitHub
  Settings action — see the manual step above.
- **Does not add new test frameworks or CI runners.** pre-commit and
  preflight reuse the existing ruff / mypy / prettier.
- **Does not normalize the 113 cosmetic-fix files.** Out of scope for a
  gate-strengthening pass; tracked as a future cleanup if desired.
- **The preflight mypy step is scoped to changed files only.** Full-tree
  mypy stays in the matrix jobs; a file that mypy-checks clean in isolation
  could still fail in a full-tree pass (rare, but possible for import-cycle
  issues). The matrix job remains authoritative for type correctness.

## Files changed

| File | Part |
|---|---|
| `.pre-commit-config.yaml` (new) | 1 |
| `requirements-dev.txt` (+pre-commit) | 1 |
| `Makefile` (+`install-hooks`/`hooks`) | 1 |
| `scripts/qwen_preflight.py` (format side-fix) | 1 |
| `.github/workflows/quality.yml` (+preflight job) | 2 |
| `.github/PULL_REQUEST_TEMPLATE.md` (new) | 3 |
| `.github/CODEOWNERS` (new) | 3 |
| `CONTRIBUTING.md` (+gate sections) | 4 |
| `docs/ci-gate-plan.md` (this doc, new) | 4 |

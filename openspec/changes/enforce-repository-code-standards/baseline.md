# Repository code standards baseline

Captured from clean commit `f0b0e635` in `.worktrees/repository-code-standards` on 2026-07-16. Python commands use `C:\Users\30262\Project\Anima\.venv\Scripts\python.exe` so the runtime is the repository-required Python 3.13 rather than the shell's unrelated Python 3.11.

## Toolchain

- Python 3.13.14
- mypy 2.1.0
- Ruff 0.15.20
- pnpm 11.7.0
- Node.js 22.17.0

## Maintained source inventory

| Root | Files | Lines |
|---|---:|---:|
| `src/**/*.py` | 404 | 56,071 |
| `tooling/**/*.py` | 17 | 3,991 |
| `scripts/**/*.py` | 37 | 8,142 |
| `evaluations/**/*.py` | 5 | 1,801 |
| `tests/**/*.py` | 336 | 56,257 |
| Python total | 799 | 126,262 |
| Frontend TS/Vue/JS/CSS | 151 | 16,623 |

## Baseline results

| Gate | Result | Evidence |
|---|---|---|
| Quality catalog | PASS | 22 groups and 15 components validated |
| Python 3.13 quick tier | PASS | `backend-route-smoke` passed with cache disabled |
| Frontend typecheck | PASS | `vue-tsc --noEmit` |
| Frontend tests | PASS | 37 files and 297 tests |
| Ruff lint over all Python roots | FAIL | 332 diagnostics; 278 advertised as safe-fixable |
| Ruff format over all Python roots | FAIL | 483 files would be reformatted; 316 already formatted |
| Existing configured mypy scope | PASS with notes | No errors, two unchecked-body notes, and one unused `tests.*` override note |

The lint total is led by 182 whitespace diagnostics, 54 placeholder-free f-strings, 23 import-order diagnostics, 20 unused imports, and 18 undefined names. The passing mypy baseline is not acceptance evidence because package-wide `ignore_errors` entries currently exclude most production packages and public untyped functions are not checked.

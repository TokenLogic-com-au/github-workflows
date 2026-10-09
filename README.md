# github-workflows

Reusable CI and proposal-check workflows for TokenLogic repositories, called by short
caller files copied into each repo (see `callers/delivering-repo/`).
This repo is public: `proposal-checks.yml` fetches its
scripts through `.github/actions/scripts@main`, so they always follow
`main` — GitHub fetches that composite action itself, the same mechanism
`coverage-gate` uses, so no token is needed. The org's Actions access
setting on this repo must allow org repositories.

## Reusable workflows

| Workflow | Purpose | Key inputs | Secrets |
|---|---|---|---|
| `foundry-ci.yml` | `forge fmt`/`build`/`test`/`sizes`/gas report + optional coverage gate | `min_coverage` (0-100, default 0=off) | `ALCHEMY_API_KEY`, `RPC_MONAD` (optional, overrides Alchemy for Monad) |
| `report-comment.yml` | Posts a CI result comment on the triggering PR, `workflow_run`-based | `workflow-name`, `dry_run` | none |
| `proposal-checks.yml` | Governance-proposal gate: coverage (blocking), address-book + spelling (non-blocking warnings, findings still reported), forum-vs-diff spec check + decimals sanity (advisory). One proposal folder per PR: a PR touching zero `src/<dir>/` folders skips every check (green); a PR touching more than one fails fast. | `min_coverage`, `backend`, `dry_run` | `ALCHEMY_API_KEY`, `OPENROUTER_API_KEY`, `RPC_MONAD` (optional, overrides Alchemy for Monad) |
| `required-ci.yml` / `required-proposals.yml` | Org-ruleset entry points; wrap `foundry-ci.yml` / `proposal-checks.yml` with no per-repo inputs. `required-proposals.yml` posts its PR comments only when the target repo sets the variable `PROPOSAL_CHECKS_LIVE=true` | — | forwarded from the ruleset repo |
| `slither.yml` | Advisory-only Slither static analysis for a Foundry repo (SARIF -> code-scanning annotations); never fails the job, no coverage-style gate | `slither_version`, `target` | none |

### Re-running the proposal-checks AI advisory

The fork test, the diff report and every other proposal-checks job run on every push. The
forum-vs-payload AI call does not: it is skipped while the PR's advisory comment (marker
`<!-- github-workflows-proposal-spec -->`) was updated less than 24 hours ago. This limits
AI cost. To get a fresh advisory before the 24 hours end, for example after a failing fork
test starts to pass:

1. Delete the advisory comment on the PR.
2. Re-run the latest `required-proposals` run from its Actions page ("Re-run all jobs").
   `gh run rerun` returns 404 for this org-required workflow, because the workflow file
   lives in this repo and not in the PR's repo; use the UI.

With no advisory comment, the gate opens and the run posts a new comment. Do not edit the
comment instead: an edit sets its update time to now, so the gate stays closed for 24 more hours.

Board sync and the board AI jobs (PR review, issue scope, progress note, quality scan) run
from board-app's own workflows; this repo's `ai.py` and `prompts/` are checked out there at a
pinned ref (`GW_REF`).

`dry_run` defaults to `true` in every reusable workflow. Callers never set it
to a literal: each job reads its own variable, and only the value `"true"`
turns it live:

| Variable | Job |
| --- | --- |
| `REPORT_COMMENT_LIVE` | `callers/delivering-repo/report.yml` |
| `PROPOSAL_CHECKS_LIVE` | `required-proposals.yml` |

## Dependabot

`callers/delivering-repo/dependabot.yml` is a template for a delivering repo's
own `.github/dependabot.yml` (not `.github/workflows/` -- Dependabot config is
read natively by GitHub, no reusable-workflow/caller split). Covers `github-actions`
and `gitsubmodule` (forge libraries) on weekly schedule; npm is left out on purpose
(aave-address-book disabled it: updates spammed the repo).

## Reusable action: `coverage-gate`

Runs `forge coverage`, sums line coverage under `path_prefix` (excluding
`exclude_suffixes`), and fails if it's below `min_coverage`. Shared by
`foundry-ci.yml` (all of `src/`) and `proposal-checks.yml` (payload files
only).

## Minimal caller example

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    permissions:
      contents: read
      actions: read
    uses: "TokenLogic-com-au/github-workflows/.github/workflows/foundry-ci.yml@<github-workflows commit SHA>"
    with:
      min_coverage: 80
    secrets:
      ALCHEMY_API_KEY: ${{ secrets.ALCHEMY_API_KEY }}
      RPC_MONAD: ${{ secrets.RPC_MONAD }} # optional; overrides Alchemy for Monad (no Alchemy archive coverage)
```

More examples, including `report.yml` and `slither.yml`,
live under `callers/delivering-repo/`.
Replace every `@<github-workflows commit SHA>` placeholder with the reviewed
commit SHA before use.

## Tests

```bash
python3 -m pytest -q
```

Workflow YAML is validated with `python3 -c "import yaml; yaml.safe_load(open(f))"`
over every file. Run `dev/run-proposal-checks-locally.sh` to exercise the
`proposal-checks.yml` advisory step (spec-check + decimals scale check)
against a local proposal repo without a GitHub Actions round-trip.

# github-workflows

Reusable CI/PR/AI workflows for TokenLogic repositories, called by short
caller files copied into each repo (see `callers/delivering-repo/`).
This repo is public: `ai-comment.yml` and `proposal-checks.yml` fetch their
scripts through `.github/actions/scripts@main`, so they always follow
`main` — GitHub fetches that composite action itself, the same mechanism
`coverage-gate` uses, so no token is needed. The org's Actions access
setting on this repo must allow org repositories.

## Reusable workflows

| Workflow | Purpose | Key inputs | Secrets |
|---|---|---|---|
| `foundry-ci.yml` | `forge fmt`/`build`/`test`/`sizes`/gas report + optional coverage gate | `min_coverage` (0-100, default 0=off) | `ALCHEMY_API_KEY`, `RPC_MONAD` (optional, overrides Alchemy for Monad) |
| `pr-board.yml` | Syncs a PR/issue to the project board (`command: pr-issue-check` or `pr-sync`), through board-app's composite action | `command`, `board_app_ref`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY` |
| `ai-comment.yml` | Posts an advisory AI comment: a PR review (`kind: review`, only on an `ai-review` label add) or an issue scope check (`kind: scope`, on issue open) | `kind`, `backend` (`anthropic`/`openrouter`), `dry_run`, `board_app_ref`, `config` | `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, `BOARD_APP_PRIVATE_KEY`, `DISCORD_BOT_TOKEN` |
| `report-comment.yml` | Posts a CI result comment on the triggering PR, `workflow_run`-based | `workflow-name`, `dry_run` | none |
| `proposal-checks.yml` | Governance-proposal gate: coverage (blocking), address-book + spelling (non-blocking warnings, findings still reported), forum-vs-diff spec check + decimals sanity (advisory). One proposal folder per PR: a PR touching zero `src/<dir>/` folders skips every check (green); a PR touching more than one fails fast. | `min_coverage`, `backend`, `dry_run` | `ALCHEMY_API_KEY`, `OPENROUTER_API_KEY`, `RPC_MONAD` (optional, overrides Alchemy for Monad) |
| `quality-scan.yml` | Batch scope-checks every open board issue (skipping ones already commented), posts a scope comment per issue, hands the batch to board-app's `quality-post batch` (through its composite action), then appends a missing-required-fields digest (config `required_issue_fields` + `required_project_fields`) to the job summary | `statuses`, `max_issues`, `board_app_ref`, `backend`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`, `DISCORD_BOT_TOKEN` |
| `required-ci.yml` / `required-proposals.yml` | Org-ruleset entry points; wrap `foundry-ci.yml` / `proposal-checks.yml` with no per-repo inputs. `required-proposals.yml` posts its PR comments only when the target repo sets the variable `PROPOSAL_CHECKS_LIVE=true` | — | forwarded from the ruleset repo |
| `slither.yml` | Advisory-only Slither static analysis for a Foundry repo (SARIF -> code-scanning annotations); never fails the job, no coverage-style gate | `slither_version`, `target` | none |
| `ai-progress-note.yml` | Weekly, per In-Progress board issue: summarizes PR/commit activity and non-bot comments since its last note into one advisory issue comment (reuses `ai.py` and `render_ai_comment.py`'s footer); skips an issue with no activity since its last note | `backend`, `board_app_ref`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` |
| `no-reviewer-reminder.yml` | Scheduled: finds open, non-draft PRs org-wide with no requested reviewer and no review, ready for review past config's `no_reviewer_hours`, and pings the author on Discord through board-app's `no-reviewer-ping` subcommand (composite action); dedup is board.py's own marker comment, posted only once the ping actually went out | `board_app_ref`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `DISCORD_BOT_TOKEN` |

`pr-board.yml`, `ai-comment.yml` (kind: scope), `quality-scan.yml`,
`ai-progress-note.yml`, and `no-reviewer-reminder.yml` check out board-app by
name at `inputs.board_app_ref` into `board-tool`, then run board.py through
board-app's own composite action (`uses: ./board-tool`) -- there is no bot
repo checkout, and no `discord_bot_ref`/`bot_config` inputs anywhere in this repo any more:
board-app's `discord` config and `Notifier` seam own every Discord send.
board-app is checked out with its own narrowly-scoped app token (read-only,
`repositories: BOARD_APP_REPO`); the composite action then mints its own,
separate token (via its `app-id`/`private-key` inputs, no `repositories:`
filter) for the actual GitHub reads/writes and Discord calls it makes. The
board-app repo name comes from the org-level repository variable
`BOARD_APP_REPO`, never hard-coded here; `TRACKER_REPO` is also required by
the workflows that check board issues against it. Each workflow fails closed
with a clear error if the variable it needs is empty.

`ai-comment.yml`'s `kind: review` path only runs when the `ai-review` label
is added to a PR (not on open/synchronize); it removes the label after
posting, so re-adding it re-triggers the review. The `kind: scope` path
keeps its 24h recency gate and its own AI comment via `render_ai_comment.py`
(built from the model's strict-JSON output, never raw model text), plus a
single-issue board-app quality check (`quality-post single`) right after
posting.

`dry_run` defaults to `true` in every reusable workflow. Callers never set it
to a literal: each job reads its own variable, and only the value `"true"`
turns it live:

| Variable | Job |
| --- | --- |
| `AI_SCOPE_LIVE` | `callers/tracker-ai.yml` |
| `AI_NOTE_LIVE` | `callers/tracker-ai-progress-note.yml` |
| `REVIEW_REMINDER_LIVE` | `callers/tracker-no-reviewer-reminder.yml` |
| `BOARD_SYNC_LIVE` | `callers/delivering-repo/board.yml` |
| `AI_COMMENT_LIVE` | `callers/delivering-repo/ai.yml` |
| `REPORT_COMMENT_LIVE` | `callers/delivering-repo/report.yml` |
| `PROPOSAL_CHECKS_LIVE` | `required-proposals.yml` |

`config` (board app config path) is a required input with no default on every
reusable workflow that takes it -- each caller states which team's board
config it runs against. It is a plain filename resolved relative to
board-app's own composite action directory (`board-tool/`, e.g.
`config.json`), never prefixed with `board-tool/` -- the composite action
resolves it from `$GITHUB_ACTION_PATH`, not from the job's working directory.

`ai-progress-note.yml` and `no-reviewer-reminder.yml` also check out the board
app by name, and need `vars.TRACKER_REPO`/`vars.BOARD_APP_REPO` set the same
way as the workflows above. `ai-progress-note.yml` mints two tokens for its
own (non-board.py) GitHub reads/writes: a read-only token with no
`repositories:` filter for discovery (listing board issues, a linked PR in any
delivering repo, existing notes), and a write token scoped with `repositories:`
to the tracker repo alone, used only to post the note -- least privilege, on top
of (not instead of) the in-script check that the issue lives in the tracker repo.

Their `callers/tracker-*.yml` templates run on both a schedule and
`workflow_dispatch`; a dispatched run honours its own `dry_run` input either
way, but a *scheduled* run has no input to read, so each caller gates its
schedule's live/dry switch on its own org variable instead -- `vars.AI_NOTE_LIVE`
for `tracker-ai-progress-note.yml`, `vars.REVIEW_REMINDER_LIVE` for
`tracker-no-reviewer-reminder.yml`. Each job gets its own variable (not
`vars.DISCORD_LIVE`, board-app's own switch for its stale/review-sweep jobs)
so that switching one scheduled job live never also switches another one on;
`no-reviewer-reminder` in particular pings hourly and posts a marker comment on
every PR it reminds, so it needs its own dedicated switch more than most.
Absent or anything other than the literal `"true"` stays dry; there is no
default that goes live.

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

More examples, including `ai.yml`, `board.yml`, `report.yml`, and `slither.yml`,
live under `callers/delivering-repo/`. `callers/tracker-quality-scan.yml`,
`callers/tracker-ai-progress-note.yml`, and `callers/tracker-no-reviewer-reminder.yml`
are `workflow_dispatch`/scheduled callers meant for the tracker board repo.
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

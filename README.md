# github-workflows

Reusable CI/PR/AI workflows for TokenLogic repositories, called by short
caller files copied into each repo (see `callers/delivering-repo/`). This
repo is private: `ai-comment.yml` and `proposal-checks.yml` fetch their
scripts through `.github/actions/scripts@main`, so they always follow
`main` — GitHub fetches that composite action itself, the same mechanism
`coverage-gate` uses, so no token is needed. The org's Actions access
setting on this repo must allow org repositories.

## Reusable workflows

| Workflow | Purpose | Key inputs | Secrets |
|---|---|---|---|
| `foundry-ci.yml` | `forge fmt`/`build`/`test`/`sizes`/gas report + optional coverage gate | `min_coverage` (0-100, default 0=off) | `ALCHEMY_API_KEY`, `QUICKNODE_TOKEN`, `QUICKNODE_ENDPOINT_NAME` |
| `pr-board.yml` | Syncs a PR/issue to the project board (`command: pr-issue-check` or `pr-sync`) | `command`, `board_app_ref`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY` |
| `ai-comment.yml` | Posts an advisory AI comment: a PR review (`kind: review`, only on an `ai-review` label add) or an issue scope check (`kind: scope`, on issue open) | `kind`, `backend` (`anthropic`/`openrouter`), `dry_run`, `board_app_ref`, `discord_bot_ref`, `config`, `bot_config` | `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, `BOARD_APP_PRIVATE_KEY`, `DISCORD_BOT_TOKEN` |
| `report-comment.yml` | Posts a CI result comment on the triggering PR, `workflow_run`-based | `workflow-name`, `dry_run` | none |
| `proposal-checks.yml` | Governance-proposal gate: address-book + spelling + coverage (blocking), forum-vs-diff spec check + decimals sanity (advisory). One proposal folder per PR: a PR touching zero `src/<dir>/` folders skips every check (green); a PR touching more than one fails fast. | `min_coverage`, `backend`, `dry_run` | `ALCHEMY_API_KEY`, `QUICKNODE_TOKEN`, `QUICKNODE_ENDPOINT_NAME`, `OPENROUTER_API_KEY` |
| `review-ping.yml` | Notifies a configured bot repo when a review is requested | `discord_bot_ref`, `bot_config`, `dry_run` | `DISCORD_BOT_TOKEN` |
| `quality-scan.yml` | Batch scope-checks every open board issue (skipping ones already commented), posts a scope comment per issue, runs the bot's batch quality check, then appends a missing-required-fields digest (config `required_issue_fields` + `required_project_fields`) to the job summary | `statuses`, `max_issues`, `board_app_ref`, `discord_bot_ref`, `backend`, `config`, `bot_config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`, `DISCORD_BOT_TOKEN` |
| `required-ci.yml` / `required-proposals.yml` | Org-ruleset entry points; wrap `foundry-ci.yml` / `proposal-checks.yml` with no per-repo inputs | — | forwarded from the ruleset repo |
| `slither.yml` | Advisory-only Slither static analysis for a Foundry repo (SARIF -> code-scanning annotations); never fails the job, no coverage-style gate | `slither_version`, `target` | none |
| `ai-progress-note.yml` | Weekly, per In-Progress board issue: summarizes PR/commit activity and non-bot comments since its last note into one advisory issue comment (reuses `ai.py` and `render_ai_comment.py`'s footer); skips an issue with no activity since its last note | `backend`, `board_app_ref`, `config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` |
| `no-reviewer-reminder.yml` | Scheduled: finds open, non-draft PRs org-wide with no requested reviewer and no review, ready for review past config's `no_reviewer_hours`, and pings the author on Discord (bot roster); dedupes per PR with a marker comment posted only once the ping actually went out | `board_app_ref`, `discord_bot_ref`, `config`, `bot_config`, `dry_run` | `BOARD_APP_PRIVATE_KEY`, `DISCORD_BOT_TOKEN` |

`pr-board.yml`, `ai-comment.yml` (kind: scope), `quality-scan.yml`, and
`review-ping.yml` check out the board app and/or bot repos by name; those
names are never hard-coded here. They come from the org-level repository
variables `TRACKER_REPO`, `BOARD_APP_REPO`, and `BOT_REPO`, which must be set
on any org that uses these workflows -- each workflow fails closed with a
clear error if the variable it needs is empty.

`ai-comment.yml`'s `kind: review` path only runs when the `ai-review` label
is added to a PR (not on open/synchronize); it removes the label after
posting, so re-adding it re-triggers the review. The `kind: scope` path
keeps its 24h recency gate and its own AI comment via `render_ai_comment.py`
(built from the model's strict-JSON output, never raw model text), plus a
single-issue bot quality check right after posting.

`dry_run` defaults to `true` everywhere; flip to `false` only for an approved
live window.

`config` (board app config path) and `bot_config` (bot config path) are
required inputs with no default on every reusable workflow that takes them --
each caller states which team's board/bot config it runs against. `bot_config`
is a path relative to the bot checkout (`bot-tool/`, e.g.
`bot-tool/config.json`); `config` is a path relative to the board-app checkout
(`board-tool/`, e.g. `board-tool/config.json`). `review-ping.yml` has no
`callers/` template in this repo (it's wired up directly per delivering repo),
so its caller must set `bot_config` itself.

`ai-progress-note.yml` and `no-reviewer-reminder.yml` also check out the board
app and/or bot repos by name, and need `vars.TRACKER_REPO`/`vars.BOARD_APP_REPO`/
`vars.BOT_REPO` set the same way as the workflows above. `no-reviewer-reminder.yml`
mints its app token with no `repositories:` filter, since a candidate PR can live
in any repo the App is installed on, not just the tracker/board-app/bot repos.
`ai-progress-note.yml` mints two tokens instead of one: a read-only token with no
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
`vars.DISCORD_LIVE`, board-discord-bot's own switch for its nudge/stale jobs)
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
      QUICKNODE_TOKEN: ${{ secrets.QUICKNODE_TOKEN }}
      QUICKNODE_ENDPOINT_NAME: ${{ secrets.QUICKNODE_ENDPOINT_NAME }}
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

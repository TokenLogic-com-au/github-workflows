#!/usr/bin/env bash
# Local dev harness for the proposal-checks advisory step: lets you iterate
# on the prompt/renderer without a GitHub Actions round-trip.
#
# Usage: dev/run-proposal-checks-locally.sh <path-to-proposal-repo> <proposal-folder-under-src>
# Example: dev/run-proposal-checks-locally.sh ~/proposals 20260910_AaveV3Ethereum_AugSepFundingUpdatePart1
#
# Secrets: reads RPC_MAINNET and OPENROUTER_API_KEY BY NAME from the file at
# $ENV_FILE (default: ~/.env; never prints them). OPENROUTER_MODEL must also
# be set in the environment (no default model). If RPC_MAINNET generation
# fails (e.g. a live-mainnet-state revert unrelated to the payload), falls
# back to any already-committed diffs/*.md for that proposal, and failing
# that, runs the comparison with an empty payload side (the renderer says so
# plainly rather than fabricating data).
set -euo pipefail

WORKFLOWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="${1:?usage: $0 <proposal-repo-path> <proposal-folder>}"
PROPOSAL_FOLDER="${2:?usage: $0 <proposal-repo-path> <proposal-folder>}"
ENV_FILE="${ENV_FILE:-$HOME/.env}"
OUT_DIR="${WORKFLOWS_DIR}/dev/out"
mkdir -p "$OUT_DIR"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(RPC_MAINNET|OPENROUTER_API_KEY|OPENROUTER_MODEL)=' "$ENV_FILE")
  set +a
fi

cd "$REPO_DIR"
PROPOSAL_DIR="src/${PROPOSAL_FOLDER}"
MD_FILE=$(find "$PROPOSAL_DIR" -maxdepth 1 -name '*.md' | head -1)
if [ -z "$MD_FILE" ]; then
  echo "no .md found under $PROPOSAL_DIR" >&2
  exit 1
fi

echo "== forum raw text ==" >&2
DISCUSSIONS_URL=$(sed -n 's/^discussions:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}/\1/p' "$MD_FILE" | head -1)
TOPIC=$(echo "$DISCUSSIONS_URL" | grep -oE '[0-9]+/?$' | tr -d '/')
FORUM_FILE="$OUT_DIR/forum.txt"
if [ -n "$TOPIC" ]; then
  curl -fsSL "https://governance.aave.com/raw/$TOPIC/1" -o "$FORUM_FILE" || echo "(forum fetch failed)" > "$FORUM_FILE"
else
  echo "(no discussions topic id found)" > "$FORUM_FILE"
fi

echo "== diff report (committed, else regenerate, else empty) ==" >&2
PROPOSAL_NAME=$(basename "$PROPOSAL_DIR" | sed -E 's/^[0-9]{8}_//')
DIFF_FILE=$(find diffs -name "*${PROPOSAL_NAME}*.md" 2>/dev/null | sort | tail -1 || true)
if [ -z "$DIFF_FILE" ] && [ -n "${RPC_MAINNET:-}" ]; then
  forge test --match-path "${PROPOSAL_DIR}/*.t.sol" --isolate -vv || true
  DIFF_FILE=$(find diffs -name "*${PROPOSAL_NAME}*.md" 2>/dev/null | sort | tail -1 || true)
fi
DIFF_FILE="${DIFF_FILE:-/dev/null}"
echo "using diff report: $DIFF_FILE" >&2

echo "== spec-check AI call ==" >&2
{
  echo "<forum>"; cat "$FORUM_FILE"; echo "</forum>"
  echo "<proposal-md>"; cat "$MD_FILE"; echo "</proposal-md>"
  echo "<diff-report>"; cat "$DIFF_FILE" 2>/dev/null || true; echo "</diff-report>"
} > "$OUT_DIR/input.txt"

cd "$WORKFLOWS_DIR"
DRY_RUN=0 \
AI_API_STYLE=openai \
AI_API_URL=https://openrouter.ai/api/v1/chat/completions \
AI_API_KEY="${OPENROUTER_API_KEY:-}" \
AI_MODEL="${OPENROUTER_MODEL:?set OPENROUTER_MODEL in $ENV_FILE or the environment}" \
AI_MAX_TOKENS=16000 \
python3 ai.py spec-check "$OUT_DIR/input.txt" "$OUT_DIR/ai-out.md"

echo "== deterministic decimals-scale check ==" >&2
if [ "$DIFF_FILE" != "/dev/null" ] && [ -f "$DIFF_FILE" ]; then
  python3 scale_check.py "$DIFF_FILE" > "$OUT_DIR/scale-out.txt" || true
else
  echo "no diff report was generated for this proposal; decimals-scale check skipped" > "$OUT_DIR/scale-out.txt"
fi

echo "== rendering ==" >&2
python3 render_advisory_comment.py "$OUT_DIR/ai-out.md" "$DIFF_FILE" "$OUT_DIR/scale-out.txt" "$OUT_DIR/advisory-body.md"

echo "" >&2
echo "Rendered advisory body: $OUT_DIR/advisory-body.md" >&2
cat "$OUT_DIR/advisory-body.md"

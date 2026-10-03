#!/usr/bin/env bash
# Deploy a SHA that CI already proved, or roll back to the previous one.
#
#   scripts/deploy.sh <40-hex-sha>
#   scripts/deploy.sh --sha <40-hex-sha>
#   scripts/deploy.sh --rollback
#
# Preflight (env, hard-coded SECRET_KEY digests, key files) finishes before
# any git fetch, reset, or checkout. Never git-clean. Never rsync --delete.
# Logs are JSON lines in instance/logs/deploy.log and must not contain secrets.
set -euo pipefail

_src="${BASH_SOURCE[0]}"
ROOT="$(cd "$(dirname "$_src")/.." && pwd)"

INSTANCE_PATH="${INSTANCE_PATH:-$ROOT/instance}"
DEPLOY_DIR="$INSTANCE_PATH/deploy"
LOG_DIR="$INSTANCE_PATH/logs"
LOG_FILE="$LOG_DIR/deploy.log"
LOCK_FILE="$DEPLOY_DIR/deploy.lock"
PREV_FILE="$DEPLOY_DIR/previous_sha"
CURRENT_FILE="$DEPLOY_DIR/current_sha"
VENV_PY="${VINOR_VENV_PYTHON:-/home/vinorir/virtualenv/vinor/3.11/bin/python}"
HEALTH_URL="${VINOR_HEALTH_URL:-https://vinor.ir/healthz}"
HEALTH_TRIES="${VINOR_HEALTH_TRIES:-30}"
HEALTH_SLEEP="${VINOR_HEALTH_SLEEP:-3}"

# sha256 of hard-coded Flask SECRET_KEY strings. The literals stay in
# config.py (Config.SECRET_KEY) and the app/__init__.py fallback. Do not
# copy those strings into this file.
BAD_SECRET_SHA256=(
  9bdbe01ad3f40a96ff235e228641d37761d3de386f29125ee90fc30291a22550
  af39a485ea82ec87b6db7a83885d29bd4678642e4ad94d819356f6080d47a4dc
)

ALWAYS_REQUIRED=(
  SECRET_KEY
  SMS_API_KEY
  VAPID_PRIVATE_KEY
  VAPID_PUBLIC_KEY
  DATABASE_URL
  VINOR_WEBHOOK_SECRET
  VINOR_CONSULTANT_API_ENABLED
)

MODE="deploy"
TARGET=""
SAVED_PREV=""
EXISTED=()

log_json() {
  local event="$1"
  local detail
  detail="$(printf '%s' "${2:-}" | tr -cd 'A-Za-z0-9_.:/-')"
  mkdir -p "$LOG_DIR"
  printf '{"ts":"%s","event":"%s","detail":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$event" \
    "$detail" >>"$LOG_FILE"
}

require_nonempty() {
  local name="$1"
  local value=""
  # printenv fails when unset; do not echo the value.
  value="$(printenv "$name" 2>/dev/null || true)"
  if [[ -z "$value" ]]; then
    log_json preflight_missing "$name"
    exit 1
  fi
}

preflight() {
  local name digest bad consultant
  if ! [[ "$HEALTH_TRIES" =~ ^[0-9]+$ ]]; then
    HEALTH_TRIES=30
  fi
  if ! [[ "$HEALTH_SLEEP" =~ ^[0-9]+$ ]]; then
    HEALTH_SLEEP=3
  fi
  for name in "${ALWAYS_REQUIRED[@]}"; do
    require_nonempty "$name"
  done
  consultant="$(printenv VINOR_CONSULTANT_API_ENABLED 2>/dev/null || true)"
  if [[ "$consultant" != "1" ]]; then
    log_json preflight_rejected VINOR_CONSULTANT_API_ENABLED
    exit 1
  fi
  if ! command -v sha256sum >/dev/null 2>&1; then
    log_json preflight_missing sha256sum
    exit 1
  fi
  digest="$(printf '%s' "$(printenv SECRET_KEY)" | sha256sum | awk '{print $1}')"
  for bad in "${BAD_SECRET_SHA256[@]}"; do
    if [[ "$digest" == "$bad" ]]; then
      log_json preflight_rejected SECRET_KEY
      unset digest
      exit 1
    fi
  done
  unset digest
  if ! command -v flock >/dev/null 2>&1; then
    log_json preflight_missing flock
    exit 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    log_json preflight_missing curl
    exit 1
  fi
  if [[ ! -x "$VENV_PY" ]]; then
    log_json preflight_missing VINOR_VENV_PYTHON
    exit 1
  fi
  log_json preflight_ok ok
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --rollback)
        MODE="rollback"
        shift
        ;;
      --sha)
        if [[ $# -lt 2 ]]; then
          log_json bad_args sha
          exit 2
        fi
        TARGET="$2"
        shift 2
        ;;
      --)
        shift
        break
        ;;
      -*)
        log_json bad_args mode
        exit 2
        ;;
      *)
        if [[ -n "$TARGET" ]]; then
          log_json bad_args sha
          exit 2
        fi
        TARGET="$1"
        shift
        ;;
    esac
  done
}

normalize_sha() {
  local sha="$1"
  sha="$(printf '%s' "$sha" | tr 'A-F' 'a-f' | tr -d '[:space:]')"
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    log_json bad_sha rejected
    exit 2
  fi
  printf '%s' "$sha"
}

resolve_target() {
  local raw=""
  if [[ "$MODE" == "rollback" ]]; then
    if [[ ! -s "$PREV_FILE" ]]; then
      log_json rollback_missing previous_sha
      exit 1
    fi
    raw="$(tr -d '[:space:]' <"$PREV_FILE")"
    TARGET="$(normalize_sha "$raw")"
    return 0
  fi
  if [[ -z "$TARGET" ]]; then
    log_json bad_args sha
    exit 2
  fi
  TARGET="$(normalize_sha "$TARGET")"
}

ensure_safe_directory() {
  if git config --global --get-all safe.directory 2>/dev/null | grep -Fxq "$ROOT"; then
    return 0
  fi
  git config --global --add safe.directory "$ROOT" || true
}

fetch_origin() {
  export GIT_TERMINAL_PROMPT=0
  # stderr is discarded so a credential embedded in the remote URL is not logged.
  if ! git fetch --prune origin main >/dev/null 2>&1; then
    if [[ "$MODE" == "rollback" ]]; then
      log_json fetch_failed continuing
      return 0
    fi
    log_json fetch_failed origin_main
    exit 1
  fi
}

sha_on_main() {
  if ! git merge-base --is-ancestor "$TARGET" origin/main; then
    log_json sha_not_on_main "$TARGET"
    exit 1
  fi
}

blob_exists() {
  local sha="$1"
  local path="$2"
  git cat-file -e "${sha}:${path}" >/dev/null 2>&1
}

key_names_from_worktree() {
  "$VENV_PY" - "$ROOT" <<'PY'
import ast
import sys
from pathlib import Path

root = Path(sys.argv[1])
names = []
seen = set()
for rel in ("api_keys.py", "app/keys.py"):
    path = root / rel
    if not path.is_file():
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        print("", end="")
        raise SystemExit(2)
    for node in tree.body:
        found = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.append(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name and alias.name != "*":
                    found.append(alias.asname or alias.name)
        for name in found:
            if not name.isupper() or name.startswith("_"):
                continue
            if name not in seen:
                seen.add(name)
                names.append(name)
sys.stdout.write("\n".join(names))
PY
}

require_keys_if_target_drops_files() {
  local sha="$1"
  local missing=0
  local names="" name=""
  if ! blob_exists "$sha" "app/keys.py"; then
    missing=1
  fi
  if ! blob_exists "$sha" "api_keys.py"; then
    missing=1
  fi
  if [[ "$missing" -eq 0 ]]; then
    return 0
  fi
  log_json keys_files_absent "$sha"
  if [[ ! -f "$ROOT/api_keys.py" && ! -f "$ROOT/app/keys.py" ]]; then
    # Already removed on the server; names were required on that earlier deploy.
    log_json keys_files_already_gone worktree
    return 0
  fi
  if ! names="$(key_names_from_worktree)"; then
    log_json preflight_missing key_names
    exit 1
  fi
  if [[ -z "$names" ]]; then
    log_json preflight_missing key_names
    exit 1
  fi
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    require_nonempty "$name"
  done <<<"$names"
}

snapshot_protected() {
  local rel path
  EXISTED=()
  for rel in \
    instance \
    instance/data/push_subs.json \
    app/data/uploads \
    app/static/uploads
  do
    path="$ROOT/$rel"
    if [[ -e "$path" ]]; then
      EXISTED+=("$path")
    fi
  done
  if [[ -n "${INSTANCE_PATH:-}" && -e "$INSTANCE_PATH" ]]; then
    local already=0 seen
    for seen in "${EXISTED[@]}"; do
      if [[ "$seen" == "$INSTANCE_PATH" ]]; then
        already=1
      fi
    done
    if [[ "$already" -eq 0 ]]; then
      EXISTED+=("$INSTANCE_PATH")
    fi
  fi
}

assert_protected() {
  local path rel
  for path in "${EXISTED[@]}"; do
    if [[ ! -e "$path" ]]; then
      rel="${path#"$ROOT"/}"
      log_json protected_missing "$rel"
      return 1
    fi
  done
  return 0
}

health_ok() {
  local i code
  for ((i = 1; i <= HEALTH_TRIES; i++)); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_URL" || printf '%s' '000')"
    code="$(printf '%s' "$code" | tr -cd '0-9')"
    if [[ "$code" == "204" ]]; then
      log_json health_ok "$code"
      return 0
    fi
    log_json health_wait "${code:-000}"
    sleep "$HEALTH_SLEEP"
  done
  # Non-204 after restart covers an app that failed to boot (missing env, import error).
  log_json health_fail "${code:-000}"
  return 1
}

apply_tree() {
  # No git clean. No rsync --delete. Tracked runtime data must still be there.
  git reset --hard "$TARGET" || return 1
  assert_protected || return 1
  "$VENV_PY" -m pip install -r "$ROOT/requirements.txt" || return 1
  mkdir -p "$ROOT/tmp" || return 1
  touch "$ROOT/tmp/restart.txt" || return 1
  health_ok || return 1
  return 0
}

rollback_to() {
  local sha="$1"
  local saved_target="$TARGET"
  log_json rollback_start "$sha"
  TARGET="$sha"
  if ! apply_tree; then
    TARGET="$saved_target"
    log_json rollback_unhealthy "$sha"
    return 1
  fi
  printf '%s\n' "$sha" >"$CURRENT_FILE"
  log_json rollback_ok "$sha"
  TARGET="$saved_target"
  return 0
}

main() {
  parse_args "$@"
  # Env checks first. Nothing below this line may fetch or touch the worktree
  # until preflight, the rollback-sha read, and (after fetch) the keys check pass.
  preflight
  mkdir -p "$DEPLOY_DIR"
  resolve_target
  exec 9>"$LOCK_FILE"
  if ! flock -w 900 9; then
    log_json deploy_locked timeout
    exit 1
  fi
  cd "$ROOT"
  ensure_safe_directory
  fetch_origin
  if [[ "$MODE" != "rollback" ]]; then
    sha_on_main
  else
    if ! git cat-file -e "${TARGET}^{commit}" >/dev/null 2>&1; then
      log_json bad_sha missing
      exit 2
    fi
  fi
  require_keys_if_target_drops_files "$TARGET"
  SAVED_PREV="$(git rev-parse HEAD)"
  if [[ "$MODE" != "rollback" ]]; then
    printf '%s\n' "$SAVED_PREV" >"$PREV_FILE"
  fi
  snapshot_protected
  log_json deploy_start "$TARGET"
  if apply_tree; then
    printf '%s\n' "$TARGET" >"$CURRENT_FILE"
    if [[ "$MODE" == "rollback" ]]; then
      log_json rollback_ok "$TARGET"
    else
      log_json deploy_ok "$TARGET"
    fi
    exit 0
  fi
  log_json deploy_failed "$TARGET"
  if [[ "$MODE" == "rollback" ]]; then
    log_json rollback_failed "$TARGET"
    exit 1
  fi
  if [[ -z "$SAVED_PREV" || "$SAVED_PREV" == "$TARGET" ]]; then
    log_json rollback_skipped no_previous
    exit 1
  fi
  rollback_to "$SAVED_PREV" || exit 1
  exit 1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi

#!/usr/bin/env bash
# تصمیم مرج. کدِ Pull Request را اجرا نمی‌کند.
# با GITHUB_TOKEN مرج یا push نمی‌کند؛ آن توکن رویداد CI روی main را خاموش می‌کند.
set -euo pipefail

classify() {
  local draft="$1" mergeable="$2" state="$3" kind="$4" files="$5" checks="$6"
  local decision="stop" reason=""

  if [ "$draft" = "true" ]; then
    printf '%s\n%s\n' stop "Pull Request پیش‌نویس است."
    return 0
  fi

  local pending=0 failed="" name status conclusion
  while IFS=$'\t' read -r name status conclusion; do
    [ -z "${name:-}" ] && continue
    case "$status" in
      COMPLETED) ;;
      *) pending=1 ;;
    esac
    case "$conclusion" in
      SUCCESS|NEUTRAL|SKIPPED|"") ;;
      *) failed="${failed}${name} (${conclusion})، " ;;
    esac
  done <<< "$checks"

  if [ -n "$failed" ]; then
    printf '%s\n%s\n' stop "بررسی ناموفق: ${failed%, }."
    return 0
  fi
  if [ "$pending" -eq 1 ]; then
    printf '%s\n%s\n' wait "بررسی‌ها هنوز تمام نشده‌اند."
    return 0
  fi

  if [ "$mergeable" = "CONFLICTING" ] || [ "$state" = "DIRTY" ]; then
    printf '%s\n%s\n' stop "تداخل حل‌نشده است و حل خودکارِ بدون ابهام ممکن نیست."
    return 0
  fi
  if [ "$state" = "BLOCKED" ]; then
    printf '%s\n%s\n' stop "Branch Protection یا قوانین مخزن جلوی مرج را گرفته است. دور زده نمی‌شود."
    return 0
  fi
  if [ "$mergeable" = "UNKNOWN" ] || [ "$state" = "UNKNOWN" ] || [ "$state" = "DRAFT" ]; then
    printf '%s\n%s\n' wait "وضعیت مرج هنوز از سمت GitHub مشخص نشده است."
    return 0
  fi

  local need_unit=0 need_release=0 missing="" skipped="" line
  if [ "$kind" = "apk" ]; then
    if printf '%s\n' "$files" | grep -E -q '^(app/|build\.gradle$|settings\.gradle$|gradle\.properties$|gradle/)'; then
      need_unit=1
    fi
    if printf '%s\n' "$files" | grep -E -q '^(version\.txt$|\.github/workflows/android\.yml$)'; then
      need_release=1
    fi
  fi

  require_success() {
    local wanted="$1"
    line=$(printf '%s\n' "$checks" | awk -F '\t' -v n="$wanted" '$1==n {print $2 "\t" $3; found=1} END {if (!found) print "MISSING\tMISSING"}' | head -n 1)
    status=${line%%$'\t'*}
    conclusion=${line#*$'\t'}
    if [ "$status" = "MISSING" ]; then
      missing="${missing}${wanted}، "
    elif [ "$conclusion" != "SUCCESS" ]; then
      skipped="${skipped}${wanted} (${conclusion:-خالی})، "
    fi
  }

  if [ "$kind" = "web" ]; then
    require_success "pytest"
  fi
  if [ "$need_unit" -eq 1 ]; then
    require_success "Detect changes"
    require_success "Unit tests"
    require_success "Build Debug APK"
  fi
  if [ "$need_release" -eq 1 ]; then
    require_success "Build Release APK (signed)"
  fi

  if [ -n "$skipped" ]; then
    printf '%s\n%s\n' stop "بررسی الزامی موفق نیست: ${skipped%, }."
    return 0
  fi
  if [ -n "$missing" ]; then
    printf '%s\n%s\n' wait "بررسی الزامی هنوز ثبت نشده: ${missing%, }."
    return 0
  fi

  if [ "$state" = "BEHIND" ]; then
    printf '%s\n%s\n' update "شاخه از main عقب است. ادغام تمیز main لازم است تا بررسی‌ها دوباره اجرا شوند."
    return 0
  fi

  case "$state" in
    CLEAN|UNSTABLE|HAS_HOOKS)
      if [ "$mergeable" = "MERGEABLE" ]; then
        printf '%s\n%s\n' merge "بررسی‌های الزامی موفق‌اند و تداخلی نیست."
        return 0
      fi
      ;;
  esac

  printf '%s\n%s\n' wait "وضعیت ${state}/${mergeable} هنوز برای مرج قطعی نیست."
}

conflict_names() {
  local base="$1" head="$2" out rc
  set +e
  out=$(git merge-tree --write-tree --name-only "$base" "$head" 2>&1)
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  printf '%s\n' "$out" | awk 'NF && $0 !~ /^[0-9a-f]{40}$/ && $0 !~ /^(Auto-merging|CONFLICT)/ {print}'
  return 1
}

self_test() {
  local fails=0 out decision
  check() {
    local label="$1" want="$2"
    shift 2
    out=$(classify "$@")
    decision=$(printf '%s\n' "$out" | head -n 1)
    if [ "$decision" != "$want" ]; then
      echo "FAIL $label: got $decision want $want" >&2
      printf '%s\n' "$out" >&2
      fails=$((fails + 1))
    else
      echo "ok $label"
    fi
  }
  local ok=$'pytest\tCOMPLETED\tSUCCESS'
  local unit=$'Detect changes\tCOMPLETED\tSUCCESS\nUnit tests\tCOMPLETED\tSUCCESS\nBuild Debug APK\tCOMPLETED\tSUCCESS'
  local pending=$'pytest\tIN_PROGRESS\t'
  local bad=$'pytest\tCOMPLETED\tFAILURE'
  local skipped_unit=$'Detect changes\tCOMPLETED\tSUCCESS\nUnit tests\tCOMPLETED\tSKIPPED\nBuild Debug APK\tCOMPLETED\tSUCCESS'

  check draft stop true MERGEABLE CLEAN web "" "$ok"
  check conflict stop false CONFLICTING DIRTY web "" "$ok"
  check pending wait false MERGEABLE UNSTABLE web "" "$pending"
  check failed stop false MERGEABLE UNSTABLE web "" "$bad"
  check web-merge merge false MERGEABLE CLEAN web "app/routes.py" "$ok"
  check blocked stop false MERGEABLE BLOCKED web "app/routes.py" "$ok"
  check behind update false MERGEABLE BEHIND web "app/routes.py" "$ok"
  check apk-code-missing wait false MERGEABLE CLEAN apk "app/src/Main.kt" ""
  check apk-code-merge merge false MERGEABLE CLEAN apk "app/src/Main.kt" "$unit"
  check apk-rules merge false MERGEABLE CLEAN apk ".cursor/rules/auto-pr-merge.mdc" ""
  check apk-skip-unit stop false MERGEABLE CLEAN apk "app/src/Main.kt" "$skipped_unit"
  local with_release="${unit}"$'\nBuild Release APK (signed)\tCOMPLETED\tSUCCESS'
  check apk-release merge false MERGEABLE CLEAN apk $'version.txt\napp/src/Main.kt' "$with_release"
  check apk-release-missing wait false MERGEABLE CLEAN apk "version.txt" "$unit"
  check unknown wait false UNKNOWN UNKNOWN web "" ""

  if [ "$fails" -ne 0 ]; then
    echo "$fails classifier test(s) failed" >&2
    return 1
  fi
  echo "classifier self-test passed"
}

if [ "${1:-}" = "--self-test" ]; then
  self_test
  exit 0
fi

# بقیهٔ فایل فقط وقتی اجرا می‌شود که ورک‌فلو آن را صدا بزند.
: "${GITHUB_REPOSITORY:?}"
: "${REPO_KIND:?}"

MARKER="<!-- vinor-auto-pr-merge -->"

upsert_comment() {
  local body="$1" id
  id=$(gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${PR}/comments" \
    --jq '.[] | select(.body | contains("<!-- vinor-auto-pr-merge -->")) | .id' | head -n 1 || true)
  if [ -n "${id:-}" ]; then
    gh api -X PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${id}" -f body="$body" >/dev/null
  else
    gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${PR}/comments" -f body="$body" >/dev/null
  fi
}

redact() {
  sed -E 's#(ghp_|gho_|github_pat_|ghs_)[A-Za-z0-9_]+#[redacted]#g'
}

report() {
  local title="$1" detail="$2"
  local body
  body=$(printf '%s\n**%s**\n\n%s\n' "$MARKER" "$title" "$detail")
  upsert_comment "$body"
  echo "$title" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  echo "$detail" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
}

load_pr() {
  PR_JSON=$(gh pr view "$PR" --repo "$GITHUB_REPOSITORY" \
    --json isDraft,mergeable,mergeStateStatus,baseRefName,headRefName,headRefOid,headRepository)
  DRAFT=$(printf '%s' "$PR_JSON" | jq -r '.isDraft')
  MERGEABLE=$(printf '%s' "$PR_JSON" | jq -r '.mergeable // "UNKNOWN"')
  STATE=$(printf '%s' "$PR_JSON" | jq -r '.mergeStateStatus // "UNKNOWN"')
  BASE_REF=$(printf '%s' "$PR_JSON" | jq -r '.baseRefName')
  HEAD_REF=$(printf '%s' "$PR_JSON" | jq -r '.headRefName')
  HEAD_SHA=$(printf '%s' "$PR_JSON" | jq -r '.headRefOid')
  HEAD_REPO=$(printf '%s' "$PR_JSON" | jq -r '.headRepository.nameWithOwner // ""')
  FILES=$(gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls/${PR}/files" --jq '.[].filename')
  CHECKS=$(gh pr view "$PR" --repo "$GITHUB_REPOSITORY" --json statusCheckRollup \
    --jq '.statusCheckRollup[]? | "\(.name)\t\(.status)\t\(.conclusion // "")"')
}

decide_once() {
  load_pr
  if [ "$BASE_REF" != "main" ]; then
    DECISION=stop
    REASON="پایهٔ Pull Request شاخهٔ main نیست."
    return 0
  fi
  if [ -z "$HEAD_REPO" ] || [ "$HEAD_REPO" != "$GITHUB_REPOSITORY" ]; then
    DECISION=stop
    REASON="شاخهٔ مبدأ داخل همین مخزن نیست. از فورک مرج یا push نمی‌شود."
    return 0
  fi
  local out
  out=$(classify "$DRAFT" "$MERGEABLE" "$STATE" "$REPO_KIND" "$FILES" "$CHECKS")
  DECISION=$(printf '%s\n' "$out" | head -n 1)
  REASON=$(printf '%s\n' "$out" | tail -n +2)
  if [ "$DECISION" = "stop" ] && printf '%s' "$REASON" | grep -q 'تداخل'; then
    git fetch --no-tags origin "$BASE_REF" "$HEAD_SHA"
    local names=""
    if ! names=$(conflict_names "origin/${BASE_REF}" "$HEAD_SHA"); then
      if [ -n "$names" ]; then
        REASON="${REASON}"$'\n'"فایل‌ها:"$'\n'"${names}"
      fi
    fi
  fi
}

run_pr() {
  local deadline=$((SECONDS + 1200))
  while true; do
    decide_once
    [ "$DECISION" != "wait" ] && break
    if [ "$SECONDS" -ge "$deadline" ]; then
      DECISION=stop
      REASON="مهلت ۲۰ دقیقه‌ای تمام شد و بررسی‌ها هنوز قطعی نشده‌اند. ${REASON}"
      break
    fi
    sleep 30
  done

  case "$DECISION" in
    stop)
      report "مرج انجام نشد" "$REASON"
      ;;
    update)
      if [ -z "${VINOR_AUTOMERGE_TOKEN:-}" ]; then
        report "مرج انجام نشد" "${REASON} سکرت VINOR_AUTOMERGE_TOKEN تنظیم نشده است، پس Actions شاخه را به‌روز نمی‌کند و با GITHUB_TOKEN هم push نمی‌کند."
      else
        update_branch
      fi
      ;;
    merge)
      if [ -z "${VINOR_AUTOMERGE_TOKEN:-}" ]; then
        report "مرج از Actions انجام نشد" "${REASON} سکرت VINOR_AUTOMERGE_TOKEN موجود نیست. با GITHUB_TOKEN مرج نمی‌شود چون CI و دیپلوی main را خاموش می‌کند. عامل Cursor، اگر این نشست باز است، بعد از همین بررسی‌ها با gh pr merge --merge مرج می‌کند."
      else
        do_merge
      fi
      ;;
    *)
      report "مرج انجام نشد" "تصمیم نامعتبر: ${DECISION}. ${REASON}"
      exit 1
      ;;
  esac
}

update_branch() {
  git fetch --no-tags origin "$BASE_REF" "$HEAD_SHA"
  if ! conflict_names "origin/${BASE_REF}" "$HEAD_SHA" >/tmp/conflict-names.txt; then
    report "مرج انجام نشد" "ادغام main بدون تداخل ممکن نیست."$'\n'"$(cat /tmp/conflict-names.txt)"
    return 0
  fi
  git checkout --detach "$HEAD_SHA"
  git -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    -c user.name='github-actions[bot]' \
    merge --no-edit "origin/${BASE_REF}"
  local askpass
  askpass=$(mktemp)
  cat > "$askpass" <<'EOF'
#!/bin/sh
exec printf '%s\n' "$VINOR_AUTOMERGE_TOKEN"
EOF
  chmod 700 "$askpass"
  local err rc
  set +e
  err=$(GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 \
    git push "https://x-access-token@github.com/${HEAD_REPO}.git" \
    "HEAD:refs/heads/${HEAD_REF}" 2>&1)
  rc=$?
  set -e
  rm -f "$askpass"
  if [ "$rc" -ne 0 ]; then
    report "به‌روزرسانی شاخه ناموفق بود" "$(printf '%s\n' "$err" | redact)"
    exit 1
  fi
  report "شاخه با main به‌روز شد" "ادغام بدون تداخل push شد. مرج بعد از اجرای دوبارهٔ بررسی‌ها انجام می‌شود."
}

do_merge() {
  local err rc
  set +e
  err=$(GH_TOKEN="$VINOR_AUTOMERGE_TOKEN" gh pr merge "$PR" --repo "$GITHUB_REPOSITORY" --merge 2>&1)
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    report "دستور مرج رد شد" "$(printf '%s\n' "$err" | redact)"
    exit 1
  fi
  local state sha
  state=$(GH_TOKEN="$VINOR_AUTOMERGE_TOKEN" gh pr view "$PR" --repo "$GITHUB_REPOSITORY" --json state --jq .state)
  sha=$(GH_TOKEN="$VINOR_AUTOMERGE_TOKEN" gh api "repos/${GITHUB_REPOSITORY}/commits/${BASE_REF}" --jq .sha)
  if [ "$state" != "MERGED" ]; then
    report "مرج تأیید نشد" "وضعیت Pull Request برابر ${state} است. HEAD شاخهٔ ${BASE_REF}: ${sha}"
    exit 1
  fi
  report "در ${BASE_REF} مرج شد" "HEAD فعلی ${BASE_REF}: \`${sha}\`"
}

if [ "${EVENT_NAME:-}" = "workflow_run" ]; then
  : "${WORKFLOW_HEAD_SHA:?}"
  mapfile -t PRS < <(gh api "repos/${GITHUB_REPOSITORY}/commits/${WORKFLOW_HEAD_SHA}/pulls" --jq '.[] | select(.state=="open") | .number')
  if [ "${#PRS[@]}" -eq 0 ]; then
    echo "no open pull request for ${WORKFLOW_HEAD_SHA}"
    exit 0
  fi
  for PR in "${PRS[@]}"; do
    run_pr
  done
else
  : "${PR_NUMBER:?}"
  PR="$PR_NUMBER"
  run_pr
fi

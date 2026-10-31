#!/usr/bin/env bash
# story: e37s08
# test-target-contracts.sh — anti-vacuity guard for run_contract.
#
# Every contract named in scripts/targets.yaml must have a real assertion behind
# it. run_contract used to end in `*) echo "SKIP ..."; return 0`, so seven
# declared contracts (cline/codebuddy/codex/kilocode/qwen/trae/windsurf
# _hooks_manifest) silently passed forever. This test fails if that default ever
# returns to being permissive, or if targets.yaml declares a contract nothing
# implements.
#
# Usage: bash scripts/test-target-contracts.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/skill-common.sh"
resolve_repo_root
cd "$REPO_ROOT"

TA_PASS=0
TA_FAIL=0
TA_TMPDIR=""

source "$REPO_ROOT/scripts/lib/test-assertions.sh"
trap ta_cleanup EXIT

echo "=== test-target-contracts.sh ==="

# shellcheck source=lib/target-contracts.sh
source "$REPO_ROOT/scripts/lib/target-contracts.sh"

# 1. An unknown contract MUST fail. This is the anti-vacuity assertion.
set +e
out=$(run_contract "faketarget" "definitely_not_a_real_contract" 2>&1)
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  ta_pass "unknown contract fails (exit $rc)"
else
  ta_fail "unknown contract returned 0 — run_contract is fail-open again: $out"
fi

# 2. Every contract declared in targets.yaml must resolve to an assertion.
#    Probing with a nonexistent target id means a real assertion returns 1 with
#    a FAIL line, while a missing implementation hits the default branch and
#    reports "unknown contract".
declared=$(grep -E "^      - [a-z0-9_]+$" scripts/targets.yaml | sed 's/^      - //' | sort -u)
[[ -n "$declared" ]] || ta_fail "no contracts parsed from targets.yaml"

for c in $declared; do
  set +e
  out=$(run_contract "__probe__" "$c" 2>&1)
  set -e
  if grep -q "unknown contract" <<<"$out"; then
    ta_fail "$c declared in targets.yaml but no assertion implements it"
  else
    ta_pass "$c has an implementation"
  fi
done

# 3. Every *_hooks_manifest target must actually ship a parseable manifest.
for c in $declared; do
  case "$c" in
    gemini_hooks_manifest) continue ;;  # adapter-level validator, not a file check
    *_hooks_manifest)
      t="${c%_hooks_manifest}"
      if [[ -f "scripts/hooks/${t}/hooks-manifest.json" ]]; then
        ta_pass "$t ships hooks-manifest.json"
      else
        ta_fail "$t declares $c but scripts/hooks/${t}/hooks-manifest.json is missing"
      fi
      ;;
  esac
done

# Exercise the OMP assertion's observable integrity boundary, not only routing.
TA_TMPDIR=$(mktemp -d)
TA_TMPDIR="$(cd "$TA_TMPDIR" && pwd -P)"
omp_fixture="$TA_TMPDIR/omp-source"
omp_source="$omp_fixture/skills/contract-example/SKILL.md"
mkdir -p "$(dirname "$omp_source")"
printf '%s\n' '---' 'name: contract-example' 'description: Inspect owned output.' \
  '---' '# Contract example' 'Inspect the assigned change.' > "$omp_source"
if (cd "$omp_fixture" && run_contract omp omp_native_resources >/dev/null 2>&1); then
  ta_fail "OMP contract accepted missing native resources"
else
  ta_pass "OMP contract rejects missing native resources"
fi
if jq -nc --arg root "$omp_fixture" --arg source "$omp_source" \
  '{repo_root:$root,mode:"all",skills:[{name:"contract-example",description:"Inspect owned output.",source_path:$source}]}' \
  | OMP_SKILLS="$omp_fixture/.omp/skills" "${PYTHON:-python3}" \
    "$REPO_ROOT/scripts/lib/omp-resources.py" >/dev/null; then
  if (cd "$omp_fixture" && run_contract omp omp_native_resources >/dev/null); then
    ta_pass "OMP contract accepts actual generated owned resources"
  else
    ta_fail "OMP contract rejected actual generated resources"
  fi
  printf '%s\n' 'User edit must survive.' >> "$omp_fixture/.omp/skills/contract-example/SKILL.md"
  if (cd "$omp_fixture" && run_contract omp omp_native_resources >/dev/null 2>&1); then
    ta_fail "OMP contract accepted edited owned output"
  else
    ta_pass "OMP contract rejects edited owned output"
  fi
else
  ta_fail "OMP contract fixture generation failed"
fi

echo "test-target-contracts: $TA_PASS passed, $TA_FAIL failed"
[[ "$TA_FAIL" -eq 0 ]] || exit 1

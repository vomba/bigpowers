#!/usr/bin/env bash
# story: e37s10
# story: e82s03
omp_render_json() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || return 1
  OMP_SKILLS="${OMP_SKILLS:-$root/.omp/skills}" \
    "${PYTHON:-python3}" "$root/scripts/lib/omp-resources.py"
}

render_skill() {
  source "$(dirname "${BASH_SOURCE[0]}")/../lib/adapter-guard.sh"
  bp_assert_safe_skill_name "${IR_NAME-}" omp >/dev/null || return 1
  [[ -n "${SKILL_MD_PATH:-}" ]] || {
    echo "omp: SKILL_MD_PATH is required; supply an actual source SKILL.md" >&2
    return 1
  }
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || return 1
  jq -nc --arg source "$SKILL_MD_PATH" --arg name "$IR_NAME" \
    --arg description "${IR_DESCRIPTION:-}" --arg root "${OMP_SOURCE_ROOT:-$root}" \
    '{skills:[{name:$name,description:$description,source_path:$source}],mode:"single",repo_root:$root}' \
    | omp_render_json
}

# Sourcing with /dev/null is inert; explicit dispatch supplies one whole batch.
if [[ ! -t 0 ]]; then
  _omp_input="$(cat)"
  if [[ -n "$_omp_input" ]]; then
    printf '%s' "$_omp_input" | omp_render_json
  fi
fi

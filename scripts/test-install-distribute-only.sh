#!/usr/bin/env bash
# story: BUG-2026-07-24-installer-runs-dev-maintenance-pipeline e82s03
# Exercise the installer distribution CLI from an actual extracted npm package.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/scripts/lib/python-env.sh"
export TEST_DISTRIBUTE_PYTHON
TEST_DISTRIBUTE_PYTHON="$("$PYTHON" -c 'import sys; print(sys.executable)')"
export TEST_DISTRIBUTE_YAML
TEST_DISTRIBUTE_YAML="$("$PYTHON" -c 'import pathlib, yaml; print(pathlib.Path(yaml.__file__).parent.parent)')"

node - "$REPO_ROOT" <<'JS'
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const root = process.argv[2];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bigpowers-packed-distribution-'));
const run = (exe, args, options = {}) => execFileSync(exe, args, {
  encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, ...options,
});
const executable = (name) => {
  for (const dir of process.env.PATH.split(path.delimiter)) {
    const file = path.resolve(dir, name);
    try { fs.accessSync(file, fs.constants.X_OK); return file; } catch {}
  }
  throw new Error(`Missing distribution test prerequisite: ${name}`);
};
const snapshot = (base, rel) => {
  const file = path.join(base, rel);
  return fs.existsSync(file) ? fs.readFileSync(file).toString('base64') : null;
};
try {
  const [packed] = JSON.parse(run(executable('npm'), [
    'pack', '--json', '--pack-destination', tmp,
  ], { cwd: root }));
  run(executable('tar'), ['-xzf', path.join(tmp, packed.filename), '-C', tmp]);
  const pkg = path.join(tmp, 'package');
  for (const rel of [
    '.pi/package.json', '.pi/skills/audit-code/SKILL.md', '.pi/prompts/audit-code.md',
    'extensions/omp-hooks.ts', '.mcp.json', 'bigpowers-mcp/build/index.js',
    'docs/templates/ci/github/test-build-release-node.yml',
    'docs/templates/ci/github/test-build-release-rust.yml',
    'docs/templates/ci/github/test-build-release-python.yml',
    'docs/templates/ci/github/test-build-release-go.yml', 'docs/templates/AGENTS.md',
    '.omp/skills/audit-code/SKILL.md', '.omp/commands/bigpowers-audit-code.md',
    'skills/align-grid/scripts/grid_tokens.py',
  ]) assert.ok(fs.existsSync(path.join(pkg, rel)), `Actual npm package lacks ${rel}`);
  for (const rel of ['.git', 'specs', 'node_modules']) {
    assert.ok(!fs.existsSync(path.join(pkg, rel)), `Package unexpectedly includes ${rel}`);
  }
  // Templates must ship, but rendering must not depend on dev documentation.
  fs.rmSync(path.join(pkg, 'docs'), { recursive: true, force: true });
  const unchanged = [
    'skills-lock.json', 'SKILL-INDEX.md', 'README.md', '.mcp.json', 'package.json',
    'extensions/omp-hooks.ts',
  ];
  const before = unchanged.map((rel) => snapshot(pkg, rel));
  const generated = [
    '.cursor/rules/audit-code.mdc',
    '.gemini/extensions/bigpowers/skills/audit-code/SKILL.md',
    '.pi/skills/audit-code/SKILL.md', '.pi/prompts/audit-code.md',
    '.omp/skills/audit-code/SKILL.md', '.omp/commands/bigpowers-audit-code.md',
  ];
  // Remove disposable extracted artifacts so packaged bytes cannot mask no-op rendering.
  for (const rel of generated) fs.rmSync(path.join(pkg, rel));
  const tools = path.join(tmp, 'tools');
  fs.mkdirSync(tools);
  for (const name of [
    'bash', 'env', 'dirname', 'basename', 'cat', 'sed', 'awk', 'grep', 'sort',
    'find', 'wc', 'tr', 'mkdir', 'rm', 'cp', 'mv', 'mktemp', 'cut', 'head', 'tail',
  ]) fs.symlinkSync(executable(name), path.join(tools, name));
  // Keep the selected interpreter's virtualenv identity instead of symlinking its binary.
  const python = process.env.TEST_DISTRIBUTE_PYTHON;
  fs.writeFileSync(path.join(tools, 'python3'),
    '#!' + executable('bash') + '\nexec ' + "'" + python.replace(/'/g, "'\\''") + "'" + ' "$@"\n',
    { mode: 0o755 });
  const home = path.join(tmp, 'home');
  fs.mkdirSync(home);
  const env = {
    PATH: tools, HOME: home, TMPDIR: tmp, LANG: 'C.UTF-8',
    PYTHONPATH: process.env.TEST_DISTRIBUTE_YAML, PYTHONNOUSERSITE: '1',
  };
  // No inherited SDK variables, Git/Bun executable, user configuration, or node_modules.
  assert.ok(!fs.existsSync(path.join(tools, 'git')));
  assert.ok(!fs.existsSync(path.join(tools, 'bun')));
  assert.ok(!Object.keys(env).some((key) => key.startsWith('BIGPOWERS_OMP_TEST_')));
  const output = run(path.join(tools, 'bash'), [
    path.join(pkg, 'scripts/sync-skills.sh'), '--distribute-only',
  ], { cwd: tmp, env });
  assert.ok(output.includes('--distribute-only: dev-maintenance regen skipped'));
  for (const rel of generated) {
    assert.ok(fs.statSync(path.join(pkg, rel)).size > 0, `Distribution did not regenerate ${rel}`);
  }
  unchanged.forEach((rel, i) => assert.strictEqual(snapshot(pkg, rel), before[i], `${rel} changed`));
  for (const rel of ['.git', 'specs', 'docs', 'node_modules']) {
    assert.ok(!fs.existsSync(path.join(pkg, rel)), `Distribution created ${rel}`);
  }
  run(path.join(tools, 'python3'), [path.join(pkg, 'scripts/validate-omp-resources.py'), pkg], { env });
  // The shipped folded security-review description must also validate without PyYAML.
  fs.writeFileSync(path.join(tools, 'python3'),
    '#!' + executable('bash') + '\nexec ' + "'" + python.replace(/'/g, "'\\''") + "'" + ' -S "$@"\n',
    { mode: 0o755 });
  const bareEnv = { ...env };
  delete bareEnv.PYTHONPATH;
  run(path.join(tools, 'bash'), [path.join(pkg, 'scripts/sync-skills.sh'), '--distribute-only'],
    { cwd: tmp, env: bareEnv });
  run(path.join(tools, 'python3'), [path.join(pkg, 'scripts/validate-omp-resources.py'), pkg],
    { env: bareEnv });
  const ompSkill = fs.readFileSync(path.join(pkg, '.omp/skills/audit-code/SKILL.md'), 'utf8');
  assert.ok(ompSkill.includes('[Canonical skill resources](../../../skills/audit-code/)'));
  assert.ok(fs.existsSync(path.join(pkg, '.omp/skills/audit-code', '../../../skills/audit-code/SKILL.md')));
  console.log('PASS: packed/extracted distribution and validation work without specs/docs/Git/Bun/SDK, with and without PyYAML');
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
JS

import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const root = process.env.BIGPOWERS_OMP_FIXTURE_ROOT!;
export const workspace = path.join(root, "workspace with spaces $ARGUMENTS $1");
export const agentDir = process.env.PI_CODING_AGENT_DIR!;
export const sourceRoot = process.env.BIGPOWERS_OMP_SOURCE_ROOT!;
export function resolveRuntime(specifier: string): string {
  const approved = process.env.BIGPOWERS_OMP_TEST_ROOT!;
  const resolved = realpathSync(Bun.resolveSync(specifier, path.join(approved, "package.json")));
  assert(resolved.startsWith(realpathSync(path.join(approved, "node_modules")) + path.sep),
    `Package export escaped approved runtime: ${specifier}`);
  return resolved;
}
// Static imports cannot resolve the explicitly provisioned, external test root.
export async function sdkImport<T>(subpath = ""): Promise<T> {
  return import(pathToFileURL(resolveRuntime(`@oh-my-pi/pi-coding-agent${subpath}`)).href);
}
export function put(file: string, text: string): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text);
}
export function tree(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? tree(file) : [file];
  }).sort();
}
export function generateFixture(): void {
  cpSync(path.join(sourceRoot, "scripts"), path.join(workspace, "scripts"), { recursive: true });
  put(path.join(workspace, "docs", "reference.txt"), "outward-source-dependency-verified\n");
  put(path.join(workspace, "skills", "native-example", "SKILL.md"),
    '---\nname: native-example\ndescription: "Read --- separators in native fixture resources."\nmodel: opus\n---\n' +
    '# Native fixture\nRead [asset](assets/detail.txt) and [source reference](../../docs/reference.txt).\n' +
    'Literal examples remain literal: `$1`, `$ARGUMENTS`, `${HOME}`.\n');
  put(path.join(workspace, "skills", "native-example", "assets", "detail.txt"), "native-asset-verified\n");
  put(path.join(workspace, "skills", "native-example", "REFERENCE.md"), "Compiled sibling Markdown remains available.\n");
  for (const control of ["hide", "disable-model-invocation"]) {
    for (const state of ["true", "false", "absent"]) {
      const name = `native-${control}-${state}`;
      put(path.join(workspace, "skills", name, "SKILL.md"),
        `---\nname: ${name}\ndescription: >-\n  Folded --- description\n  for ${name}.\n` +
        (state === "absent" ? "" : `${control}: ${state}\n`) +
        `---\nExplicit access: ${control === "hide" ? "visibility" : "invocation"}/${state}.\n`);
    }
  }
  cpSync(path.join(sourceRoot, "skills", "align-grid"), path.join(workspace, "skills", "align-grid"), { recursive: true });
  cpSync(path.join(sourceRoot, "extensions"), path.join(workspace, "extensions"), { recursive: true });
  // Exercise the existing workflow itself, not a rewritten two-review imitation.
  cpSync(path.join(sourceRoot, "skills", "request-review"), path.join(workspace, "skills", "request-review"), { recursive: true });
  const command = Bun.spawnSync(["/bin/bash", "scripts/sync-skills.sh", "--distribute-only"],
    { cwd: workspace, env: process.env, stdout: "pipe", stderr: "pipe" });
  assert.equal(command.exitCode, 0, `Ordinary distribution generation failed:\n${command.stdout}\n${command.stderr}`);
  assertGeneratedSurface(workspace);
  for (const forbidden of ["config.yml", "agents", "extensions", "tools", "providers", "mcp.json", "hooks"]) {
    assert(!existsSync(path.join(workspace, ".omp", forbidden)), `Renderer introduced ${forbidden}`);
  }
}
function assertGeneratedSurface(checkout: string): void {
  const omp = path.join(checkout, ".omp");
  assert.deepEqual(readdirSync(omp).sort(), ["commands", "skills"], "Native generation adds only skills and commands");
  for (const name of readdirSync(path.join(omp, "skills"))) {
    assert.deepEqual(readdirSync(path.join(omp, "skills", name)), ["SKILL.md"],
      `No copied assets or private inventory may mask canonical resource resolution: ${name}`);
  }
}
export function copyDeliveryCandidate(): void {
  const sourceOmp = path.join(sourceRoot, ".omp");
  assert(existsSync(sourceOmp), "Generate source-root delivery-candidate .omp with ordinary sync before the native suite");
  assertGeneratedSurface(sourceRoot);
  // Export tracked working-tree paths, including the staged native artifacts.
  // Untracked credentials, profiles, dependencies and old generated files are not delivery inputs.
  const listed = Bun.spawnSync(["git", "ls-files", "-z"], {
    cwd: sourceRoot, env: process.env, stdout: "pipe", stderr: "pipe",
  });
  assert.equal(listed.exitCode, 0, `Delivery-candidate source must be a Git checkout: ${listed.stderr}`);
  for (const relative of listed.stdout.toString().split("\0").filter(Boolean)) {
    const source = path.join(sourceRoot, relative);
    if (!existsSync(source)) continue; // Deletions in the correction must stay deleted.
    const destination = path.join(workspace, relative);
    mkdirSync(path.dirname(destination), { recursive: true });
    cpSync(source, destination, { recursive: true });
  }
  const sourceFiles = tree(sourceOmp);
  assert(sourceFiles.length > 0, "Delivery candidate must not be an empty generated tree");
  for (const file of sourceFiles) {
    const relative = path.relative(sourceOmp, file);
    assert.deepEqual(readFileSync(path.join(workspace, ".omp", relative)), readFileSync(file),
      `Relocation must use source-root delivery-candidate bytes without regeneration: ${relative}`);
  }
  const names = readdirSync(path.join(workspace, "skills")).filter(name =>
    existsSync(path.join(workspace, "skills", name, "SKILL.md"))).sort();
  assert.deepEqual(readdirSync(path.join(workspace, ".omp", "skills")).sort(), names,
    "Every canonical skill must be present in the delivery candidate");
  assert.deepEqual(readdirSync(path.join(workspace, ".omp", "commands")).sort(),
    names.map(name => `bigpowers-${name}.md`).sort(), "Every delivery-candidate convenience command must be present");
  console.log("Delivery candidate: full source tree + exact source-root .omp bytes relocated without regeneration; no copied support assets.");
}
export function resourceSnapshot(): Map<string, Buffer> {
  return new Map(tree(path.join(workspace, ".omp")).map(file => [file, readFileSync(file)]));
}
export function assertResourcesUnchanged(snapshot: Map<string, Buffer>): void {
  assert.deepEqual(tree(path.join(workspace, ".omp")), [...snapshot.keys()]);
  for (const [file, bytes] of snapshot) assert.deepEqual(readFileSync(file), bytes, `Resource changed: ${file}`);
}

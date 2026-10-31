import assert from "node:assert/strict";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const root = process.env.BIGPOWERS_OMP_FIXTURE_ROOT!;
export const workspace = path.join(root, "workspace-$ARGUMENTS-$1");
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
  // Exercise the existing workflow itself, not a rewritten two-review imitation.
  cpSync(path.join(sourceRoot, "skills", "request-review"), path.join(workspace, "skills", "request-review"), { recursive: true });
  const command = Bun.spawnSync(["/bin/bash", "scripts/sync-skills.sh", "--target", "omp"],
    { cwd: workspace, env: process.env, stdout: "pipe", stderr: "pipe" });
  assert.equal(command.exitCode, 0, `Public OMP generation failed:\n${command.stdout}\n${command.stderr}`);
  const allowed: Record<string, true> = { skills: true, commands: true, ".bigpowers-resources.json": true };
  for (const name of readdirSync(path.join(workspace, ".omp"))) assert(Object.hasOwn(allowed, name), `Renderer introduced ${name}`);
  for (const forbidden of ["config.yml", "agents", "extensions", "tools", "providers", "mcp.json", "hooks"]) {
    assert(!existsSync(path.join(workspace, ".omp", forbidden)), `Renderer introduced ${forbidden}`);
  }
}
export function resourceSnapshot(): Map<string, Buffer> {
  return new Map(tree(path.join(workspace, ".omp")).map(file => [file, readFileSync(file)]));
}
export function assertResourcesUnchanged(snapshot: Map<string, Buffer>): void {
  assert.deepEqual(tree(path.join(workspace, ".omp")), [...snapshot.keys()]);
  for (const [file, bytes] of snapshot) assert.deepEqual(readFileSync(file), bytes, `Resource changed: ${file}`);
}

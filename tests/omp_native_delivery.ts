// story: e82s03
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, symlinkSync } from "node:fs";
import path from "node:path";
import { assertResourcesUnchanged, resourceSnapshot, sdkImport, sourceRoot, workspace } from "./omp_native_fixture";
import { createProviderFixture } from "./omp_native_provider";
import type { ProviderFixture } from "./omp_native_provider";
import type { NativeSdk, NativeSession, NativeSlash, Skill, ToolResult } from "./omp_native_types";

function text(result: ToolResult): string {
  assert(!result.isError, `Actual host read failed: ${JSON.stringify(result)}`);
  return result.content.map(item => item.text ?? "").join("\n");
}
export async function readGridResources(session: NativeSession, skills: Skill[]): Promise<void> {
  const file = path.join(workspace, ".omp", "skills", "align-grid", "SKILL.md");
  const grid = skills.find(skill => skill.filePath === file);
  assert(grid, "Actual SDK must discover delivery-candidate align-grid");
  const reader = session.getToolByName("read");
  assert(reader);
  assert(/grid/i.test(text(await reader.execute("grid-skill", { path: `skill://${grid.name}` }))));
  const link = readFileSync(file, "utf8").match(/\[Canonical skill resources\]\(([^)]+)\)/)?.[1];
  assert(link && !path.isAbsolute(link) && !link.includes("://"), "Canonical directory link must be portable and relative");
  const canonical = path.resolve(path.dirname(file), link);
  assert.equal(canonical, path.join(workspace, "skills", "align-grid"));
  assert(text(await reader.execute("grid-canonical-directory", { path: canonical })).includes("scripts"));
  const scripts = path.join(canonical, "scripts");
  assert(text(await reader.execute("grid-scripts-directory", { path: scripts })).includes("grid_tokens.py"));
  const script = path.join(scripts, "grid_tokens.py");
  assert(text(await reader.execute("grid-canonical-script", { path: script })).includes("import argparse"),
    "Actual read tool must load canonical script outside generated output, not skill:// traversal");
  const python = process.env.BIGPOWERS_OMP_TEST_PYTHON;
  assert(python && path.isAbsolute(python), "Explicit isolated Python with PyYAML is required");
  const help = Bun.spawnSync([python, script, "--help"], { cwd: workspace, env: process.env, stdout: "pipe", stderr: "pipe" });
  assert.equal(help.exitCode, 0, `Canonical grid script --help failed: ${help.stderr}`);
  assert(help.stdout.toString().includes("--cols") && help.stdout.toString().includes("--scaffold"));
  console.log("Canonical asset smoke: actual host directory/script reads and explicit Python grid_tokens.py --help; no browser/install/publication.");
}
export async function assertLegacyCoexistence(runtime: ProviderFixture): Promise<void> {
  const dependency = path.join(sourceRoot, "node_modules", "typebox");
  assert(existsSync(path.join(dependency, "package.json")),
    "Legacy coexistence needs its existing declared dev dependencies; run npm ci in the source checkout");
  const modules = path.join(workspace, "node_modules");
  mkdirSync(modules, { recursive: true });
  symlinkSync(dependency, path.join(modules, "typebox"), "dir");
  function registrations(session: NativeSession) {
    const runner = session.extensionRunner;
    assert(runner, "Actual SDK must construct its extension host");
    const loaded = runner.getLoadedExtensions();
    const legacy = loaded.filter(extension => extension.resolvedPath === path.join(workspace, "extensions", "omp-hooks.ts"));
    assert.equal(legacy.length, 1, "The same legacy extension must not be loaded twice");
    const result = {
      extensions: loaded.map(extension => extension.resolvedPath).sort(),
      tools: runner.getAllRegisteredTools().map(tool => tool.definition.name).sort(),
      commands: runner.getRegisteredCommands().map(command => command.name).sort(),
      handlers: [...legacy[0].handlers].map(([event, handlers]) => [event, handlers.length]).sort(),
    };
    assert.equal(result.tools.filter(name => name === "bigpowers_skill").length, 1);
    assert.deepEqual(result.commands.filter(name => name.startsWith("bigpowers-")), [],
      "Native convenience commands must not also register as extension commands");
    assert.deepEqual(result.handlers, [["session_start", 1], ["tool_call", 1]], "Native resources must not register duplicate guards");
    return result;
  }
  const legacyOnly = await runtime.session("*", { skills: [], slashCommands: [], legacyExtension: true });
  const nativeAndLegacy = await runtime.session("*", { legacyExtension: true });
  assert.deepEqual(registrations(nativeAndLegacy), registrations(legacyOnly),
    "Adding native resources must not change actual legacy host registrations");
  console.log("Legacy coexistence: actual SDK loaded one legacy extension, one legacy tool and one guard; no extension slash-command registrations.");
}
export async function runDeliveryCandidate(sdk: NativeSdk): Promise<void> {
  const skills = (await sdk.discoverSkills(workspace)).skills;
  const slash = await sdkImport<NativeSlash>("/extensibility/slash-commands");
  const commands = await slash.loadSlashCommands({ cwd: workspace });
  const command = commands.find(item => item.name === "bigpowers-align-grid");
  assert(command && command.source.includes("Project"), "Copied delivery candidate must be discovered without generation");
  const expanded = slash.expandSlashCommand('/bigpowers-align-grid "relocated path" \'$ARGUMENTS $1\'', commands);
  assert(expanded.includes("skill://align-grid") && expanded.includes("relocated path") && expanded.includes("$ARGUMENTS $1"));
  const before = resourceSnapshot();
  const runtime = await createProviderFixture(sdk, skills, commands);
  try {
    const session = await runtime.session();
    assert.equal(session.extensionRunner?.getLoadedExtensions().length, 0, "Native delivery resources must not load extensions");
    await readGridResources(session, skills);
    await assertLegacyCoexistence(runtime);
    assertResourcesUnchanged(before);
  } finally { await runtime.dispose(); }
  console.log("PASS delivery-candidate relocation: full source tree, exact generated bytes, native discovery/command/read/asset/legacy APIs; no regeneration or remotely committed artifact claim.");
}

import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { agentDir, put, sdkImport, workspace } from "./omp_native_fixture";
import type { NativeSdk, NativeSession, NativeSlash, Skill, ToolResult } from "./omp_native_types";

export function installUserFixtures(): void {
  put(path.join(agentDir, "skills", "native-example", "SKILL.md"),
    "---\nname: native-example\ndescription: A different user-owned skill.\n---\nUser collision remains user owned.\n");
  put(path.join(agentDir, "commands", "bigpowers-native-example.md"),
    "---\ndescription: User command collision.\n---\nUSER-COMMAND $ARGUMENTS\n");
  // Synthetic user definitions are isolated test input, never renderer output.
  for (const name of ["task", "reviewer"]) put(path.join(agentDir, "agents", `${name}.md`),
    `---\nname: ${name}\ndescription: TEST-ONLY ${name}.\nmodel: fixture-override/override\ntools: read\nspawns: false\n---\n` +
    `Respond independently as TEST-ONLY ${name}. Do not use tools, network, or modify files.\n`);
  put(path.join(agentDir, "agents", "native-fallback.md"),
    "---\nname: native-fallback\ndescription: TEST-ONLY default inheritance.\nmodel: default\ntools: read\nspawns: false\n---\nRespond independently without tools.\n");
}
export async function discoverResources(sdk: NativeSdk) {
  const slash = await sdkImport<NativeSlash>("/extensibility/slash-commands");
  const found = await sdk.discoverSkills(workspace);
  const generatedPath = path.join(workspace, ".omp", "skills", "native-example", "SKILL.md");
  const generated = found.skills.find(skill => skill.filePath === generatedPath);
  assert(generated, "Actual SDK must discover the generated canonical skill");
  const collided = found.skills.filter(skill => skill.filePath.endsWith("native-example/SKILL.md"));
  assert.equal(collided.length, 2, "Differing user/project skills must both survive native collision handling");
  assert.notEqual(collided[0].name, collided[1].name, "Collisions must not silently lose either resource");
  assert(collided.some(skill => skill.name.includes("/")), "Native same-name collisions are namespaced");
  const commands = await slash.loadSlashCommands({ cwd: workspace });
  const command = commands.find(command => command.name === "bigpowers-native-example");
  assert(command && command.source.includes("Project"), "Project command wins the user command collision at root");
  const expanded = slash.expandSlashCommand('/bigpowers-native-example "quoted argument" tail', commands);
  assert.equal(expanded, slash.renderFileSlashCommand(command, '"quoted argument" tail'));
  const targetJson = expanded.match(/"(?:[^"\\]|\\.)*SKILL\.md"/)?.[0];
  assert(targetJson, "Expanded command must identify a readable skill target");
  const commandTarget: string = JSON.parse(targetJson);
  assert(expanded.includes("quoted argument tail"), "Native argument parser expands quoted wrapper arguments");
  assert(!expanded.includes("Literal examples remain literal"), "Command must not inline source dollar examples");
  assert.equal(slash.expandSlashCommand("/unknown-native-command keep", commands), "/unknown-native-command keep");
  const nested = path.join(workspace, "nested", "deep");
  mkdirSync(nested, { recursive: true });
  const nestedSkills = await sdk.discoverSkills(nested);
  assert(nestedSkills.skills.some(skill => skill.filePath === generatedPath), "Native skills walk project ancestors");
  const nestedCommands = await slash.loadSlashCommands({ cwd: nested });
  const nestedCommand = nestedCommands.find(command => command.name === "bigpowers-native-example");
  assert(nestedCommand && nestedCommand.source.includes("User"), "Nested cwd does not inherit root project commands; user command remains");
  assert.equal(slash.expandSlashCommand("/bigpowers-native-example nested", nestedCommands), "USER-COMMAND nested");
  console.log(`Discovery: root project command; nested cwd user command; ${collided.map(skill => skill.name).join(", ")} preserved.`);
  return { skills: found.skills, commands, generated, slash, commandTarget };
}
function text(result: ToolResult): string {
  assert(!result.isError, `Native read failed: ${JSON.stringify(result)}`);
  return result.content.map(item => item.text ?? "").join("\n");
}
export async function readNativeResources(session: NativeSession, generated: Skill, commandTarget: string): Promise<void> {
  const reader = session.getToolByName("read");
  assert(reader, "SDK must expose its actual native read tool");
  const commandBody = text(await reader.execute("expanded-command-target", { path: commandTarget }));
  assert(commandBody.includes("Literal examples remain literal"), "Expanded command target must read the intended generated skill");
  const body = text(await reader.execute("native-skill", { path: `skill://${generated.name}` }));
  assert(body.includes("Literal examples remain literal"));
  assert(body.includes("$1") && body.includes("$ARGUMENTS") && body.includes("${HOME}"));
  const asset = text(await reader.execute("native-asset", { path: `skill://${generated.name}/assets/detail.txt` }));
  assert(asset.includes("native-asset-verified"), "Native skill protocol must read generated supporting assets");
  const generatedBody = readFileSync(generated.filePath, "utf8");
  const references = [...generatedBody.matchAll(/\]\(([^)]+)\)/g)].map(match => match[1]);
  const outward = references.find(reference => reference.endsWith("reference.txt"));
  assert(outward && (outward.startsWith("file://") || path.isAbsolute(outward)), "Outward source dependency must be explicit and repo-backed");
  const source = text(await reader.execute("native-outward", { path: outward }));
  assert(source.includes("outward-source-dependency-verified"));
  console.log("Read: real session read tool + skill:// loaded skill body, supporting asset, and outward source dependency.");
}

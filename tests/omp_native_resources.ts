import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { agentDir, put, root, sdkImport, workspace } from "./omp_native_fixture";
import type { NativeSdk, NativeSession, NativeSkills, NativeSlash, Skill, ToolResult } from "./omp_native_types";

export function installUserFixtures(): void {
  put(path.join(agentDir, "skills", "native-example", "SKILL.md"),
    "---\nname: native-example\ndescription: A different user-owned skill.\n---\nUser collision remains user owned.\n");
  put(path.join(agentDir, "commands", "bigpowers-native-example.md"),
    "---\ndescription: User command collision.\n---\nUSER-COMMAND $ARGUMENTS\n");
  put(path.join(root, "custom skills", "native-example", "SKILL.md"),
    "---\nname: native-example\ndescription: Explicit custom-directory override.\n---\nCUSTOM-DIRECTORY-OVERRIDE\n");
  // Synthetic user definitions are isolated test input, never renderer output.
  for (const name of ["task", "reviewer"]) put(path.join(agentDir, "agents", `${name}.md`),
    `---\nname: ${name}\ndescription: TEST-ONLY ${name}.\nmodel: fixture-override/override\ntools: read\nspawns: false\n---\n` +
    `Respond independently as TEST-ONLY ${name}. Do not use tools, network, or modify files.\n`);
  put(path.join(agentDir, "agents", "native-fallback.md"),
    "---\nname: native-fallback\ndescription: TEST-ONLY default inheritance.\nmodel: default\ntools: read\nspawns: false\n---\nRespond independently without tools.\n");
}
export async function discoverResources(sdk: NativeSdk) {
  const slash = await sdkImport<NativeSlash>("/extensibility/slash-commands");
  const loader = await sdkImport<NativeSkills>("/extensibility/skills");
  const found = await sdk.discoverSkills(workspace);
  const generatedPath = path.join(workspace, ".omp", "skills", "native-example", "SKILL.md");
  const generated = found.skills.find(skill => skill.filePath === generatedPath);
  assert(generated, "Actual SDK must discover the generated canonical skill");
  assert.equal(generated.description, "Read --- separators in native fixture resources.");
  const collided = found.skills.filter(skill => skill.filePath.endsWith("native-example/SKILL.md"));
  const userPath = path.join(agentDir, "skills", "native-example", "SKILL.md");
  assert(collided.some(skill => skill.filePath === userPath), "User variant must survive normal multi-target discovery");
  assert.equal(new Set(collided.map(skill => skill.name)).size, collided.length, "Every discovered variant needs a distinct native address");
  const commands = await slash.loadSlashCommands({ cwd: workspace });
  const command = commands.find(command => command.name === "bigpowers-native-example");
  assert(command && command.source.includes("Project"), "Project command wins the user command collision at root");
  const args = '"quoted argument" \'dollar $ARGUMENTS $1 ${HOME}\' tail';
  const expanded = slash.expandSlashCommand(`/bigpowers-native-example ${args}`, commands);
  assert.equal(expanded, slash.renderFileSlashCommand(command, args));
  assert(expanded.includes("skill://native-example"), "Convenience command must use native name selection");
  assert(expanded.includes("quoted argument") && expanded.includes("dollar $ARGUMENTS $1 ${HOME}"),
    "Native argument expansion retains quotes/spaces and literal dollar placeholders without shell interpolation");
  assert(!expanded.includes("Literal examples remain literal"), "Command must not inline the compiled skill body");
  assert.equal(slash.expandSlashCommand("/unknown-native-command keep", commands), "/unknown-native-command keep");
  const nested = path.join(workspace, "nested", "deep");
  mkdirSync(nested, { recursive: true });
  const nestedSkills = await sdk.discoverSkills(nested);
  assert(nestedSkills.skills.some(skill => skill.filePath === generatedPath), "Pinned SDK skills discover ancestor .omp roots");
  const nestedCommands = await slash.loadSlashCommands({ cwd: nested });
  const nestedCommand = nestedCommands.find(command => command.name === "bigpowers-native-example");
  assert(nestedCommand && nestedCommand.source.includes("User"), "Commands are cwd-local, not inherited from project ancestors");
  assert.equal(slash.expandSlashCommand("/bigpowers-native-example nested", nestedCommands), "USER-COMMAND nested");
  const userSkills = (await loader.loadSkills({
    cwd: workspace, enablePiUser: false, customDirectories: [path.join(agentDir, "skills")],
  })).skills;
  assert.equal(userSkills.find(skill => skill.name === "native-example")?.filePath,
    path.join(agentDir, "skills", "native-example", "SKILL.md"), "Explicit user directory overrides native name selection");
  const customPath = path.join(root, "custom skills", "native-example", "SKILL.md");
  const custom = await loader.loadSkills({ cwd: workspace, customDirectories: [path.dirname(path.dirname(customPath))] });
  assert.equal(custom.skills.find(skill => skill.name === "native-example")?.filePath, customPath,
    "Custom-directory override must own the command's bare native URI");
  const variants = custom.skills.filter(skill => skill.filePath.endsWith("native-example/SKILL.md"));
  for (const required of [generatedPath, userPath, customPath]) {
    assert(variants.some(skill => skill.filePath === required), `Native collision handling lost ${required}`);
  }
  assert.equal(new Set(variants.map(skill => skill.name)).size, variants.length);
  console.log("Discovery: actual SDK command cwd semantics, quoted/dollar arguments, user/custom overrides and differing skill variants.");
  const commandTarget = expanded.match(/skill:\/\/[a-z0-9/-]+/)?.[0];
  assert.equal(commandTarget, "skill://native-example", "Read target must come from actual native command expansion");
  return { skills: custom.skills, commands, userSkills, slash, commandTarget: commandTarget! };
}
function text(result: ToolResult): string {
  assert(!result.isError, `Native read failed: ${JSON.stringify(result)}`);
  return result.content.map(item => item.text ?? "").join("\n");
}
export async function readNativeResources(session: NativeSession, skills: Skill[], commandTarget: string, expected: string): Promise<void> {
  const reader = session.getToolByName("read");
  assert(reader, "SDK must expose its actual native read tool");
  const commandBody = text(await reader.execute("expanded-command-target", { path: commandTarget }));
  assert(commandBody.includes(expected), "Expanded command must honor native skill override selection");
  const generatedPath = path.join(workspace, ".omp", "skills", "native-example", "SKILL.md");
  const generated = skills.find(skill => skill.filePath === generatedPath);
  assert(generated);
  const body = text(await reader.execute("native-generated-variant", { path: `skill://${generated.name}` }));
  assert(body.includes("Literal examples remain literal") && body.includes("Compiled sibling Markdown remains available."));
  assert(body.includes("$1") && body.includes("$ARGUMENTS") && body.includes("${HOME}"));
  for (const skill of skills.filter(skill => skill.filePath.endsWith("native-example/SKILL.md"))) {
    const variant = text(await reader.execute(`variant-${skill.name}`, { path: `skill://${skill.name}` }));
    const expectedVariant = skill.filePath.startsWith(agentDir + path.sep) ? "User collision remains user owned"
      : skill.filePath === path.join(root, "custom skills", "native-example", "SKILL.md")
        ? "CUSTOM-DIRECTORY-OVERRIDE" : "Literal examples remain literal";
    assert(variant.includes(expectedVariant), `Actual native URI lost variant ${skill.name}`);
  }
  const generatedBody = readFileSync(generated.filePath, "utf8");
  const references = [...generatedBody.matchAll(/\]\(([^)]+)\)/g)].map(match => match[1]);
  for (const [suffix, sentinel] of [["detail.txt", "native-asset-verified"], ["reference.txt", "outward-source-dependency-verified"]]) {
    const reference = references.find(link => link.endsWith(suffix));
    assert(reference && !path.isAbsolute(reference) && !reference.includes("://"), "Canonical assets require portable relative links");
    const resolved = path.resolve(path.dirname(generated.filePath), reference);
    assert(resolved.startsWith(workspace + path.sep) && !resolved.startsWith(path.join(workspace, ".omp") + path.sep));
    assert(text(await reader.execute(`canonical-${suffix}`, { path: resolved })).includes(sentinel));
  }
}
export async function checkNativeControls(session: NativeSession, skills: Skill[]): Promise<void> {
  const reader = session.getToolByName("read");
  assert(reader);
  const prompt = session.systemPrompt.join("\n");
  for (const control of ["hide", "disable-model-invocation"]) {
    for (const state of ["true", "false", "absent"]) {
      const name = `native-${control}-${state}`;
      const skill = skills.find(candidate => candidate.name === name);
      assert(skill, `SDK must retain explicitly accessible skill ${name}`);
      assert.equal(skill.description, `Folded --- description for ${name}.`, "Actual SDK must parse folded description");
      assert.equal(skill.hide, state === "true", `SDK normalizes ${control}: ${state} visibility`);
      assert.equal(prompt.includes(`- ${name}:`) || prompt.includes(`<skill name="${name}">`), state !== "true",
        "Actual model-facing system prompt must honor native visibility");
      const body = text(await reader.execute(name, { path: `skill://${name}` }));
      assert(body.includes(`Explicit access: ${control === "hide" ? "visibility" : "invocation"}/${state}.`),
        `Hidden skill ${name} must remain explicitly readable`);
    }
  }
  console.log("Read: command-selected override, generated/user variants, compiled sibling Markdown, canonical asset links, SDK metadata visibility and explicit access.");
}

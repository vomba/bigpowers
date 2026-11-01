import assert from "node:assert/strict";
import net from "node:net";
import path from "node:path";
import { agentDir, copyDeliveryCandidate, generateFixture, root, sdkImport, workspace } from "./omp_native_fixture";
import { installUserFixtures } from "./omp_native_resources";
import { runRouting } from "./omp_native_routing";
import { runDeliveryCandidate } from "./omp_native_delivery";
import type { NativeSdk, NativeSlash, NativeSubagent } from "./omp_native_types";

assert(root && process.env.HOME?.startsWith(root + path.sep));
assert(agentDir.startsWith(root + path.sep));
assert.equal(process.cwd(), workspace);
for (const key of ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"]) {
  assert(process.env[key]?.startsWith(root + path.sep), `${key} must be isolated before importing SDK`);
}
const python = process.env.BIGPOWERS_OMP_TEST_PYTHON;
assert(python && path.isAbsolute(python), "Explicit Python prerequisite must be selected before SDK import");
const yaml = Bun.spawnSync([python, "-c", "import yaml; print(yaml.__version__)"],
  { cwd: workspace, env: process.env, stdout: "pipe", stderr: "pipe" });
assert.equal(yaml.exitCode, 0, `Explicit isolated Python must provide PyYAML: ${yaml.stderr}`);
const attempts: string[] = [];
globalThis.fetch = async () => {
  attempts.push("fetch");
  throw new Error("Native fixture forbids network requests");
};
// Deny accidental node HTTP/socket paths as well as fetch; no fake provider transport.
net.Socket.prototype.connect = function (): never {
  attempts.push("socket.connect");
  throw new Error("Native fixture forbids network sockets");
};
const sdk = await sdkImport<NativeSdk>();
assert.equal(sdk.VERSION, "18.13.3");
for (const symbol of ["createAgentSession", "Settings", "SessionManager", "AuthStorage", "ModelRegistry", "discoverSkills", "discoverSlashCommands"] as const) {
  assert.equal(typeof sdk[symbol], "function", `Pinned SDK missing required root export ${symbol}`);
}
assert.equal(typeof sdk.AuthStorage.create, "function", "Pinned SDK must expose explicit isolated AuthStorage.create");
assert.equal(typeof sdk.Settings.isolated, "function");
assert.equal(typeof sdk.SessionManager.inMemory, "function");
const slash = await sdkImport<NativeSlash>("/extensibility/slash-commands");
assert.equal(typeof slash.expandSlashCommand, "function");
assert.equal(typeof slash.renderFileSlashCommand, "function");
assert.equal(typeof slash.loadSlashCommands, "function");
const subagent = await sdkImport<NativeSubagent>("/task/structured-subagent");
assert.equal(typeof subagent.resolveEffectiveSubagentPolicy, "function");
assert.equal(typeof subagent.runStructuredSubagent, "function");
assert.equal(attempts.length, 0, "Prerequisite import attempted network");
console.log("PASS prerequisites: Bun 1.4.4; approved OMP 18.13.3 package exports; settings/auth/session/discovery/task APIs; sanitized HOME/XDG/config/auth roots before all SDK imports; no downloads.");
if (process.env.BIGPOWERS_OMP_TEST_SUITE !== "prerequisites") {
  if (process.env.BIGPOWERS_OMP_TEST_MODE === "delivery") {
    copyDeliveryCandidate();
    await runDeliveryCandidate(sdk);
  } else {
    generateFixture();
    installUserFixtures();
    await runRouting(sdk);
    console.log("PASS routing: actual native discovery, command expansion, skill/read assets, metadata controls, collision/cwd semantics, task role resolution, launches and policy rejection.");
  }
  assert.equal(attempts.length, 0, `Unexpected network attempts: ${attempts.join(", ")}`);
}

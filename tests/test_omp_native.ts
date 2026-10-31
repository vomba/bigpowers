// Native integration harness: no root dependency, downloads, or operational OMP fallback.
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";

const args = process.argv.slice(2);
assert(args.length === 0 || (args.length === 2 && args[0] === "--suite"),
  "Usage: bun tests/test_omp_native.ts [--suite prerequisites|routing|all]");
const suite = args[1] ?? "all";
assert(["prerequisites", "routing", "all"].includes(suite), `Invalid suite: ${suite}`);
assert.equal(Bun.version, "1.4.4", "Native tests require explicitly provisioned Bun 1.4.4");
const approved = process.env.BIGPOWERS_OMP_TEST_ROOT;
assert(approved && path.isAbsolute(approved), "BIGPOWERS_OMP_TEST_ROOT must name the approved isolated SDK dependency root");
const runtimeRoot = realpathSync(approved);
const repo = path.resolve(import.meta.dir, "..");
assert(runtimeRoot !== repo && !runtimeRoot.includes(`${path.sep}.omp${path.sep}`),
  "Operational installations and repository dependencies are not native test runtimes");
const lockBytes = readFileSync(path.join(runtimeRoot, "package-lock.json"));
const lock = JSON.parse(lockBytes.toString());
const entry = lock.packages?.["node_modules/@oh-my-pi/pi-coding-agent"];
assert.equal(entry?.version, "18.13.3", "Approved runtime lock must pin OMP 18.13.3");
assert.equal(entry?.integrity, "sha512-FdFC0spf+AQKgYI54Kkkvo7yVhfYKx+iNLf8aWg1h0FZbkwqoy4mBAUrZK8YOC4+opXtXt5qkR2tqF8I/eAJjQ==",
  "SDK lock integrity must match the published 18.13.3 SRI");
assert.equal(entry?.resolved, "https://registry.npmjs.org/@oh-my-pi/pi-coding-agent/-/pi-coding-agent-18.13.3.tgz");
const manifest = readFileSync(path.join(runtimeRoot, "node_modules/@oh-my-pi/pi-coding-agent/package.json"));
assert.equal(JSON.parse(manifest.toString()).version, "18.13.3");
console.log(`Runtime provenance: published npm SRI verified in approved lock; lock sha256=${createHash("sha256").update(lockBytes).digest("hex")}; manifest sha256=${createHash("sha256").update(manifest).digest("hex")}`);
console.log("Integrity scope: validates installed package identity and lock provenance, not a fresh tarball/file-tree attestation.");

const isolated = realpathSync(mkdtempSync(path.join(tmpdir(), "bigpowers-omp-native-")));
try {
  const home = path.join(isolated, "home");
  const agentDir = path.join(home, ".omp", "agent");
  const workspace = path.join(isolated, "workspace-$ARGUMENTS-$1");
  for (const dir of [home, agentDir, workspace, "config", "data", "state", "cache", "tmp"].map(
    dir => path.isAbsolute(dir) ? dir : path.join(isolated, dir))) mkdirSync(dir, { recursive: true });
  // Whitelist, never copy process.env: excludes provider secrets, overlays, plugins, and sessions.
  const env: Record<string, string> = {
    HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: path.join(isolated, "config"),
    XDG_DATA_HOME: path.join(isolated, "data"), XDG_STATE_HOME: path.join(isolated, "state"),
    XDG_CACHE_HOME: path.join(isolated, "cache"), TMPDIR: path.join(isolated, "tmp"),
    PI_CODING_AGENT_DIR: agentDir, PI_CONFIG_DIR: ".omp", OMP_PROFILE: "",
    BIGPOWERS_OMP_TEST_ROOT: runtimeRoot, BIGPOWERS_OMP_FIXTURE_ROOT: isolated,
    BIGPOWERS_OMP_SOURCE_ROOT: repo, BIGPOWERS_OMP_TEST_SUITE: suite,
    PATH: `${path.dirname(process.execPath)}:/usr/bin:/bin:/usr/sbin:/sbin`, LANG: "en_US.UTF-8",
    GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: path.join(home, "gitconfig"),
  };
  const python = process.env.BIGPOWERS_OMP_TEST_PYTHON;
  if (python) {
    assert(path.isAbsolute(python), "BIGPOWERS_OMP_TEST_PYTHON must be an explicit Python executable with PyYAML");
    env.BIGPOWERS_OMP_TEST_PYTHON = python;
    env.PATH = `${path.dirname(python)}:${env.PATH}`;
  }
  const child = Bun.spawn([process.execPath, "--no-env-file", path.join(import.meta.dir, "omp_native_worker.ts")],
    { cwd: workspace, env, stdout: "inherit", stderr: "inherit" });
  const exit = await child.exited;
  assert.equal(exit, 0, `Isolated native ${suite} suite failed (exit ${exit})`);
} finally {
  rmSync(isolated, { recursive: true, force: true });
}

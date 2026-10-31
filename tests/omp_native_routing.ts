import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { agentDir, assertResourcesUnchanged, put, resourceSnapshot, sdkImport } from "./omp_native_fixture";
import { createProviderFixture } from "./omp_native_provider";
import { discoverResources, readNativeResources } from "./omp_native_resources";
import type { NativeSdk, NativeSubagent, Policy } from "./omp_native_types";

export async function runRouting(sdk: NativeSdk): Promise<void> {
  const resources = await discoverResources(sdk);
  const native = await sdkImport<NativeSubagent>("/task/structured-subagent");
  const configPath = path.join(agentDir, "config.yml");
  put(configPath, "# TEST-ONLY isolated user configuration sentinel\nmodelRoles:\n  default: fixture-parent/parent\n");
  const configBytes = readFileSync(configPath);
  const files = resourceSnapshot();
  const runtime = await createProviderFixture(sdk, resources.skills, resources.commands);
  try {
    const parent = await runtime.session();
    const initialModel = parent.model;
    assert(initialModel);
    await readNativeResources(parent, resources.generated, resources.commandTarget);
    assert.equal(parent.model, initialModel, "Inline resource reads cannot change the parent allocation");
    const context = runtime.toolSession(parent);
    const request = { session: context, invocationKind: "task", assignment: "Return deterministic fixture text", structured: false };
    const omitted = await native.resolveEffectiveSubagentPolicy(request);
    assert.equal(omitted.agentName, "task", "Unrestricted native omission defaults to implementation task");
    assert.equal(omitted.modelRole, "task");
    assert.deepEqual(omitted.modelOverride, ["fixture-task/worker"]);
    function trace(policy: Policy) {
      console.log(`Native policy: agent=${policy.agentName}; role=${policy.modelRole ?? "native-inheritance"}; patterns=${policy.modelOverride?.join(",")}`);
    }
    trace(omitted);
    const worker = await runtime.dispatch(parent, [{ name: "Implementation", task: "IMPLEMENTATION-CONTEXT-ONLY" }]);
    assert.equal(worker.length, 1, "Controlled task call must actually launch one native child");
    assert.equal(worker[0].provider, "fixture-task");
    assert.equal(worker[0].model, "worker");
    const reviewPolicy = await native.resolveEffectiveSubagentPolicy({ ...request, agent: "reviewer" });
    assert.equal(reviewPolicy.modelRole, "review");
    assert.deepEqual(reviewPolicy.modelOverride, ["fixture-review/review"]);
    trace(reviewPolicy);
    const reviewPrompt = resources.slash.expandSlashCommand('/bigpowers-request-review "HEAD~1..HEAD"', resources.commands);
    const reviews = await runtime.dispatch(parent, [
      { name: "ReviewerA", agent: "reviewer", task: "REVIEW-A-PRIVATE-CONTEXT; independently return PASS" },
      { name: "ReviewerB", agent: "reviewer", task: "REVIEW-B-PRIVATE-CONTEXT; independently return PASS" },
    ], reviewPrompt);
    assert.equal(reviews.length, 2, "Existing request-review workflow is exercised with its mandatory reviewer pair");
    assert(reviews.every(review => review.provider === "fixture-review" && review.model === "review"));
    assert(reviews.every(review => typeof review.sessionId === "string" && review.sessionId.length > 0));
    assert.notEqual(reviews[0].sessionId, reviews[1].sessionId, "Independent reviewers require distinct child session IDs");
    const a = reviews.find(review => review.text.includes("REVIEW-A-PRIVATE-CONTEXT"));
    const b = reviews.find(review => review.text.includes("REVIEW-B-PRIVATE-CONTEXT"));
    assert(a && b && a !== b);
    assert(!a.text.includes("REVIEW-B-PRIVATE-CONTEXT") && !b.text.includes("REVIEW-A-PRIVATE-CONTEXT"),
      "Independent reviewer contexts cannot inherit one another's assignment");
    assert(!reviews.some(review => review.text.includes("IMPLEMENTATION-CONTEXT-ONLY")), "Reviewer contexts must not inherit worker transcript");
    runtime.settings.overrideModelRoles({ task: "fixture-review/review-next", review: "fixture-task/worker-next" });
    const nextTask = await native.resolveEffectiveSubagentPolicy(request);
    const nextReview = await native.resolveEffectiveSubagentPolicy({ ...request, agent: "reviewer" });
    trace(nextTask); trace(nextReview);
    assert.deepEqual(nextTask.modelOverride, ["fixture-review/review-next"]);
    assert.deepEqual(nextReview.modelOverride, ["fixture-task/worker-next"]);
    const remapped = await runtime.dispatch(parent, [
      { name: "RemappedTask", task: "Remapped implementation" },
      { name: "RemappedReview", agent: "reviewer", task: "Remapped review" },
    ]);
    assert.deepEqual(remapped.map(call => `${call.provider}/${call.model}`).sort(),
      ["fixture-review/review-next", "fixture-task/worker-next"].sort());
    assertResourcesUnchanged(files);
    // Exact user overrides outrank agent frontmatter AND role-bound task defaults.
    runtime.taskSettings.cfgTaskAgentModelOverrides.override(runtime.settings, { task: "fixture-override/override", reviewer: "@review" });
    const explicit = await native.resolveEffectiveSubagentPolicy(request);
    assert.deepEqual(explicit.modelOverride, ["fixture-override/override"]);
    assert.equal(explicit.modelRole, undefined);
    const overridden = await runtime.dispatch(parent, [{ name: "ExplicitOverride", task: "User override precedence" }]);
    assert.equal(overridden[0]?.provider, "fixture-override");
    // Do not invent a provider fallback when a built-in role is unconfigured.
    runtime.modelSettings.cfgModelRoles.override(runtime.settings, {
      default: "fixture-parent/parent", review: "fixture-task/worker-next",
    });
    runtime.taskSettings.cfgTaskAgentModelOverrides.override(runtime.settings, { task: "@task", reviewer: "@review" });
    const missingRole = await native.resolveEffectiveSubagentPolicy(request);
    assert.equal(runtime.settings.getModelRole("task"), undefined);
    assert(!missingRole.modelOverride?.includes("fixture-review/review-next"), "Removed role cannot retain the prior user allocation");
    trace(missingRole);
    const missingBefore = runtime.traces.length;
    await native.runStructuredSubagent({ ...request, enableLsp: false, enableIrc: false });
    const missingCalls = runtime.traces.slice(missingBefore);
    assert.equal(missingCalls.length, 1, "Missing-role resolution must launch one actual native child");
    assert(["fixture-parent", "fixture-override"].includes(missingCalls[0].provider),
      "Native missing-role fallback must use authenticated parent/default or agent frontmatter, never an invented allocation");
    console.log(`Unconfigured role native fallback: ${missingCalls[0].provider}/${missingCalls[0].model}`);
    // No mapping for this test-only user agent: the actual native resolver inherits the parent.
    const fallback = await native.resolveEffectiveSubagentPolicy({ ...request, agent: "native-fallback" });
    assert.deepEqual(fallback.modelOverride, ["fixture-parent/parent"]);
    assert.equal(fallback.modelRole, undefined);
    trace(fallback);
    const beforeFallback = runtime.traces.length;
    await native.runStructuredSubagent({ ...request, agent: "native-fallback", enableLsp: false, enableIrc: false });
    assert(runtime.traces.slice(beforeFallback).some(call => call.provider === "fixture-parent" && call.model === "parent"),
      "Native fallback must reach the real child launch path");
    const restricted = await runtime.session("reviewer");
    const restrictedRequest = { ...request, session: runtime.toolSession(restricted) };
    const restrictedDefault = await native.resolveEffectiveSubagentPolicy(restrictedRequest);
    assert.equal(restrictedDefault.agentName, "reviewer", "Restricted omission follows another allowed default, not task");
    const allowed = await runtime.dispatch(restricted, [{ name: "RestrictedDefault", task: "Allowed native default" }]);
    assert.equal(allowed[0]?.provider, "fixture-task");
    await assert.rejects(native.resolveEffectiveSubagentPolicy({ ...restrictedRequest, agent: "task" }), /Cannot spawn 'task'/);
    const beforeRefusal = runtime.traces.length;
    const beforeResults = runtime.toolResults.length;
    await runtime.dispatch(restricted, [{ name: "ForbiddenTask", agent: "task", task: "Must be rejected without substitution" }]);
    assert(!runtime.traces.slice(beforeRefusal).some(call => call.model !== "parent"), "Disallowed task cannot be substituted");
    assert(runtime.toolResults.slice(beforeResults).some(event => /Cannot spawn|not allowed|allowed agents|unknown agent/i.test(JSON.stringify(event))),
      "Real task tool must report its permission boundary");
    assert.equal(parent.model, initialModel, "Native delegated work cannot change parent model");
    assert.deepEqual(readFileSync(configPath), configBytes, "Role tests must not mutate user config bytes");
    assertResourcesUnchanged(files);
    assert.deepEqual(parent.getEnabledToolNames().sort(), ["read", "task"]);
    console.log("Routing scope: deterministic TEST-ONLY providers issued controlled calls through actual SDK task tool/resolver/launcher; task and review use distinct synthetic providers, remap live, and preserve parent/config/resources.");
    console.log("Excluded: arbitrary LLM compliance with skill instructions, real-provider availability, credentials, and live UAT.");
  } finally { await runtime.dispose(); }
}

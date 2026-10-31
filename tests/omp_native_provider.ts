import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { agentDir, resolveRuntime, sdkImport, workspace } from "./omp_native_fixture";
import type { Command, Model, NativeAi, NativeModelSettings, NativeSdk, NativeSession, NativeTaskSettings, Skill, ToolContext } from "./omp_native_types";

export interface Dispatch { agent?: string; task: string; name: string; }
export interface CallTrace { provider: string; model: string; sessionId?: string; text: string; }
export async function createProviderFixture(sdk: NativeSdk, skills: Skill[], slashCommands: Command[]) {
  // The approved external runtime is selected at invocation; no root dependency is allowed.
  const ai: NativeAi = await import(pathToFileURL(resolveRuntime("@oh-my-pi/pi-ai")).href);
  const taskSettings = await sdkImport<NativeTaskSettings>("/task/settings");
  const modelSettings = await sdkImport<NativeModelSettings>("/config/model-settings");
  const queue: Dispatch[][] = [];
  const traces: CallTrace[] = [];
  const toolResults: Record<string, unknown>[] = [];
  const settings = sdk.Settings.isolated({
    "modelRoles": { default: "fixture-parent/parent", task: "fixture-task/worker", review: "fixture-review/review" },
    "task.agentModelOverrides": { task: "@task", reviewer: "@review" },
    "task.structured": false, "task.batch": false, "task.enableLsp": false,
    "async.enabled": false, "compaction.enabled": false, "autolearn.enabled": false,
    "memory.backend": "off",
    "tools.approvalMode": "yolo",
  });
  const auth = await sdk.AuthStorage.create(path.join(agentDir, "fixture-auth.db"));
  const registry = new sdk.ModelRegistry(auth, path.join(agentDir, "models.yml"), {
    settings, cacheDbPath: path.join(agentDir, "fixture-models.db"),
    fetch: async () => { throw new Error("Native fixture forbids model registry network"); },
  });
  const providers: Record<string, string[]> = {
    "fixture-parent": ["parent"], "fixture-task": ["worker", "worker-next"],
    "fixture-review": ["review", "review-next"], "fixture-override": ["override"],
  };
  let callId = 0;
  function stream(model: Model, context: { messages: unknown[] }, options?: { sessionId?: string }) {
    const out = ai.createAssistantMessageEventStream();
    const text = JSON.stringify(context.messages);
    traces.push({ provider: model.provider, model: model.id, sessionId: options?.sessionId, text });
    console.log(`Native dispatch transport: provider=${model.provider}; model=${model.id}; session=${options?.sessionId ?? "missing"}`);
    const calls = model.id === "parent" ? queue.shift() ?? [] : [];
    const content = calls.length ? calls.map(item => ({
      type: "toolCall", id: `fixture-${++callId}`, name: "task", arguments: {
        ...item, solutionSpace: "one deterministic fixture response; no files changed",
      },
    })) : [{ type: "text", text: `TEST-ONLY ${model.provider}/${model.id} completed independently` }];
    const message = {
      role: "assistant", content, api: model.api, provider: model.provider, model: model.id,
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      stopReason: calls.length ? "toolUse" : "stop", timestamp: Date.now(),
    };
    queueMicrotask(() => {
      out.push({ type: "start", partial: message });
      // Native stream consumers finalize calls on toolcall_end, not just done.content.
      for (const [contentIndex, block] of content.entries()) {
        if (block.type === "toolCall") {
          out.push({ type: "toolcall_start", contentIndex, partial: message });
          out.push({ type: "toolcall_end", contentIndex, toolCall: block, partial: message });
        } else {
          out.push({ type: "text_start", contentIndex, partial: message });
          out.push({ type: "text_end", contentIndex, content: block.text, partial: message });
        }
      }
      out.push({ type: "done", reason: message.stopReason, message });
      out.end();
    });
    return out;
  }
  for (const [provider, ids] of Object.entries(providers)) registry.registerProvider(provider, {
    api: "bigpowers-native-test", baseUrl: "https://invalid.example.test", apiKey: "TEST-ONLY-NOT-A-CREDENTIAL",
    streamSimple: stream, models: ids.map(id => ({
      id, name: `TEST-ONLY ${id}`, reasoning: false, input: ["text"], supportsTools: true,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 4096,
    })),
  });
  const sessions: NativeSession[] = [];
  async function session(spawns = "*") {
    const { session: created } = await sdk.createAgentSession({
      cwd: workspace, agentDir, settings, authStorage: auth, modelRegistry: registry,
      model: registry.find("fixture-parent", "parent"), sessionManager: sdk.SessionManager.inMemory(workspace),
      spawns, skills, slashCommands, contextFiles: [], noContextFiles: true, rules: [], promptTemplates: [],
      disableExtensionDiscovery: true, preloadedExtensionPaths: [], preloadedCustomToolPaths: [],
      enableMCP: false, enableLsp: false, enableIrc: false, skipPythonPreflight: true,
      autoTitle: false, cacheWarming: false, toolNames: ["read", "task"], restrictToolNames: true,
      bindProcessState: false, requireYieldTool: false,
    });
    sessions.push(created);
    created.subscribe(event => {
      if (event.type === "tool_execution_end") toolResults.push(event);
    });
    assert(created.getToolByName("task"), "Actual SDK session must construct its native task tool");
    return created;
  }
  async function dispatch(parent: NativeSession, calls: Dispatch[], prompt = "Controlled native dispatch") {
    assert(queue.length === 0);
    queue.push(calls);
    // The next parent turn after the tool response must finish without another dispatch.
    const before = traces.length;
    await parent.prompt(prompt);
    assert.equal(queue.length, 0, "Parent deterministic provider did not consume controlled task calls");
    return traces.slice(before).filter(call => call.model !== "parent");
  }
  return {
    settings, registry, traces, toolResults, session, dispatch, taskSettings, modelSettings,
    toolSession(parent: NativeSession): ToolContext {
      // TS-private, not #private in 18.13.3. Inspect the REAL constructed tool's context.
      const tool = parent.getToolByName("task");
      assert(tool && "session" in tool && typeof tool.session === "object" && tool.session !== null,
        "Pinned SDK native task context layout changed; do not substitute a mock");
      assert("settings" in tool.session && tool.session.settings === settings && "cwd" in tool.session && tool.session.cwd === workspace);
      // Asserted real native tool instance above; retain identity/prototype, never fabricate a context.
      const context = tool.session as ToolContext;
      return context;
    },
    async dispose() {
      try { for (const created of sessions.reverse()) await created.dispose(); }
      finally { auth.close(); }
    },
  };
}

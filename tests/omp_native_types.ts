// Structural surface exercised from runtime-selected, package-export-resolved SDK modules.
export interface Skill { name: string; filePath: string; baseDir: string; hide?: boolean; }
export interface Command { name: string; content: string; source: string; }
export interface Model { id: string; provider: string; api: string; }
export interface ToolResult { content: { type: string; text?: string }[]; isError?: boolean; }
export interface Tool {
  name: string;
  execute(id: string, args: Record<string, unknown>): Promise<ToolResult>;
}
export interface Settings {
  overrideModelRoles(roles: Record<string, string>): void;
  getModelRole(role: string): string | undefined;
}
export interface ToolContext { cwd: string; settings: Settings; }
export interface NativeSession {
  model?: Model;
  sessionId: string;
  getToolByName(name: string): Tool | undefined;
  getEnabledToolNames(): string[];
  prompt(text: string): Promise<void>;
  dispose(): Promise<void>;
  subscribe(callback: (event: Record<string, unknown>) => void): () => void;
}
export interface Registry {
  registerProvider(name: string, config: Record<string, unknown>): void;
  find(provider: string, id: string): Model | undefined;
}
export interface Auth { close(): void; }
export interface NativeSdk {
  VERSION: string;
  Settings: { isolated(overrides: Record<string, unknown>): Settings };
  SessionManager: { inMemory(cwd: string): unknown };
  AuthStorage: { create(file: string): Promise<Auth> };
  ModelRegistry: new (auth: Auth, file: string, options: Record<string, unknown>) => Registry;
  createAgentSession(options: Record<string, unknown>): Promise<{ session: NativeSession }>;
  discoverSkills(cwd: string): Promise<{ skills: Skill[]; warnings: unknown[] }>;
  discoverSlashCommands(cwd: string): Promise<Command[]>;
}
export interface NativeSlash {
  loadSlashCommands(options: { cwd: string }): Promise<Command[]>;
  renderFileSlashCommand(command: Command, args: string): string;
  expandSlashCommand(text: string, commands: Command[]): string;
}
export interface Policy { agentName: string; modelRole?: string; modelOverride?: string[]; }
export interface NativeSubagent {
  resolveEffectiveSubagentPolicy(request: Record<string, unknown>): Promise<Policy>;
  runStructuredSubagent(request: Record<string, unknown>): Promise<unknown>;
}
export interface NativeTaskSettings {
  cfgTaskAgentModelOverrides: { override(settings: Settings, value: Record<string, string>): void };
}
export interface NativeModelSettings {
  cfgModelRoles: { override(settings: Settings, value: Record<string, string>): void };
}
export interface EventStream { push(event: Record<string, unknown>): void; end(): void; }
export interface NativeAi { createAssistantMessageEventStream(): EventStream; }

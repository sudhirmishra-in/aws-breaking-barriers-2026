import { BedrockAgentCoreClient, CreateEventCommand, RetrieveMemoryRecordsCommand } from "@aws-sdk/client-bedrock-agentcore";

/**
 * Derived memory over three SEPARATE AgentCore Memory resources. DynamoDB stays authoritative; this is rebuilt from it.
 *  personal   actor = producer id         private notes about one person's own conversations
 *  organization actor = organization id   authorized summaries and issue events, never transcripts
 *  published  actor = "global"            only reviewed, shared case payloads
 */
export type MemoryScope = "personal" | "organization" | "published";
export interface MemoryHit { text: string; score?: number }
export interface MemoryPort {
  enabled: boolean;
  /** Idempotent by clientToken: the same durable event written twice stores once. */
  write(scope: MemoryScope, actorId: string, sessionId: string, text: string, clientToken: string, at: Date): Promise<void>;
  recall(scope: MemoryScope, actorId: string, query: string, topK: number): Promise<MemoryHit[]>;
}
export const NAMESPACE: Record<MemoryScope, (actor: string) => string> = { personal: (a) => `/producer/${a}/`, organization: (a) => `/org/${a}/`, published: (a) => `/published/${a}/` };

export class AgentCoreMemory implements MemoryPort {
  enabled = true;
  constructor(private ids: Record<MemoryScope, string>, private client = new BedrockAgentCoreClient({})) {}
  async write(scope: MemoryScope, actorId: string, sessionId: string, text: string, clientToken: string, at: Date) {
    await this.client.send(new CreateEventCommand({ memoryId: this.ids[scope], actorId, sessionId: sessionId.slice(0, 100), eventTimestamp: at, clientToken: clientToken.slice(0, 250),
      payload: [{ conversational: { role: "USER", content: { text: text.slice(0, 9000) } } }] }));
  }
  async recall(scope: MemoryScope, actorId: string, query: string, topK: number): Promise<MemoryHit[]> {
    const r = await this.client.send(new RetrieveMemoryRecordsCommand({ memoryId: this.ids[scope], namespacePath: NAMESPACE[scope](actorId), searchCriteria: { searchQuery: query.slice(0, 2000), topK } }));
    return (r.memoryRecordSummaries ?? []).flatMap((m) => { const t = m.content && "text" in m.content ? (m.content as { text?: string }).text : undefined; return t ? [{ text: t, score: m.score }] : []; });
  }
}

/** Test double and "memory not configured" stand-in: records writes in memory, dedupes by client token, can be made to fail. */
export class FakeMemory implements MemoryPort {
  enabled = true; fail = false; events: { scope: MemoryScope; actorId: string; text: string; token: string }[] = [];
  async write(scope: MemoryScope, actorId: string, _s: string, text: string, token: string) {
    if (this.fail) throw new Error("memory_down");
    if (!this.events.some((e) => e.token === token)) this.events.push({ scope, actorId, text, token });
  }
  async recall(scope: MemoryScope, actorId: string, query: string, topK: number) {
    const words = query.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
    return this.events.filter((e) => e.scope === scope && e.actorId === actorId).filter((e) => !words.length || words.some((w) => e.text.toLowerCase().includes(w))).slice(0, topK).map((e) => ({ text: e.text }));
  }
}

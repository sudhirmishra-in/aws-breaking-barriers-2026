import type { Conversation, Message, Outcome, ProducerProfile } from "./contracts";

/** Persistence port. DynamoDB in production; in-memory in unit tests (LOCAL MOCK). */
export interface Store {
  getProfileBySub(sub: string): Promise<ProducerProfile | undefined>;
  putConversation(c: Conversation): Promise<void>;
  getConversation(id: string): Promise<Conversation | undefined>;
  findActiveByOwner(sub: string): Promise<Conversation | undefined>;
  /** Optimistic update: succeeds only if stored version === expectedVersion. Returns the new item. */
  updateConversation(id: string, expectedVersion: number, patch: Partial<Conversation>): Promise<Conversation | undefined>;
  /** Atomic lock: succeeds only if no unexpired lock exists. */
  acquireLock(id: string, token: string, nowMs: number, ttlMs: number): Promise<boolean>;
  releaseLock(id: string, token: string): Promise<void>;
  /** Owner's conversations, newest first (eventually consistent index). */
  listByOwner(sub: string): Promise<Conversation[]>;
  /** Pointer to the owner's most recently started active conversation (strongly consistent). */
  setCurrent(sub: string, conversationId: string, nowMs: number): Promise<void>;
  clearCurrent(sub: string, conversationId: string): Promise<void>;
  /** Extend the retention of a saved conversation's messages. */
  retainMessages(id: string, ttl: number): Promise<void>;
  /** Claims a request id for a scope. "claimed" means the caller should do the work and then putIdem. */
  claimRequest(scope: string, requestId: string, ttl: number): Promise<"claimed" | "pending" | { response: unknown }>;
  /** Releases an unfinished claim so a failed request can be retried. */
  dropRequestClaim(scope: string, requestId: string): Promise<void>;
  addMessages(id: string, msgs: Message[]): Promise<void>;
  listMessages(id: string): Promise<Message[]>;
  deleteMessages(id: string): Promise<void>;
  /** Deletes a conversation's messages and idempotency snapshots; with keepMeta false also the conversation item. */
  purgeConversation(id: string, opts: { keepMeta: boolean }): Promise<void>;
  getIdem(id: string, requestId: string): Promise<unknown | undefined>;
  putIdem(id: string, requestId: string, response: unknown, ttl: number): Promise<void>;
  putOutcome(o: Outcome): Promise<void>;
  getOutcome(id: string): Promise<Outcome | undefined>;
  listRecords(): Promise<Outcome[]>;
  /** Records and declined outcomes, newest first. */
  listOutcomes(): Promise<Outcome[]>;
  /** Review update only if current reviewStatus === 'pending' (prevents double review). */
  reviewOutcome(id: string, patch: Partial<Outcome>): Promise<Outcome | undefined>;
}

export class MemoryStore implements Store {
  profiles = new Map<string, ProducerProfile>();
  convs = new Map<string, Conversation>();
  msgs = new Map<string, Message[]>();
  idem = new Map<string, unknown>();
  outcomes = new Map<string, Outcome>();
  async getProfileBySub(sub: string) { return this.profiles.get(sub); }
  async putConversation(c: Conversation) { this.convs.set(c.conversationId, structuredClone(c)); }
  async getConversation(id: string) { const c = this.convs.get(id); return c && structuredClone(c); }
  async findActiveByOwner(sub: string) {
    const id = this.current.get(sub);
    const c = id ? this.convs.get(id) : undefined;
    return c && c.status === "active" ? structuredClone(c) : undefined;
  }
  async updateConversation(id: string, v: number, patch: Partial<Conversation>) {
    const c = this.convs.get(id);
    if (!c || c.version !== v) return undefined;
    const n = { ...c, ...patch, version: v + 1 };
    this.convs.set(id, n);
    return structuredClone(n);
  }
  async acquireLock(id: string, token: string, now: number, ttl: number) {
    const c = this.convs.get(id);
    if (!c || (c.lockExpires && c.lockExpires > now)) return false;
    c.lockToken = token; c.lockExpires = now + ttl;
    return true;
  }
  async releaseLock(id: string, token: string) {
    const c = this.convs.get(id);
    if (c && c.lockToken === token) { delete c.lockToken; delete c.lockExpires; }
  }
  current = new Map<string, string>();
  claims = new Set<string>();
  async listByOwner(sub: string) {
    return [...this.convs.values()].filter((c) => c.ownerSub === sub).sort((a, b) => b.createdAt.localeCompare(a.createdAt)).map((c) => structuredClone(c));
  }
  async setCurrent(sub: string, id: string) { this.current.set(sub, id); }
  async clearCurrent(sub: string, id: string) { if (this.current.get(sub) === id) this.current.delete(sub); }
  async retainMessages() { /* in-memory: no expiry */ }
  async claimRequest(scope: string, requestId: string) {
    const k = `${scope}#${requestId}`;
    if (this.idem.has(k)) return { response: this.idem.get(k) };
    if (this.claims.has(k)) return "pending" as const;
    this.claims.add(k); return "claimed" as const;
  }
  async dropRequestClaim(scope: string, requestId: string) { this.claims.delete(`${scope}#${requestId}`); }
  async addMessages(id: string, m: Message[]) { this.msgs.set(id, [...(this.msgs.get(id) ?? []), ...m]); }
  async listMessages(id: string) { return [...(this.msgs.get(id) ?? [])]; }
  async deleteMessages(id: string) { this.msgs.delete(id); }
  async purgeConversation(id: string, opts: { keepMeta: boolean }) {
    this.msgs.delete(id);
    for (const k of [...this.idem.keys()]) if (k.startsWith(`${id}#`)) this.idem.delete(k);
    if (!opts.keepMeta) this.convs.delete(id);
  }
  async getIdem(id: string, r: string) { return this.idem.get(`${id}#${r}`); }
  async putIdem(id: string, r: string, resp: unknown) { this.idem.set(`${id}#${r}`, resp); }
  async putOutcome(o: Outcome) { this.outcomes.set(o.outcomeId, structuredClone(o)); }
  async getOutcome(id: string) { const o = this.outcomes.get(id); return o && structuredClone(o); }
  async listRecords() { return [...this.outcomes.values()].filter((o) => o.kind === "record"); }
  async listOutcomes() { return [...this.outcomes.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).map((o) => structuredClone(o)); }
  async reviewOutcome(id: string, patch: Partial<Outcome>) {
    const o = this.outcomes.get(id);
    if (!o || o.kind !== "record" || o.reviewStatus !== "pending") return undefined;
    const n = { ...o, ...patch }; this.outcomes.set(id, n); return structuredClone(n);
  }
}

import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";
import type { Language } from "./contracts";

export interface AgentTurnRequest {
  context: {
    conversationId: string;
    language: Language;
    mode: "intake" | "guidance" | "ask";
    allowPlayback: boolean;
    forcePlayback?: boolean;
    producer: { producerId: string; entityType: string; location: string; crop: string };
    confirmedAccount?: string | null;
  };
  messages: { role: "user" | "assistant"; text: string }[];
}
export interface AgentTurnResponse {
  reply: string;
  phase: "intake" | "playback" | "guidance" | "answer";
  playbackSummary?: string | null;
  title?: string | null;
  summaryOriginal?: string | null;
  summaryEn?: string | null;
  challengeTags?: string[];
  piiFlag: boolean;
  piiTypes: string[];
  evidence: { status: "unavailable"; note?: string };
  language: Language;
}
export interface MatchRequest {
  task: "match"; language: Language; producer: { producerId: string; entityType: string; location: string; crop: string };
  account: string; tags: string[];
  candidates: { caseId: string; challenge: string; action: string | null; result: string | null; tags: string[]; sameOrganization: boolean; sameCountry: boolean }[];
}
export interface MatchResponse { matches: { caseId: string; fit: "strong" | "partial"; reason: string }[]; considered: number }
export interface AgentClient {
  turn(req: AgentTurnRequest, runtimeSessionId: string, userId: string): Promise<AgentTurnResponse>;
  /** Ranks application-selected candidate cases against the producer's account. Optional so callers without it fall back to rule-based ranking. */
  match?(req: MatchRequest, runtimeSessionId: string, userId: string): Promise<MatchResponse>;
}

/** The runtime session id is derived from the application conversation id (>= 33 chars required). */
export const runtimeSessionIdFor = (conversationId: string) => `ftusa-conv-${conversationId}`;

export class AgentCoreClient implements AgentClient {
  private c = new BedrockAgentCoreClient({});
  constructor(private runtimeArn: string) {}
  async match(req: MatchRequest, runtimeSessionId: string, userId: string): Promise<MatchResponse> {
    const out = await this.c.send(new InvokeAgentRuntimeCommand({ agentRuntimeArn: this.runtimeArn, runtimeSessionId, runtimeUserId: userId,
      contentType: "application/json", accept: "application/json", payload: new TextEncoder().encode(JSON.stringify(req)) }));
    const parsed = JSON.parse(await out.response!.transformToString());
    if (!Array.isArray(parsed?.matches)) throw new Error("agent_bad_response");
    return parsed as MatchResponse;
  }
  async turn(req: AgentTurnRequest, runtimeSessionId: string, userId: string): Promise<AgentTurnResponse> {
    const out = await this.c.send(new InvokeAgentRuntimeCommand({
      agentRuntimeArn: this.runtimeArn,
      runtimeSessionId,
      runtimeUserId: userId,
      contentType: "application/json",
      accept: "application/json",
      payload: new TextEncoder().encode(JSON.stringify(req)),
    }));
    const text = await out.response!.transformToString();
    const parsed = JSON.parse(text);
    if (typeof parsed?.reply !== "string" || !["intake", "playback", "guidance", "answer"].includes(parsed?.phase)) {
      throw new Error("agent_bad_response");
    }
    return parsed as AgentTurnResponse;
  }
}

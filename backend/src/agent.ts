import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";
import type { Language } from "./contracts";

export interface AgentTurnRequest {
  context: {
    conversationId: string;
    language: Language;
    mode: "intake" | "guidance" | "ask";
    allowPlayback: boolean;
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
  piiFlag: boolean;
  piiTypes: string[];
  evidence: { status: "unavailable"; note?: string };
  language: Language;
}
export interface AgentClient { turn(req: AgentTurnRequest, runtimeSessionId: string, userId: string): Promise<AgentTurnResponse> }

/** The runtime session id is derived from the application conversation id (>= 33 chars required). */
export const runtimeSessionIdFor = (conversationId: string) => `ftusa-conv-${conversationId}`;

export class AgentCoreClient implements AgentClient {
  private c = new BedrockAgentCoreClient({});
  constructor(private runtimeArn: string) {}
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

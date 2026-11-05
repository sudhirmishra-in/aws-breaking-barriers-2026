import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { ZodError } from "zod";
import { AgentCoreClient } from "./agent";
import { CorrectionCreateReq, CorrectionDecisionReq, FinalizeReq, FeedbackReq, IssueEventReq, IssueLinkReq, SetLanguageReq, PeerQuery, ReconfirmReq, SharingUpdateReq, AskReq, ReviewPatchReq, ReviewProducersQuery, TranscribeReq, ConsentReq, CreateConversationReq, EndReq, PlaybackReq, ReviewUpdateReq, SubmitMessageReq } from "./contracts";
import { DdbStore } from "./ddbStore";
import { BedrockAgentRuntimeClient, RetrieveCommand } from "@aws-sdk/client-bedrock-agent-runtime";
import { KnowledgeBaseRetriever, LocalProjectRetriever, type ProjectRetriever } from "./projectEvidence";
import { AgentCoreMemory } from "./memory";
import { DdbFacts } from "./externalFacts";
import { emf } from "./metrics";
import { PollySpeaker } from "./speech";
import { TranscribeStreamingTranscriber } from "./transcribe";
import { ApiError, invalid, notFound, unauthorized } from "./errors";
import { requireReviewer, type Principal } from "./service";
import { ServiceV2 } from "./serviceV2";

/** Claims arrive from the API Gateway JWT authorizer (signature, issuer, audience, exp already checked). We re-check use and client. */
export function principalFromEvent(e: APIGatewayProxyEventV2, expected: { clientIds: string[]; issuer: string }, nowSec = Math.floor(Date.now() / 1000)): Principal {
  const claims = (e.requestContext as any)?.authorizer?.jwt?.claims as Record<string, string> | undefined;
  if (!claims?.sub) throw unauthorized();
  if (claims.token_use !== "access") throw unauthorized(); // ID tokens are not accepted for API use
  if (!expected.clientIds.includes(claims.client_id) || claims.iss !== expected.issuer) throw unauthorized();
  if (!claims.exp || Number(claims.exp) <= nowSec) throw unauthorized();
  const raw = claims["cognito:groups"] ?? "";
  const groups = raw.replace(/^\[|\]$/g, "").split(/[\s,]+/).filter(Boolean);
  return { sub: claims.sub, groups, name: claims.username ?? claims["cognito:username"] ?? undefined };
}

const json = (status: number, body: unknown, requestId: string): APIGatewayProxyStructuredResultV2 => ({
  statusCode: status,
  headers: { "content-type": "application/json", "cache-control": "no-store", "x-request-id": requestId },
  body: JSON.stringify(body),
});

export async function route(svc: ServiceV2, p: Principal, method: string, path: string, body: unknown, query: Record<string, string | undefined> = {}) {
  const seg = path.replace(/^\/+|\/+$/g, "").split("/");
  if (seg[0] === "api") seg.shift();
  const [r0, r1, r2] = seg;
  if (method === "GET" && r0 === "me") return svc.me(p);
  if (method === "GET" && r0 === "overview") return svc.overview(p);
  if (method === "GET" && r0 === "producer-info") return svc.producerInformation(p);
  if (method === "GET" && r0 === "related" && r1) return svc.relatedCases(p, r1);
  if (method === "GET" && r0 === "evidence" && r1) return svc.evidence(p, r1);
  if (r0 === "issues") {
    if (method === "GET" && !r1) return svc.listIssues(p);
    if (method === "GET" && r1 === "for" && r2) return svc.issueContext(p, r2);
    if (method === "POST" && r1 && r2 === "events") return svc.addIssueEvent(p, r1, IssueEventReq.parse(body));
  }
  if (method === "POST" && r0 === "memory" && r1 === "reconcile") return svc.reconcileMemory(p);
  if (r0 === "corrections") {
    if (method === "POST" && !r1) return svc.createCorrection(p, CorrectionCreateReq.parse(body));
    if (method === "GET" && !r1) return svc.listMyCorrections(p);
  }
  if (r0 === "peers" && r1 === "summaries") {
    if (method === "GET" && !r2) return svc.peerSummaries(p, PeerQuery.parse(query).scope ?? "organization");
    if (method === "GET" && r2) return svc.peerCase(p, decodeURIComponent(r2));
  }
  // Reviewer routes check the role before validating input, so a producer always gets 403, never a 400 that hints at the schema.
  if (r0 === "review" || r0 === "records") requireReviewer(p);
  if (r0 === "review") {
    if (method === "GET" && r1 === "corrections" && !r2) return svc.reviewCorrections(p, query.status);
    if (method === "POST" && r1 === "corrections" && r2 && seg[3] === "decision") return svc.decideCorrection(p, r2, CorrectionDecisionReq.parse(body));
    if (method === "GET" && r1 === "stats" && !r2) return svc.reviewStats(p);
    if (method === "GET" && r1 === "producers" && !r2) return svc.reviewProducers(p, ReviewProducersQuery.parse(query));
    if (method === "GET" && r1 === "producers" && r2 && seg[3] === "records" && !seg[4]) return svc.reviewProducerRecords(p, r2);
    if (method === "GET" && r1 === "producers" && r2 && seg[3] === "related" && !seg[4]) return svc.reviewRelated(p, r2);
  }
  if (r0 === "records" && r1 && !r2) {
    if (method === "GET") return svc.getRecord(p, r1);
    if (method === "PATCH") return svc.patchRecord(p, r1, ReviewPatchReq.parse(body));
  }
  if (r0 === "records" && r1 && r2 === "publish" && method === "POST") return svc.retryPublication(p, r1);
  if (method === "POST" && r0 === "transcribe") { const q = TranscribeReq.parse(body); return svc.transcribe(p, q.language, q.audio); }
  if (method === "POST" && r0 === "ask") { const q = AskReq.parse(body); return svc.ask(p, q.text, q.language); }
  if (r0 === "conversations") {
    if (method === "GET" && !r1) return svc.listConversations(p);
    if (method === "POST" && !r1) { const q = CreateConversationReq.parse(body); return svc.create(p, q.language, q.requestId, q.referenceCaseId); }
    if (method === "GET" && r1 === "current") return svc.getCurrent(p);
    if (r1 && method === "GET" && !r2) return svc.getConversation(p, r1);
    if (r1 && method === "DELETE" && !r2) return svc.deleteConversation(p, r1);
    if (r1 && method === "POST" && r2 === "messages" && seg[3] && seg[4] === "speech" && !seg[5]) {
      const seq = Number(seg[3]); if (!Number.isInteger(seq) || seq < 1) throw invalid("Invalid message number.");
      return svc.speech(p, r1, seq);
    }
    if (r1 && method === "POST" && r2 === "messages" && !seg[3]) { const q = SubmitMessageReq.parse(body); return svc.message(p, r1, q.requestId, q.text); }
    if (r1 && method === "POST" && r2 === "playback") { return svc.playback(p, r1, PlaybackReq.parse(body)); }
    if (r1 && method === "POST" && r2 === "consent") { const q = ConsentReq.parse(body); return svc.consent(p, r1, q.requestId, q.storeSummary); }
    if (r1 && method === "POST" && r2 === "finalize") { const q = FinalizeReq.parse(body); return svc.finalize(p, r1, q); }
    if (r1 && method === "POST" && r2 === "language") { const q = SetLanguageReq.parse(body); return svc.setConversationLanguage(p, r1, q.requestId, q.language); }
    if (r1 && method === "POST" && r2 === "issue-link") { const q = IssueLinkReq.parse(body); return svc.linkIssue(p, r1, q); }
    if (r1 && method === "POST" && r2 === "feedback") return svc.feedback(p, r1, FeedbackReq.parse(body));
    if (r1 && method === "POST" && r2 === "sharing") return svc.updateSharing(p, r1, SharingUpdateReq.parse(body));
    if (r1 && method === "POST" && r2 === "reconfirm") return svc.reconfirm(p, r1, ReconfirmReq.parse(body));
    if (r1 && method === "POST" && r2 === "deletion-request") return svc.requestDeletion(p, r1);
    if (r1 && method === "POST" && r2 === "end") { const q = EndReq.parse(body); return svc.end(p, r1, q.requestId); }
  }
  if (r0 === "reviews") {
    if (method === "GET" && !r1) return svc.listReviews(p);
    if (method === "GET" && r1) return svc.getReview(p, r1);
    if (method === "PUT" && r1) return svc.updateReview(p, r1, ReviewUpdateReq.parse(body));
  }
  throw notFound();
}

/** Knowledge Base retrieval when one is provisioned and ingested; otherwise the deterministic local retriever. A KB failure at query time also falls back to local. */
function projectRetriever(): ProjectRetriever {
  const local = new LocalProjectRetriever();
  const kb = process.env.KNOWLEDGE_BASE_ID && new KnowledgeBaseRetriever(process.env.KNOWLEDGE_BASE_ID, new BedrockAgentRuntimeClient({}) as never, (i) => new RetrieveCommand(i as never));
  return kb ? { search: async (q) => { try { const r = await kb.search(q); return r.length ? r : local.search(q); } catch { return local.search(q); } } } : local;
}

let svc: ServiceV2 | undefined;
const getSvc = () => (svc ??= new ServiceV2({
  store: new DdbStore(process.env.CONVERSATIONS_TABLE!, process.env.OUTCOMES_TABLE!),
  agent: new AgentCoreClient(process.env.AGENT_RUNTIME_ARN!),
  transcriber: new TranscribeStreamingTranscriber(),
  speaker: new PollySpeaker(),
  projects: projectRetriever(),
  facts: process.env.ENVIRONMENTAL_FACTS_TABLE ? new DdbFacts(process.env.ENVIRONMENTAL_FACTS_TABLE) : undefined,
  memory: process.env.MEMORY_PERSONAL_ID && process.env.MEMORY_ORG_ID && process.env.MEMORY_PUBLISHED_ID
    ? new AgentCoreMemory({ personal: process.env.MEMORY_PERSONAL_ID, organization: process.env.MEMORY_ORG_ID, published: process.env.MEMORY_PUBLISHED_ID }) : undefined,
  metric: emf,
  log: (e) => console.log(JSON.stringify({ level: "info", ...e })), // structured; never message text
}));

export async function handler(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  const requestId = event.requestContext.requestId;
  try {
    const p = principalFromEvent(event, { clientIds: (process.env.ALLOWED_CLIENT_IDS ?? process.env.USER_POOL_CLIENT_ID!).split(",").filter(Boolean), issuer: process.env.ISSUER! });
    let body: unknown;
    if (event.body) { try { body = JSON.parse(event.isBase64Encoded ? Buffer.from(event.body, "base64").toString() : event.body); } catch { throw invalid("Body must be JSON."); } }
    const out = await route(getSvc(), p, event.requestContext.http.method, event.rawPath, body, event.queryStringParameters ?? {});
    return json(200, out, requestId);
  } catch (e) {
    if (e instanceof ZodError) return json(400, { error: { code: "validation_error", message: "Invalid request.", retryable: false, requestId } }, requestId);
    if (e instanceof ApiError) return json(e.status, { error: { code: e.code, message: e.message, retryable: e.retryable, requestId } }, requestId);
    console.log(JSON.stringify({ level: "error", event: "unhandled", requestId, errorName: (e as Error)?.name }));
    return json(500, { error: { code: "internal_error", message: "Something went wrong.", retryable: true, requestId } }, requestId);
  }
}

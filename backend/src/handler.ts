import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { ZodError } from "zod";
import { AgentCoreClient } from "./agent";
import { AskReq, TranscribeReq, ConsentReq, CreateConversationReq, EndReq, PlaybackReq, ReviewUpdateReq, SubmitMessageReq } from "./contracts";
import { DdbStore } from "./ddbStore";
import { PollySpeaker } from "./speech";
import { TranscribeStreamingTranscriber } from "./transcribe";
import { ApiError, invalid, notFound, unauthorized } from "./errors";
import { Service, type Principal } from "./service";

/** Claims arrive from the API Gateway JWT authorizer (signature, issuer, audience, exp already checked). We re-check use and client. */
export function principalFromEvent(e: APIGatewayProxyEventV2, expected: { clientIds: string[]; issuer: string }, nowSec = Math.floor(Date.now() / 1000)): Principal {
  const claims = (e.requestContext as any)?.authorizer?.jwt?.claims as Record<string, string> | undefined;
  if (!claims?.sub) throw unauthorized();
  if (claims.token_use !== "access") throw unauthorized(); // ID tokens are not accepted for API use
  if (!expected.clientIds.includes(claims.client_id) || claims.iss !== expected.issuer) throw unauthorized();
  if (!claims.exp || Number(claims.exp) <= nowSec) throw unauthorized();
  const raw = claims["cognito:groups"] ?? "";
  const groups = raw.replace(/^\[|\]$/g, "").split(/[\s,]+/).filter(Boolean);
  return { sub: claims.sub, groups };
}

const json = (status: number, body: unknown, requestId: string): APIGatewayProxyStructuredResultV2 => ({
  statusCode: status,
  headers: { "content-type": "application/json", "cache-control": "no-store", "x-request-id": requestId },
  body: JSON.stringify(body),
});

export async function route(svc: Service, p: Principal, method: string, path: string, body: unknown) {
  const seg = path.replace(/^\/+|\/+$/g, "").split("/");
  if (seg[0] === "api") seg.shift();
  const [r0, r1, r2] = seg;
  if (method === "GET" && r0 === "me") return svc.me(p);
  if (method === "GET" && r0 === "overview") return svc.overview(p);
  if (method === "POST" && r0 === "transcribe") { const q = TranscribeReq.parse(body); return svc.transcribe(p, q.language, q.audio); }
  if (method === "POST" && r0 === "ask") { const q = AskReq.parse(body); return svc.ask(p, q.text, q.language); }
  if (r0 === "conversations") {
    if (method === "GET" && !r1) return svc.listConversations(p);
    if (method === "POST" && !r1) { const q = CreateConversationReq.parse(body); return svc.create(p, q.language, q.requestId); }
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
    if (r1 && method === "POST" && r2 === "end") { const q = EndReq.parse(body); return svc.end(p, r1, q.requestId); }
  }
  if (r0 === "reviews") {
    if (method === "GET" && !r1) return svc.listReviews(p);
    if (method === "GET" && r1) return svc.getReview(p, r1);
    if (method === "PUT" && r1) return svc.updateReview(p, r1, ReviewUpdateReq.parse(body));
  }
  throw notFound();
}

let svc: Service | undefined;
const getSvc = () => (svc ??= new Service({
  store: new DdbStore(process.env.CONVERSATIONS_TABLE!, process.env.OUTCOMES_TABLE!),
  agent: new AgentCoreClient(process.env.AGENT_RUNTIME_ARN!),
  transcriber: new TranscribeStreamingTranscriber(),
  speaker: new PollySpeaker(),
  log: (e) => console.log(JSON.stringify({ level: "info", ...e })), // structured; never message text
}));

export async function handler(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  const requestId = event.requestContext.requestId;
  try {
    const p = principalFromEvent(event, { clientIds: (process.env.ALLOWED_CLIENT_IDS ?? process.env.USER_POOL_CLIENT_ID!).split(",").filter(Boolean), issuer: process.env.ISSUER! });
    let body: unknown;
    if (event.body) { try { body = JSON.parse(event.isBase64Encoded ? Buffer.from(event.body, "base64").toString() : event.body); } catch { throw invalid("Body must be JSON."); } }
    const out = await route(getSvc(), p, event.requestContext.http.method, event.rawPath, body);
    return json(200, out, requestId);
  } catch (e) {
    if (e instanceof ZodError) return json(400, { error: { code: "validation_error", message: "Invalid request.", retryable: false, requestId } }, requestId);
    if (e instanceof ApiError) return json(e.status, { error: { code: e.code, message: e.message, retryable: e.retryable, requestId } }, requestId);
    console.log(JSON.stringify({ level: "error", event: "unhandled", requestId, errorName: (e as Error)?.name }));
    return json(500, { error: { code: "internal_error", message: "Something went wrong.", retryable: true, requestId } }, requestId);
  }
}

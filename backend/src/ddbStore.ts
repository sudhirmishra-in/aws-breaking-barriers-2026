import { DynamoDBClient, ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, QueryCommand, UpdateCommand, DeleteCommand, BatchWriteCommand } from "@aws-sdk/lib-dynamodb";
import type { Conversation, Message, Outcome, ProducerProfile } from "./contracts";
import type { Store } from "./store";

const META = "META";
const isCCF = (e: unknown) => e instanceof ConditionalCheckFailedException;

export class DdbStore implements Store {
  private d: DynamoDBDocumentClient;
  constructor(private convTable: string, private outTable: string, client = new DynamoDBClient({})) {
    this.d = DynamoDBDocumentClient.from(client, { marshallOptions: { removeUndefinedValues: true } });
  }
  async getProfileBySub(sub: string): Promise<ProducerProfile | undefined> {
    const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key: { pk: `PROFILE#${sub}`, sk: META } }));
    return r.Item?.profile as ProducerProfile | undefined;
  }
  async putConversation(c: Conversation) {
    await this.d.send(new PutCommand({ TableName: this.convTable, Item: { pk: `CONV#${c.conversationId}`, sk: META, ownerSub: c.ownerSub, createdAt: c.createdAt, convStatus: c.status, ttl: c.expiresAt, data: c },
      ConditionExpression: "attribute_not_exists(pk)" }));
  }
  async getConversation(id: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key: { pk: `CONV#${id}`, sk: META }, ConsistentRead: true }));
    return r.Item?.data as Conversation | undefined;
  }
  async findActiveByOwner(sub: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key: { pk: `ACTIVE#${sub}`, sk: META }, ConsistentRead: true }));
    const id = r.Item?.conversationId as string | undefined;
    const c = id ? await this.getConversation(id) : undefined;
    return c && c.status === "active" ? c : undefined;
  }
  async updateConversation(id: string, v: number, patch: Partial<Conversation>) {
    // Whole-document replace guarded by version; lock fields are managed separately on the item root.
    const cur = await this.getConversation(id);
    if (!cur || cur.version !== v) return undefined;
    const next: Conversation = { ...cur, ...patch, version: v + 1 };
    try {
      await this.d.send(new UpdateCommand({ TableName: this.convTable, Key: { pk: `CONV#${id}`, sk: META },
        UpdateExpression: "SET #data = :n, convStatus = :s, #ttl = :t", ConditionExpression: "#data.#v = :v",
        ExpressionAttributeNames: { "#data": "data", "#v": "version", "#ttl": "ttl" },
        ExpressionAttributeValues: { ":n": next, ":v": v, ":s": next.status, ":t": next.expiresAt } }));
      return next;
    } catch (e) { if (isCCF(e)) return undefined; throw e; }
  }
  async acquireLock(id: string, token: string, now: number, ttl: number) {
    try {
      await this.d.send(new UpdateCommand({ TableName: this.convTable, Key: { pk: `CONV#${id}`, sk: META },
        UpdateExpression: "SET lockToken = :t, lockExpires = :e",
        ConditionExpression: "attribute_exists(pk) AND (attribute_not_exists(lockExpires) OR lockExpires < :n)",
        ExpressionAttributeValues: { ":t": token, ":e": now + ttl, ":n": now } }));
      return true;
    } catch (e) { if (isCCF(e)) return false; throw e; }
  }
  async releaseLock(id: string, token: string) {
    try {
      await this.d.send(new UpdateCommand({ TableName: this.convTable, Key: { pk: `CONV#${id}`, sk: META },
        UpdateExpression: "REMOVE lockToken, lockExpires", ConditionExpression: "lockToken = :t", ExpressionAttributeValues: { ":t": token } }));
    } catch (e) { if (!isCCF(e)) throw e; }
  }
  async listByOwner(sub: string) {
    const r = await this.d.send(new QueryCommand({ TableName: this.convTable, IndexName: "owner-index",
      KeyConditionExpression: "ownerSub = :o", ExpressionAttributeValues: { ":o": sub }, ScanIndexForward: false, Limit: 100 }));
    return (r.Items ?? []).filter((i) => i.sk === META && i.data).map((i) => i.data as Conversation);
  }
  async setCurrent(sub: string, conversationId: string, nowMs: number) {
    await this.d.send(new PutCommand({ TableName: this.convTable, Item: { pk: `ACTIVE#${sub}`, sk: META, conversationId, ttl: Math.floor(nowMs / 1000) + 8 * 86400 } }));
  }
  async clearCurrent(sub: string, conversationId: string) {
    try {
      await this.d.send(new DeleteCommand({ TableName: this.convTable, Key: { pk: `ACTIVE#${sub}`, sk: META }, ConditionExpression: "conversationId = :c", ExpressionAttributeValues: { ":c": conversationId } }));
    } catch (e) { if (!isCCF(e)) throw e; }
  }
  async retainMessages(id: string, ttl: number) {
    const r = await this.d.send(new QueryCommand({ TableName: this.convTable, ConsistentRead: true, ProjectionExpression: "pk, sk",
      KeyConditionExpression: "pk = :p AND begins_with(sk, :m)", ExpressionAttributeValues: { ":p": `CONV#${id}`, ":m": "MSG#" } }));
    for (const k of r.Items ?? []) {
      await this.d.send(new UpdateCommand({ TableName: this.convTable, Key: { pk: k.pk, sk: k.sk }, UpdateExpression: "SET #t = :t", ExpressionAttributeNames: { "#t": "ttl" }, ExpressionAttributeValues: { ":t": ttl } }));
    }
  }
  async claimRequest(scope: string, requestId: string, ttl: number): Promise<"claimed" | "pending" | { response: unknown }> {
    const Key = { pk: `CONV#${scope}`, sk: `REQ#${requestId}` };
    try {
      await this.d.send(new PutCommand({ TableName: this.convTable, Item: { ...Key, pending: true, ttl }, ConditionExpression: "attribute_not_exists(pk)" }));
      return "claimed";
    } catch (e) {
      if (!isCCF(e)) throw e;
      const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key, ConsistentRead: true }));
      return r.Item && "response" in r.Item ? { response: r.Item.response } : "pending";
    }
  }
  async addMessages(id: string, msgs: Message[]) {
    for (const m of msgs) {
      await this.d.send(new PutCommand({ TableName: this.convTable, Item: { pk: `CONV#${id}`, sk: `MSG#${String(m.seq).padStart(6, "0")}`, ttl: Math.floor(Date.now() / 1000) + 8 * 86400, ...m } }));
    }
  }
  async listMessages(id: string) {
    const r = await this.d.send(new QueryCommand({ TableName: this.convTable, ConsistentRead: true,
      KeyConditionExpression: "pk = :p AND begins_with(sk, :m)", ExpressionAttributeValues: { ":p": `CONV#${id}`, ":m": "MSG#" } }));
    return (r.Items ?? []).map((i) => ({ seq: i.seq, role: i.role, text: i.text, at: i.at, stage: i.stage }) as Message);
  }
  async deleteMessages(id: string) {
    const r = await this.d.send(new QueryCommand({ TableName: this.convTable, ConsistentRead: true, ProjectionExpression: "pk, sk",
      KeyConditionExpression: "pk = :p AND begins_with(sk, :m)", ExpressionAttributeValues: { ":p": `CONV#${id}`, ":m": "MSG#" } }));
    const keys = r.Items ?? [];
    for (let i = 0; i < keys.length; i += 25) {
      await this.d.send(new BatchWriteCommand({ RequestItems: { [this.convTable]: keys.slice(i, i + 25).map((k) => ({ DeleteRequest: { Key: { pk: k.pk, sk: k.sk } } })) } }));
    }
  }
  async getIdem(id: string, requestId: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key: { pk: `CONV#${id}`, sk: `REQ#${requestId}` }, ConsistentRead: true }));
    return r.Item && "response" in r.Item ? r.Item.response : undefined;
  }
  async putIdem(id: string, requestId: string, response: unknown, ttl: number) {
    await this.d.send(new PutCommand({ TableName: this.convTable, Item: { pk: `CONV#${id}`, sk: `REQ#${requestId}`, response, ttl } }));
  }
  async dropRequestClaim(scope: string, requestId: string) {
    await this.d.send(new DeleteCommand({ TableName: this.convTable, Key: { pk: `CONV#${scope}`, sk: `REQ#${requestId}` }, ConditionExpression: "attribute_exists(pending)" })).catch((e) => { if (!isCCF(e)) throw e; });
  }
  async putOutcome(o: Outcome) {
    // Deterministic outcomeId per conversation => a retry cannot create a second final record.
    try {
      await this.d.send(new PutCommand({ TableName: this.outTable, Item: { ...o, gsiKind: o.kind }, ConditionExpression: "attribute_not_exists(outcomeId)" }));
    } catch (e) { if (!isCCF(e)) throw e; }
  }
  async getOutcome(id: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.outTable, Key: { outcomeId: id }, ConsistentRead: true }));
    return r.Item as Outcome | undefined;
  }
  async listRecords() {
    const r = await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "kind-index",
      KeyConditionExpression: "gsiKind = :k", ExpressionAttributeValues: { ":k": "record" }, ScanIndexForward: false, Limit: 100 }));
    return (r.Items ?? []) as Outcome[];
  }
  async reviewOutcome(id: string, patch: Partial<Outcome>) {
    const names: Record<string, string> = { "#rs": "reviewStatus" };
    const vals: Record<string, unknown> = { ":pending": "pending" };
    const sets: string[] = [];
    Object.entries(patch).forEach(([k, v], i) => { names[`#f${i}`] = k; vals[`:v${i}`] = v; sets.push(`#f${i} = :v${i}`); });
    try {
      const r = await this.d.send(new UpdateCommand({ TableName: this.outTable, Key: { outcomeId: id }, UpdateExpression: `SET ${sets.join(", ")}`,
        ConditionExpression: "attribute_exists(outcomeId) AND #rs = :pending", ExpressionAttributeNames: names, ExpressionAttributeValues: vals, ReturnValues: "ALL_NEW" }));
      return r.Attributes as Outcome;
    } catch (e) { if (isCCF(e)) return undefined; throw e; }
  }
}


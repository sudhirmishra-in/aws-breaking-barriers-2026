import { DynamoDBClient, ConditionalCheckFailedException } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, QueryCommand, UpdateCommand, DeleteCommand, BatchWriteCommand } from "@aws-sdk/lib-dynamodb";
import type { IssueRecord, Conversation, CorrectionRecord, Message, Organization, Outcome, ProducerProfile, PublicationStatus } from "./contracts";
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
        // expiresAt 0 means "kept until the producer deletes it": the TTL attribute is removed.
        UpdateExpression: next.expiresAt ? "SET #data = :n, convStatus = :s, #ttl = :t" : "SET #data = :n, convStatus = :s REMOVE #ttl",
        ConditionExpression: "#data.#v = :v",
        ExpressionAttributeNames: { "#data": "data", "#v": "version", "#ttl": "ttl" },
        ExpressionAttributeValues: { ":n": next, ":v": v, ":s": next.status, ...(next.expiresAt ? { ":t": next.expiresAt } : {}) } }));
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
  async purgeConversation(id: string, opts: { keepMeta: boolean }) {
    let start: Record<string, unknown> | undefined;
    do {
      const r = await this.d.send(new QueryCommand({ TableName: this.convTable, ConsistentRead: true, ProjectionExpression: "pk, sk", ExclusiveStartKey: start,
        KeyConditionExpression: "pk = :p", ExpressionAttributeValues: { ":p": `CONV#${id}` } }));
      const keys = (r.Items ?? []).filter((k) => opts.keepMeta ? k.sk !== META : true);
      for (let i = 0; i < keys.length; i += 25) {
        await this.d.send(new BatchWriteCommand({ RequestItems: { [this.convTable]: keys.slice(i, i + 25).map((k) => ({ DeleteRequest: { Key: { pk: k.pk, sk: k.sk } } })) } }));
      }
      start = r.LastEvaluatedKey;
    } while (start);
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
  async listOutcomes() {
    const out: Outcome[] = [];
    for (const kind of ["record", "declined"]) {
      let start: Record<string, unknown> | undefined;
      do {
        const r = await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "kind-index", ExclusiveStartKey: start,
          KeyConditionExpression: "gsiKind = :k", ExpressionAttributeValues: { ":k": kind }, ScanIndexForward: false }));
        out.push(...((r.Items ?? []) as Outcome[])); start = r.LastEvaluatedKey;
      } while (start && out.length < 5000);
    }
    return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
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
  // ---- V2 ----------------------------------------------------------------------------------------------------
  async getOrganization(id: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.convTable, Key: { pk: `ORG#${id}`, sk: META } }));
    return r.Item?.org as Organization | undefined;
  }
  async putCorrection(c: CorrectionRecord) {
    try {
      await this.d.send(new PutCommand({ TableName: this.outTable, Item: { ...c, outcomeId: c.correctionId, gsiKind: "correction" }, ConditionExpression: "attribute_not_exists(outcomeId)" }));
      return true;
    } catch (e) { if (isCCF(e)) return false; throw e; }
  }
  async getCorrection(id: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.outTable, Key: { outcomeId: id }, ConsistentRead: true }));
    return r.Item?.gsiKind === "correction" ? (r.Item as unknown as CorrectionRecord) : undefined;
  }
  async listCorrections(f: { organizationId?: string }) {
    const out: CorrectionRecord[] = [];
    let start: Record<string, unknown> | undefined;
    do {
      const r = f.organizationId
        ? await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "org-index", ExclusiveStartKey: start, FilterExpression: "gsiKind = :k",
          KeyConditionExpression: "organizationId = :o", ExpressionAttributeValues: { ":o": f.organizationId, ":k": "correction" }, ScanIndexForward: false }))
        : await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "kind-index", ExclusiveStartKey: start,
          KeyConditionExpression: "gsiKind = :k", ExpressionAttributeValues: { ":k": "correction" }, ScanIndexForward: false }));
      out.push(...((r.Items ?? []) as unknown as CorrectionRecord[])); start = r.LastEvaluatedKey;
    } while (start && out.length < 2000);
    return out;
  }
  async updateCorrection(id: string, from: CorrectionRecord["status"][], patch: Partial<CorrectionRecord>) {
    const names: Record<string, string> = { "#st": "status" }; const vals: Record<string, unknown> = {}; const sets: string[] = []; const ins: string[] = [];
    Object.entries(patch).forEach(([k, v], i) => { names[`#f${i}`] = k; vals[`:v${i}`] = v; sets.push(`#f${i} = :v${i}`); });
    from.forEach((f, i) => { vals[`:s${i}`] = f; ins.push(`:s${i}`); });
    try {
      const r = await this.d.send(new UpdateCommand({ TableName: this.outTable, Key: { outcomeId: id }, UpdateExpression: `SET ${sets.join(", ")}`,
        ConditionExpression: `attribute_exists(outcomeId) AND gsiKind = :corr AND #st IN (${ins.join(", ")})`, ExpressionAttributeNames: names,
        ExpressionAttributeValues: { ...vals, ":corr": "correction" }, ReturnValues: "ALL_NEW" }));
      return r.Attributes as unknown as CorrectionRecord;
    } catch (e) { if (isCCF(e)) return undefined; throw e; }
  }
  async listRecordsByOrganization(orgId: string) {
    const out: Outcome[] = []; let start: Record<string, unknown> | undefined;
    do {
      const r = await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "org-index", ExclusiveStartKey: start, FilterExpression: "gsiKind = :k",
        KeyConditionExpression: "organizationId = :o", ExpressionAttributeValues: { ":o": orgId, ":k": "record" }, ScanIndexForward: false }));
      out.push(...((r.Items ?? []) as Outcome[])); start = r.LastEvaluatedKey;
    } while (start && out.length < 2000);
    return out;
  }
  async listPublishedRecords() {
    const out: Outcome[] = []; let start: Record<string, unknown> | undefined;
    do {
      const r = await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "kind-index", ExclusiveStartKey: start, FilterExpression: "publicationStatus = :p",
        KeyConditionExpression: "gsiKind = :k", ExpressionAttributeValues: { ":k": "record", ":p": "published" }, ScanIndexForward: false }));
      out.push(...((r.Items ?? []) as Outcome[])); start = r.LastEvaluatedKey;
    } while (start && out.length < 2000);
    return out;
  }
  async updateOutcome(id: string, from: PublicationStatus[] | null, patch: Partial<Outcome>) {
    const names: Record<string, string> = from ? { "#ps": "publicationStatus" } : {}; // DynamoDB rejects names that no expression uses
    const vals: Record<string, unknown> = {}; const sets: string[] = []; const ins: string[] = [];
    Object.entries(patch).forEach(([k, v], i) => { names[`#f${i}`] = k; vals[`:v${i}`] = v; sets.push(`#f${i} = :v${i}`); });
    from?.forEach((f, i) => { vals[`:s${i}`] = f; ins.push(`:s${i}`); });
    // A record created before V2 has no publicationStatus; it reads as "not_shared".
    const cond = from ? `attribute_exists(outcomeId) AND (#ps IN (${ins.join(", ")})${from.includes("not_shared") ? " OR attribute_not_exists(#ps)" : ""})` : "attribute_exists(outcomeId)";
    try {
      const r = await this.d.send(new UpdateCommand({ TableName: this.outTable, Key: { outcomeId: id }, UpdateExpression: `SET ${sets.join(", ")}`,
        ConditionExpression: cond, ExpressionAttributeNames: names, ExpressionAttributeValues: vals, ReturnValues: "ALL_NEW" }));
      return r.Attributes as Outcome;
    } catch (e) { if (isCCF(e)) return undefined; throw e; }
  }
  // ---- issue history ------------------------------------------------------------------------------------------------
  async putIssue(i: IssueRecord) {
    try {
      await this.d.send(new PutCommand({ TableName: this.outTable, Item: { outcomeId: i.issueId, gsiKind: "issue", organizationId: i.organizationId, createdAt: i.firstReportedAt, issue: i }, ConditionExpression: "attribute_not_exists(outcomeId)" }));
      return true;
    } catch (e) { if (isCCF(e)) return false; throw e; }
  }
  async getIssue(id: string) {
    const r = await this.d.send(new GetCommand({ TableName: this.outTable, Key: { outcomeId: id }, ConsistentRead: true }));
    return r.Item?.gsiKind === "issue" ? (r.Item.issue as IssueRecord) : undefined;
  }
  async listIssuesByOrganization(orgId: string) {
    const out: IssueRecord[] = []; let start: Record<string, unknown> | undefined;
    do {
      const r = await this.d.send(new QueryCommand({ TableName: this.outTable, IndexName: "org-index", ExclusiveStartKey: start, FilterExpression: "gsiKind = :k",
        KeyConditionExpression: "organizationId = :o", ExpressionAttributeValues: { ":o": orgId, ":k": "issue" }, ScanIndexForward: false }));
      out.push(...((r.Items ?? []).map((x) => x.issue as IssueRecord))); start = r.LastEvaluatedKey;
    } while (start && out.length < 1000);
    return out;
  }
  async updateIssue(next: IssueRecord, expected: number) {
    try {
      await this.d.send(new UpdateCommand({ TableName: this.outTable, Key: { outcomeId: next.issueId }, UpdateExpression: "SET issue = :n",
        ConditionExpression: "gsiKind = :k AND issue.version = :v", ExpressionAttributeValues: { ":n": next, ":k": "issue", ":v": expected } }));
      return true;
    } catch (e) { if (isCCF(e)) return false; throw e; }
  }
}

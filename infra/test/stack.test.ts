// Template assertions on the synthesized stack. No AWS calls.
import { describe, expect, it } from "vitest";
import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { ExchangeStack } from "../lib/exchange-stack";

const app = new cdk.App();
const stack = new ExchangeStack(app, "T", {
  env: { account: "111111111111", region: "us-west-2" }, envName: "test", modelId: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  extraCallbackUrls: ["http://localhost:5173/auth/callback"], extraLogoutUrls: ["http://localhost:5173/"],
  agentZip: "../agent/dist/agent.zip", webDist: "../web/dist", gitSha: "abc123", enableCiClient: true, enableKnowledgeBase: false, knowledgeBaseCards: "../data/v2-synthetic",
});
const t = Template.fromStack(stack);
const kbStack = new ExchangeStack(new cdk.App(), "K", {
  env: { account: "111111111111", region: "us-west-2" }, envName: "test", modelId: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  extraCallbackUrls: ["http://localhost:5173/auth/callback"], extraLogoutUrls: ["http://localhost:5173/"],
  agentZip: "../agent/dist/agent.zip", webDist: "../web/dist", gitSha: "abc123", enableCiClient: true, enableKnowledgeBase: true, knowledgeBaseCards: "../data/v2-synthetic",
});
const kt = Template.fromStack(kbStack);

describe("knowledge base (optional)", () => {
  it("is absent unless enabled", () => { t.resourceCountIs("AWS::Bedrock::KnowledgeBase", 0); t.resourceCountIs("AWS::S3Vectors::VectorBucket", 0); });
  it("uses a managed KB on an S3 Vectors index with a multilingual embedding model, one chunk per card", () => {
    kt.hasResourceProperties("AWS::Bedrock::KnowledgeBase", Match.objectLike({ StorageConfiguration: Match.objectLike({ Type: "S3_VECTORS" }) }));
    kt.hasResourceProperties("AWS::S3Vectors::Index", Match.objectLike({ Dimension: 1024, DistanceMetric: "cosine" }));
    kt.hasResourceProperties("AWS::Bedrock::DataSource", Match.objectLike({ VectorIngestionConfiguration: { ChunkingConfiguration: { ChunkingStrategy: "NONE" } } }));
    expect(JSON.stringify(kt.toJSON())).toContain("amazon.titan-embed-text-v2:0");
  });
  it("the API may only retrieve from that one knowledge base", () => {
    const stmts = Object.values(kt.findResources("AWS::IAM::Policy")).flatMap((r) => (r as { Properties: { PolicyDocument: { Statement: { Action: string | string[]; Resource: unknown }[] } } }).Properties.PolicyDocument.Statement);
    const retr = stmts.filter((x) => [x.Action].flat().includes("bedrock:Retrieve"));
    expect(retr).toHaveLength(1); expect(JSON.stringify(retr[0].Resource)).toContain("knowledge-base/"); expect(retr[0].Resource).not.toBe("*");
  });
});

describe("stack", () => {
  it("uses a public PKCE client without a secret and no password flows", () => {
    t.hasResourceProperties("AWS::Cognito::UserPoolClient", { GenerateSecret: false, AllowedOAuthFlows: ["code"], ExplicitAuthFlows: Match.absent() });
  });
  it("disables self sign-up", () => t.hasResourceProperties("AWS::Cognito::UserPool", { AdminCreateUserConfig: { AllowAdminCreateUserOnly: true } }));
  it("authorises the API with a JWT authorizer", () => t.hasResourceProperties("AWS::ApiGatewayV2::Authorizer", { AuthorizerType: "JWT" }));
  it("guardrail PII filters are detect-only", () => {
    const g = Object.values(t.findResources("AWS::Bedrock::Guardrail"))[0] as any;
    for (const e of g.Properties.SensitiveInformationPolicyConfig.PiiEntitiesConfig) expect([e.Action, e.InputAction, e.OutputAction]).toEqual(["NONE", "NONE", "NONE"]);
  });
  it("runtime is IAM-authorised code zip on python 3.13", () => {
    t.hasResourceProperties("AWS::BedrockAgentCore::Runtime", { ProtocolConfiguration: "HTTP", AgentRuntimeArtifact: { CodeConfiguration: Match.objectLike({ Runtime: "PYTHON_3_13" }) } });
    expect(JSON.stringify(Object.values(t.findResources("AWS::BedrockAgentCore::Runtime"))[0])).not.toContain("AuthorizerConfiguration");
  });
  it("conversations table has the owner history index", () => {
    t.hasResourceProperties("AWS::DynamoDB::GlobalTable", { GlobalSecondaryIndexes: Match.arrayWith([Match.objectLike({ IndexName: "owner-index" })]) });
  });
  it("V2: outcomes table has the organization index and expires records (no indefinite retention)", () => {
    t.hasResourceProperties("AWS::DynamoDB::GlobalTable", { GlobalSecondaryIndexes: Match.arrayWith([Match.objectLike({ IndexName: "org-index" })]), TimeToLiveSpecification: { Enabled: true, AttributeName: "ttl" } });
  });
  it("API role can start Transcribe streaming and nothing broader on Transcribe", () => {
    const pol = JSON.stringify(Object.values(t.findResources("AWS::IAM::Policy")));
    expect(pol).toContain("transcribe:StartStreamTranscription"); expect(pol).not.toContain("transcribe:*");
    expect(pol).toContain("polly:SynthesizeSpeech"); expect(pol).not.toContain("polly:*");
  });
  it("tables are encrypted with a CMK and the web bucket blocks public access", () => {
    t.allResourcesProperties("AWS::DynamoDB::GlobalTable", { SSESpecification: Match.objectLike({ SSEEnabled: true, SSEType: "KMS" }) });
    t.hasResourceProperties("AWS::S3::Bucket", { PublicAccessBlockConfiguration: { BlockPublicAcls: true, RestrictPublicBuckets: true } });
  });
});

import { CiRolesStack } from "../lib/ci-roles-stack";
describe("ci roles with an immutable subject prefix", () => {
  it("uses the supplied prefix for both roles", () => {
    const t2 = Template.fromStack(new CiRolesStack(new cdk.App(), "C2", { env: { account: "111111111111", region: "us-west-2" }, envName: "sandbox", githubRepo: "o/r", deployBranch: "main", createOidcProvider: true, subjectPrefix: "repo:o@1/r@2" }));
    const s = JSON.stringify(t2.toJSON());
    expect(s).toContain("repo:o@1/r@2:environment:sandbox"); expect(s).toContain("repo:o@1/r@2:ref:refs/heads/main"); expect(s).not.toContain("repo:o/r:");
  });
});
describe("ci roles", () => {
  const ci = Template.fromStack(new CiRolesStack(new cdk.App(), "C", { env: { account: "111111111111", region: "us-west-2" }, envName: "sandbox", githubRepo: "o/r", deployBranch: "main", createOidcProvider: true }));
  it("trusts only the named repo, with exact sub conditions and the STS audience", () => {
    const roles = Object.values(ci.findResources("AWS::IAM::Role")) as any[];
    const subs = roles.map((r) => JSON.stringify(r.Properties.AssumeRolePolicyDocument)).filter((x) => x.includes("AssumeRoleWithWebIdentity"));
    expect(subs).toHaveLength(2);
    expect(subs.some((s) => s.includes("repo:o/r:environment:sandbox"))).toBe(true);
    expect(subs.some((s) => s.includes("repo:o/r:ref:refs/heads/main"))).toBe(true);
    for (const s of subs) { expect(s).toContain("sts.amazonaws.com"); expect(s).not.toContain("StringLike"); expect(s).not.toContain("repo:o/r:*"); }
  });
  it("no role carries wildcard admin", () => {
    expect(JSON.stringify(ci.toJSON())).not.toMatch(/"Action":"\*"|"Action":\["\*"\]/);
  });
});

import * as cdk from "aws-cdk-lib";
import { ExchangeStack } from "../lib/exchange-stack";
import { CiRolesStack } from "../lib/ci-roles-stack";

const app = new cdk.App();
const envName = app.node.tryGetContext("envName") ?? "sandbox";
new ExchangeStack(app, `FtusaExchange-${envName}`, {
  // Account comes from the active credentials; region is a parameter (default us-west-2).
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: app.node.tryGetContext("region") ?? process.env.CDK_DEFAULT_REGION ?? "us-west-2" },
  envName,
  modelId: app.node.tryGetContext("modelId") ?? "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  extraCallbackUrls: (app.node.tryGetContext("extraCallbackUrls") ?? "http://localhost:5173/auth/callback").split(","),
  extraLogoutUrls: (app.node.tryGetContext("extraLogoutUrls") ?? "http://localhost:5173/").split(","),
  gitSha: app.node.tryGetContext("gitSha") ?? "local",
  enableCiClient: String(app.node.tryGetContext("enableCiClient") ?? "false") === "true",
  agentZip: app.node.tryGetContext("agentZip") ?? "../agent/dist/agent.zip",
  webDist: app.node.tryGetContext("webDist") ?? "../web/dist",
});

// One-time bootstrap stack (deployed by an administrator): GitHub OIDC provider and least-privilege roles.
new CiRolesStack(app, `FtusaCiRoles-${envName}`, {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: app.node.tryGetContext("region") ?? process.env.CDK_DEFAULT_REGION ?? "us-west-2" },
  envName,
  githubRepo: app.node.tryGetContext("githubRepo") ?? "sudhirmishra-in/aws-breaking-barriers-2026",
  deployBranch: app.node.tryGetContext("deployBranch") ?? "main",
  createOidcProvider: String(app.node.tryGetContext("createOidcProvider") ?? "true") === "true",
});

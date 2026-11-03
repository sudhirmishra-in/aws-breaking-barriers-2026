import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";

export interface CiRolesProps extends cdk.StackProps {
  envName: string;
  githubRepo: string; // owner/name
  deployBranch: string;
  createOidcProvider: boolean; // false if the account already has the GitHub provider
}

/**
 * GitHub Actions OIDC trust. Deployed ONCE by an administrator (not by the pipeline it enables).
 * - deploy role: only jobs that run in the GitHub environment named like this stack's env (protected, approval rules live in GitHub).
 * - smoke role : only jobs running on the deploy branch; narrower, data-plane permissions.
 * Pull-request workflows get no AWS role at all (they run with `contents: read` and no id-token permission).
 */
export class CiRolesStack extends cdk.Stack {
  constructor(scope: Construct, id: string, p: CiRolesProps) {
    super(scope, id, p);
    const host = "token.actions.githubusercontent.com";
    const providerArn = p.createOidcProvider
      ? new iam.OpenIdConnectProvider(this, "GitHubOidc", { url: `https://${host}`, clientIds: ["sts.amazonaws.com"] }).openIdConnectProviderArn
      : `arn:${this.partition}:iam::${this.account}:oidc-provider/${host}`;
    const trust = (sub: string) => new iam.FederatedPrincipal(providerArn, {
      StringEquals: { [`${host}:aud`]: "sts.amazonaws.com", [`${host}:sub`]: sub },
    }, "sts:AssumeRoleWithWebIdentity");
    const stackName = `FtusaExchange-${p.envName}`;
    const a = this.account, r = this.region;

    const deploy = new iam.Role(this, "DeployRole", {
      roleName: `ftusa-gha-deploy-${p.envName}`, maxSessionDuration: cdk.Duration.hours(1),
      assumedBy: trust(`repo:${p.githubRepo}:environment:${p.envName}`),
      description: "GitHub Actions: cdk deploy via CDK bootstrap roles",
    });
    deploy.addToPolicy(new iam.PolicyStatement({ actions: ["sts:AssumeRole"], resources: [`arn:${this.partition}:iam::${a}:role/cdk-hnb659fds-*-role-${a}-${r}`] }));
    deploy.addToPolicy(new iam.PolicyStatement({ actions: ["ssm:GetParameter"], resources: [`arn:${this.partition}:ssm:${r}:${a}:parameter/cdk-bootstrap/hnb659fds/version`] }));
    deploy.addToPolicy(new iam.PolicyStatement({ actions: ["cloudformation:DescribeStacks", "cloudformation:GetTemplate"], resources: [`arn:${this.partition}:cloudformation:${r}:${a}:stack/${stackName}/*`, `arn:${this.partition}:cloudformation:${r}:${a}:stack/CDKToolkit/*`] }));

    const smoke = new iam.Role(this, "SmokeRole", {
      roleName: `ftusa-gha-smoke-${p.envName}`, maxSessionDuration: cdk.Duration.hours(1),
      assumedBy: trust(`repo:${p.githubRepo}:ref:refs/heads/${p.deployBranch}`),
      description: "GitHub Actions: post-deploy smoke tests (synthetic identities only)",
    });
    smoke.addToPolicy(new iam.PolicyStatement({ actions: ["cloudformation:DescribeStacks"], resources: [`arn:${this.partition}:cloudformation:${r}:${a}:stack/${stackName}/*`] }));
    smoke.addToPolicy(new iam.PolicyStatement({
      actions: ["cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword", "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminInitiateAuth", "cognito-idp:AdminDeleteUser", "cognito-idp:AdminGetUser"],
      resources: [`arn:${this.partition}:cognito-idp:${r}:${a}:userpool/*`],
    }));
    const tables = [`ftusa-conversations-${p.envName}`, `ftusa-outcomes-${p.envName}`].map((t) => `arn:${this.partition}:dynamodb:${r}:${a}:table/${t}`);
    smoke.addToPolicy(new iam.PolicyStatement({ actions: ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:Query"], resources: tables }));
    smoke.addToPolicy(new iam.PolicyStatement({ actions: ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], resources: [`arn:${this.partition}:kms:${r}:${a}:key/*`], conditions: { StringEquals: { "kms:ViaService": `dynamodb.${r}.amazonaws.com` } } }));
    smoke.addToPolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeForUser"],
      resources: [`arn:${this.partition}:bedrock-agentcore:${r}:${a}:runtime/ftusa_exchange_${p.envName}*`],
    }));

    new cdk.CfnOutput(this, "DeployRoleArn", { value: deploy.roleArn });
    new cdk.CfnOutput(this, "SmokeRoleArn", { value: smoke.roleArn });
  }
}

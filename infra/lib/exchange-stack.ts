import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as kms from "aws-cdk-lib/aws-kms";
import * as ddb from "aws-cdk-lib/aws-dynamodb";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3assets from "aws-cdk-lib/aws-s3-assets";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as cf from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as nodejs from "aws-cdk-lib/aws-lambda-nodejs";
import * as logs from "aws-cdk-lib/aws-logs";
import * as apigw from "aws-cdk-lib/aws-apigatewayv2";
import * as authorizers from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import * as integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as agentcore from "aws-cdk-lib/aws-bedrockagentcore";

export interface ExchangeProps extends cdk.StackProps {
  envName: string;
  modelId: string; // Bedrock inference profile or model id; availability is account/region dependent.
  extraCallbackUrls: string[];
  extraLogoutUrls: string[];
  agentZip: string;
  webDist: string;
  gitSha: string; // recorded on the runtime, stack tag and output so a deploy can be tied to a commit
  enableCiClient: boolean; // sandbox only: adds an IAM-gated (admin API) client for smoke tests; the browser client is unchanged
}

export class ExchangeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, p: ExchangeProps) {
    super(scope, id, p);
    const n = (s: string) => `ftusa-${s}-${p.envName}`;
    const removal = p.envName === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;

    const key = new kms.Key(this, "DataKey", { enableKeyRotation: true, alias: `alias/${n("data")}`, removalPolicy: removal });

    // ---- persistence -------------------------------------------------------
    const conversations = new ddb.TableV2(this, "Conversations", {
      tableName: n("conversations"),
      partitionKey: { name: "pk", type: ddb.AttributeType.STRING }, sortKey: { name: "sk", type: ddb.AttributeType.STRING },
      billing: ddb.Billing.onDemand(), timeToLiveAttribute: "ttl", encryption: ddb.TableEncryptionV2.customerManagedKey(key),
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: false }, removalPolicy: removal,
      // Producer history (CONV-01): a producer's conversations, newest first.
      globalSecondaryIndexes: [{ indexName: "owner-index", partitionKey: { name: "ownerSub", type: ddb.AttributeType.STRING }, sortKey: { name: "createdAt", type: ddb.AttributeType.STRING } }],
    });
    const outcomes = new ddb.TableV2(this, "Outcomes", {
      tableName: n("outcomes"), partitionKey: { name: "outcomeId", type: ddb.AttributeType.STRING },
      billing: ddb.Billing.onDemand(), encryption: ddb.TableEncryptionV2.customerManagedKey(key),
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true }, removalPolicy: removal,
      globalSecondaryIndexes: [{ indexName: "kind-index", partitionKey: { name: "gsiKind", type: ddb.AttributeType.STRING }, sortKey: { name: "createdAt", type: ddb.AttributeType.STRING } }],
    });

    // ---- web hosting (private bucket + CloudFront OAC) --------------------
    const webBucket = new s3.Bucket(this, "WebBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, enforceSSL: true, encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: removal, autoDeleteObjects: removal === cdk.RemovalPolicy.DESTROY,
    });
    const headers = new cf.ResponseHeadersPolicy(this, "Headers", {
      securityHeadersBehavior: {
        strictTransportSecurity: { accessControlMaxAge: cdk.Duration.days(365), override: true },
        contentTypeOptions: { override: true }, frameOptions: { frameOption: cf.HeadersFrameOption.DENY, override: true },
        referrerPolicy: { referrerPolicy: cf.HeadersReferrerPolicy.NO_REFERRER, override: true },
        contentSecurityPolicy: { override: true, contentSecurityPolicy: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://cognito-idp.${this.region}.amazonaws.com https://*.auth.${this.region}.amazoncognito.com https://*.execute-api.${this.region}.amazonaws.com; frame-ancestors 'none'` },
      },
    });
    const dist = new cf.Distribution(this, "Web", {
      defaultBehavior: { origin: origins.S3BucketOrigin.withOriginAccessControl(webBucket), viewerProtocolPolicy: cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS, responseHeadersPolicy: headers },
      defaultRootObject: "index.html",
      errorResponses: [403, 404].map((s) => ({ httpStatus: s, responseHttpStatus: 200, responsePagePath: "/index.html", ttl: cdk.Duration.seconds(0) })),
    });
    const webUrl = `https://${dist.distributionDomainName}`;

    // ---- identity ----------------------------------------------------------
    const pool = new cognito.UserPool(this, "Pool", {
      userPoolName: n("users"), selfSignUpEnabled: false, signInAliases: { email: true }, signInCaseSensitive: false,
      autoVerify: { email: true }, accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      passwordPolicy: { minLength: 12, requireLowercase: true, requireUppercase: true, requireDigits: true, requireSymbols: false },
      removalPolicy: removal, deletionProtection: p.envName === "prod",
    });
    new cognito.CfnUserPoolGroup(this, "ProducerGroup", { userPoolId: pool.userPoolId, groupName: "producer", description: "Synthetic producers" });
    new cognito.CfnUserPoolGroup(this, "ReviewerGroup", { userPoolId: pool.userPoolId, groupName: "reviewer", description: "FTUSA reviewers" });
    // Public client: authorization code + PKCE, no secret.
    const client = pool.addClient("WebClient", {
      userPoolClientName: n("web"), generateSecret: false, preventUserExistenceErrors: true, enableTokenRevocation: true,
      authFlows: {}, // no direct password flows from the browser
      oAuth: { flows: { authorizationCodeGrant: true }, scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        callbackUrls: [`${webUrl}/auth/callback`, ...p.extraCallbackUrls], logoutUrls: [`${webUrl}/`, ...p.extraLogoutUrls] },
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      accessTokenValidity: cdk.Duration.hours(1), idTokenValidity: cdk.Duration.hours(1), refreshTokenValidity: cdk.Duration.hours(8),
    });
    // Sandbox-only smoke-test client: tokens can only be minted through the admin API (IAM-signed), never by a browser or anonymous caller.
    const ciClient = p.enableCiClient
      ? pool.addClient("CiClient", { userPoolClientName: n("ci-smoke"), generateSecret: false, authFlows: { adminUserPassword: true }, accessTokenValidity: cdk.Duration.minutes(30), enableTokenRevocation: true })
      : undefined;
    cdk.Tags.of(this).add("deployed-commit", p.gitSha);
    const domain = pool.addDomain("Domain", { cognitoDomain: { domainPrefix: `${n("auth")}-${this.account}`.toLowerCase() } });
    const issuer = `https://cognito-idp.${this.region}.amazonaws.com/${pool.userPoolId}`;

    // ---- guardrail (PII detect-only: flagged, never masked or blocked) -----
    const piiTypes = ["EMAIL", "PHONE", "NAME", "ADDRESS", "US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER", "INTERNATIONAL_BANK_ACCOUNT_NUMBER"];
    const guardrail = new bedrock.CfnGuardrail(this, "Guardrail", {
      name: n("guardrail"), kmsKeyArn: key.keyArn,
      blockedInputMessaging: "I can't help with that request here.", blockedOutputsMessaging: "I can't share that response.",
      contentPolicyConfig: { filtersConfig: [
        ...["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"].map((t) => ({ type: t, inputStrength: "MEDIUM", outputStrength: "MEDIUM" })),
        { type: "PROMPT_ATTACK", inputStrength: "MEDIUM", outputStrength: "NONE" } ] },
      sensitiveInformationPolicyConfig: { piiEntitiesConfig: piiTypes.map((t) => ({
        type: t, action: "NONE", inputAction: "NONE", outputAction: "NONE", inputEnabled: true, outputEnabled: true })) },
    });
    const guardrailVersion = new bedrock.CfnGuardrailVersion(this, "GuardrailV1", { guardrailIdentifier: guardrail.attrGuardrailId, description: "initial" });

    // ---- AgentCore Runtime -------------------------------------------------
    const agentAsset = new s3assets.Asset(this, "AgentZip", { path: path.resolve(process.cwd(), p.agentZip) });
    const runtimeRole = new iam.Role(this, "RuntimeRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", { conditions: {
        StringEquals: { "aws:SourceAccount": this.account }, ArnLike: { "aws:SourceArn": `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:*` } } }),
    });
    const modelArns = [
      `arn:${this.partition}:bedrock:*::foundation-model/*`,
      `arn:${this.partition}:bedrock:${this.region}:${this.account}:inference-profile/${p.modelId}`,
    ];
    runtimeRole.addToPolicy(new iam.PolicyStatement({ actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], resources: modelArns }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({ actions: ["bedrock:ApplyGuardrail"], resources: [guardrail.attrGuardrailArn] }));
    key.grantDecrypt(runtimeRole);
    agentAsset.grantRead(runtimeRole);
    runtimeRole.addToPolicy(new iam.PolicyStatement({ actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
      resources: [`arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`] }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({ actions: ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], resources: ["*"] }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({ actions: ["cloudwatch:PutMetricData"], resources: ["*"], conditions: { StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" } } }));

    const runtime = new agentcore.CfnRuntime(this, "Runtime", {
      agentRuntimeName: `ftusa_exchange_${p.envName}`.replace(/[^A-Za-z0-9_]/g, "_"),
      description: "Producer exchange agent (Strands)",
      roleArn: runtimeRole.roleArn,
      agentRuntimeArtifact: { codeConfiguration: { code: { s3: { bucket: agentAsset.s3BucketName, prefix: agentAsset.s3ObjectKey } }, entryPoint: ["main.py"], runtime: "PYTHON_3_13" } },
      networkConfiguration: { networkMode: "PUBLIC" },
      protocolConfiguration: "HTTP",
      lifecycleConfiguration: { idleRuntimeSessionTimeout: 900, maxLifetime: 3600 },
      environmentVariables: { MODEL_ID: p.modelId, GUARDRAIL_ID: guardrail.attrGuardrailId, GUARDRAIL_VERSION: guardrailVersion.attrVersion, ENV_NAME: p.envName, DEPLOYED_COMMIT: p.gitSha },
    });
    runtime.node.addDependency(runtimeRole);

    // ---- API ----------------------------------------------------------------
    const apiLogs = new logs.LogGroup(this, "ApiFnLogs", { retention: logs.RetentionDays.ONE_MONTH, removalPolicy: cdk.RemovalPolicy.DESTROY });
    const fn = new nodejs.NodejsFunction(this, "ApiFn", {
      entry: path.join(__dirname, "../../backend/src/handler.ts"), handler: "handler", runtime: lambda.Runtime.NODEJS_22_X,
      architecture: lambda.Architecture.ARM_64, memorySize: 512, timeout: cdk.Duration.seconds(60), logGroup: apiLogs, reservedConcurrentExecutions: undefined,
      environment: {
        CONVERSATIONS_TABLE: conversations.tableName, OUTCOMES_TABLE: outcomes.tableName, AGENT_RUNTIME_ARN: runtime.attrAgentRuntimeArn,
        USER_POOL_CLIENT_ID: client.userPoolClientId, ALLOWED_CLIENT_IDS: [client.userPoolClientId, ...(ciClient ? [ciClient.userPoolClientId] : [])].join(","), ISSUER: issuer, NODE_OPTIONS: "--enable-source-maps",
      },
      bundling: { minify: true, sourceMap: true, target: "node22" },
      depsLockFilePath: path.join(__dirname, "../../package-lock.json"),
      projectRoot: path.join(__dirname, "../.."),
    });
    conversations.grantReadWriteData(fn); outcomes.grantReadWriteData(fn); key.grantEncryptDecrypt(fn);
    // Dictation: Transcribe streaming has no resource-level permissions. Audio is not stored.
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["transcribe:StartStreamTranscription"], resources: ["*"] }));
    // Read aloud: Polly speech synthesis has no resource-level permissions (only lexicons do). Audio is not stored.
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ["polly:SynthesizeSpeech"], resources: ["*"] }));
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeForUser"],
      resources: [runtime.attrAgentRuntimeArn, `${runtime.attrAgentRuntimeArn}/*`],
    }));

    const api = new apigw.HttpApi(this, "Api", {
      apiName: n("api"),
      corsPreflight: { allowOrigins: [webUrl, ...p.extraCallbackUrls.map((u) => new URL(u).origin)], allowMethods: [apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PUT, apigw.CorsHttpMethod.DELETE], allowHeaders: ["authorization", "content-type"], maxAge: cdk.Duration.hours(1) },
      defaultAuthorizer: new authorizers.HttpJwtAuthorizer("CognitoJwt", issuer, { jwtAudience: [client.userPoolClientId, ...(ciClient ? [ciClient.userPoolClientId] : [])] }),
    });
    api.addRoutes({ path: "/{proxy+}", methods: [apigw.HttpMethod.GET, apigw.HttpMethod.POST, apigw.HttpMethod.PUT, apigw.HttpMethod.DELETE], integration: new integrations.HttpLambdaIntegration("ApiIntegration", fn) });
    const stage = api.defaultStage!.node.defaultChild as apigw.CfnStage;
    stage.defaultRouteSettings = { throttlingBurstLimit: 20, throttlingRateLimit: 10 };
    const accessLogs = new logs.LogGroup(this, "ApiAccessLogs", { retention: logs.RetentionDays.ONE_MONTH, removalPolicy: cdk.RemovalPolicy.DESTROY });
    stage.accessLogSettings = { destinationArn: accessLogs.logGroupArn, format: JSON.stringify({ requestId: "$context.requestId", route: "$context.routeKey", status: "$context.status", sub: "$context.authorizer.claims.sub", latency: "$context.responseLatency" }) };

    // ---- web deployment with runtime config (no secrets) ---------------------
    new s3deploy.BucketDeployment(this, "WebDeploy", {
      destinationBucket: webBucket, distribution: dist, distributionPaths: ["/*"], prune: true,
      sources: [
        s3deploy.Source.asset(path.resolve(process.cwd(), p.webDist)),
        s3deploy.Source.jsonData("config.json", {
          region: this.region, apiBaseUrl: api.apiEndpoint, clientId: client.userPoolClientId, issuer,
          authority: issuer, cognitoDomain: domain.baseUrl(), redirectUri: `${webUrl}/auth/callback`, logoutUri: `${webUrl}/`,
        }),
      ],
    });

    // ---- operational diagnostics ----------------------------------------------
    new cdk.aws_cloudwatch.Alarm(this, "Api5xx", { metric: fn.metricErrors({ period: cdk.Duration.minutes(5) }), threshold: 3, evaluationPeriods: 1, alarmDescription: "API Lambda errors" });

    if (ciClient) new cdk.CfnOutput(this, "CiClientId", { value: ciClient.userPoolClientId });
    new cdk.CfnOutput(this, "DeployedCommit", { value: p.gitSha });
    new cdk.CfnOutput(this, "WebUrl", { value: webUrl });
    new cdk.CfnOutput(this, "ApiUrl", { value: api.apiEndpoint });
    new cdk.CfnOutput(this, "UserPoolId", { value: pool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", { value: client.userPoolClientId });
    new cdk.CfnOutput(this, "CognitoDomain", { value: domain.baseUrl() });
    new cdk.CfnOutput(this, "AgentRuntimeArn", { value: runtime.attrAgentRuntimeArn });
    new cdk.CfnOutput(this, "OutcomesTable", { value: outcomes.tableName });
    new cdk.CfnOutput(this, "ConversationsTable", { value: conversations.tableName });
    new cdk.CfnOutput(this, "GuardrailId", { value: guardrail.attrGuardrailId });
  }
}

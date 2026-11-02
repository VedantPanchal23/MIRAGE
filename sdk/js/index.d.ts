/**
 * Type declarations for @mirage-ai/sdk
 */

export interface MirageClientOptions {
  apiKey: string;
  baseUrl?: string;
  timeout?: number;
  tenantId?: string;
}

export interface VerificationRequestOptions {
  prompt: string;
  response: string;
  modelId?: string;
  autoCorrect?: boolean;
  knowledgeBaseId?: string;
}

export interface ConformalInterval {
  lower: number;
  upper: number;
}

export interface HRSResult {
  hrs: number;
  tier: "LOW" | "GUARDED" | "ELEVATED" | "CRITICAL";
  conformal_interval: ConformalInterval;
  claims_count: number;
  contradicted_claims_count: number;
}

export interface VerificationResponse {
  request_id: string;
  hrs_result: HRSResult;
  verified_response: string;
  claims: Array<{
    claim: { claim_id: string; text: string };
    status: string;
    risk_score: number;
    rav_score: number;
    scs_score: number;
    nli_score: number;
    ics_score: number;
  }>;
}

export interface StreamEvent<T = any> {
  event: "connected" | "claims_extracted" | "claim_verified" | "verification_complete" | string;
  data: T;
}

export interface ActionProposal {
  action_id: string;
  decision: "ALLOW" | "DENY" | "REQUIRE_APPROVAL";
  risk_level: string;
  fencing_token?: number;
}

export class MirageError extends Error {
  status: number | null;
  code: string | null;
  details: any;
  constructor(message: string, status?: number | null, code?: string | null, details?: any);
}

export class MirageAuthenticationError extends MirageError {}
export class MirageAuthorizationError extends MirageError {}
export class MirageExecutionUncertainError extends MirageError {}

export class MirageClient {
  constructor(options: MirageClientOptions);

  verify(params: VerificationRequestOptions): Promise<VerificationResponse>;

  verifyStream(params: VerificationRequestOptions): AsyncGenerator<StreamEvent, void, unknown>;

  proposeAction(proposal: {
    transaction_id: string;
    tool_name: string;
    action_type: string;
    target_resource: string;
    parameters: Record<string, any>;
  }): Promise<ActionProposal>;

  executeAction(actionId: string, approvalToken?: string | null): Promise<any>;

  verifyOutcome(payload: {
    action_id: string;
    execution_result: Record<string, any>;
    predicted_postconditions: Record<string, any>;
  }): Promise<any>;

  listTools(): Promise<Array<any>>;

  getPendingApprovals(): Promise<Array<any>>;
  grantApproval(approvalId: string, reason?: string): Promise<any>;
  denyApproval(approvalId: string, reason?: string): Promise<any>;

  getAuditIntegrity(): Promise<{ valid: boolean; total_events: number }>;
  getTenantBudget(tenantId?: string | null): Promise<any>;
  updateTenantBudget(params: {
    totalBudgetMicros: number;
    hardLimit?: boolean;
    resetPeriod?: string;
  }): Promise<any>;
  listResourceLeases(params?: {
    resource_uri?: string;
    limit?: number;
    offset?: number;
  }): Promise<Array<any>>;
  releaseResourceLease(leaseId: string, fencingToken: number): Promise<any>;
}

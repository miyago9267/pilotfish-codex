export type ModelRef = {
  provider: string;
  model: string;
  variant?: string;
};

export type RouteSource =
  | "explicit"
  | "agent_config"
  | "inherited"
  | "fallback";

export type FallbackPolicy =
  | "none"
  | "ordered_candidates"
  | "same_capability";

export type CapabilityStatus = "declared" | "override" | "observed" | "unknown";

export type ResolvedModel = ModelRef & {
  source: RouteSource;
};

export type RouteReceipt = {
  version: 1;
  role: string;
  agent: string;
  requested: ModelRef;
  resolved: ResolvedModel;
  fallback: FallbackPolicy;
  capability_status: CapabilityStatus;
  provider_identity: string;
};

import type {
  CapabilityStatus,
  FallbackPolicy,
  ModelRef,
  ResolvedModel,
  RouteReceipt,
} from "./types.ts";

export type RouteReceiptInput = {
  role: string;
  agent: string;
  requested: ModelRef;
  resolved: ResolvedModel;
  fallback: FallbackPolicy;
  capabilityStatus: CapabilityStatus;
  providerIdentity: string;
};

function redactToken(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160);
}

function redactProviderIdentity(value: string): string {
  return value.includes("://") ? "unknown" : redactToken(value);
}

function redactModelRef(ref: ModelRef): ModelRef {
  return {
    provider: redactToken(ref.provider),
    model: redactToken(ref.model),
    ...(ref.variant === undefined ? {} : { variant: redactToken(ref.variant) }),
  };
}

export function createRouteReceipt(input: RouteReceiptInput): RouteReceipt {
  return {
    version: 1,
    role: redactToken(input.role),
    agent: redactToken(input.agent),
    requested: redactModelRef(input.requested),
    resolved: {
      ...redactModelRef(input.resolved),
      source: input.resolved.source,
    },
    fallback: input.fallback,
    capability_status: input.capabilityStatus,
    provider_identity: redactProviderIdentity(input.providerIdentity),
  };
}

export function serializeRouteReceipt(receipt: RouteReceipt): string {
  return JSON.stringify(receipt);
}

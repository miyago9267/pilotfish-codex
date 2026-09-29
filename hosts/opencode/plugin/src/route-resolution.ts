import {
  createDefaultRoleRegistry,
  type RoleAliases,
  type RoleRegistry,
} from "./role-contract.js";
import { createRouteReceipt } from "./receipt.js";
import type {
  CapabilityStatus,
  FallbackPolicy,
  ModelRef,
  RouteReceipt,
  RouteSource,
} from "./types.js";

export type CapabilitySource = "catalog" | "override" | "live";

export type CapabilityDeclaration = {
  supported?: readonly string[];
  unsupported?: readonly string[];
  source: CapabilitySource;
};

export type ModelCatalogEntry = {
  capabilities?: CapabilityDeclaration;
  variants?: Readonly<Record<string, { capabilities?: CapabilityDeclaration }>>;
};

export type ProviderCatalogEntry = {
  authenticated: boolean | "unknown";
  identity?: string;
  models: Readonly<Record<string, ModelCatalogEntry>>;
};

export type AgentMode = "primary" | "subagent" | "all";

export type AgentCatalogEntry = {
  mode: AgentMode;
  available?: boolean;
  model?: ModelRef;
};

export type ResolvedOpenCodeCatalog = {
  agents: Readonly<Record<string, AgentCatalogEntry>>;
  providers: Readonly<Record<string, ProviderCatalogEntry>>;
};

export type Candidate = ModelRef & {
  requires?: readonly string[];
};

export type RoleRoute = {
  agent: string;
  candidates?: readonly Candidate[];
  fallback: FallbackPolicy;
  requiredCapabilities?: readonly string[];
  inheritParent?: boolean;
};

export type RoutingConfig = {
  version: 1;
  roles: Readonly<Record<string, RoleRoute>>;
  aliases?: RoleAliases;
};

export type RouteAttempt = {
  candidate: ModelRef;
  status: "selected" | "rejected";
  error?: RouteResolutionError["code"];
};

export type ResolveRouteRequest = {
  role: string;
  config: RoutingConfig;
  catalog: ResolvedOpenCodeCatalog;
  registry?: RoleRegistry;
  explicit?: ModelRef;
  parentModel?: ModelRef;
  requiredCapabilities?: readonly string[];
};

export type ResolveRouteResult = {
  receipt: RouteReceipt;
  attempts: readonly RouteAttempt[];
};

export type RouteErrorCode =
  | "invalid_config"
  | "role_not_found"
  | "agent_not_found"
  | "agent_unavailable"
  | "agent_mode_invalid"
  | "no_route"
  | "provider_not_found"
  | "provider_unauthenticated"
  | "model_not_found"
  | "variant_not_found"
  | "capability_unknown"
  | "capability_unsupported";

function safeDetail(value: string | number): string | number {
  if (typeof value === "number") return value;
  return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160);
}

export class RouteResolutionError extends Error {
  readonly code: RouteErrorCode;
  readonly details: Readonly<Record<string, string | number>>;

  constructor(
    code: RouteErrorCode,
    details: Record<string, string | number> = {},
  ) {
    const safeDetails = Object.fromEntries(
      Object.entries(details).map(([key, value]) => [key, safeDetail(value)]),
    );
    super(`${code}: ${JSON.stringify(safeDetails)}`);
    this.name = "RouteResolutionError";
    this.code = code;
    this.details = safeDetails;
  }
}

function fail(
  code: RouteErrorCode,
  details: Record<string, string | number> = {},
): never {
  throw new RouteResolutionError(code, details);
}

function hasOwn<T extends object>(object: T, key: PropertyKey): key is keyof T {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertRouteToken(value: string, field: string): void {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/.test(value) ||
    value.includes("://")
  ) {
    fail("invalid_config", { field });
  }
}

function assertModelRef(ref: ModelRef, field: string): void {
  if (ref === undefined || ref === null || typeof ref !== "object") {
    fail("invalid_config", { field });
  }
  assertRouteToken(ref.provider, `${field}.provider`);
  assertRouteToken(ref.model, `${field}.model`);
  if (ref.variant !== undefined) {
    assertRouteToken(ref.variant, `${field}.variant`);
  }
}

function uniqueCapabilities(
  ...sets: readonly (readonly string[] | undefined)[]
): string[] {
  return [...new Set(sets.flatMap((set) => set ?? []))];
}

function capabilityStatus(
  declaration: CapabilityDeclaration | undefined,
): CapabilityStatus {
  if (declaration?.source === "catalog") return "declared";
  if (declaration?.source === "override") return "override";
  if (declaration?.source === "live") return "observed";
  return "unknown";
}

function mergeCapabilities(
  model: ModelCatalogEntry,
  modelId: string,
  variant: string | undefined,
  provider: string,
): CapabilityDeclaration | undefined {
  const base = model.capabilities;
  if (variant === undefined) return base;

  if (model.variants === undefined || !hasOwn(model.variants, variant)) {
    fail("variant_not_found", { provider, model: modelId, variant });
  }

  const variantCapabilities = model.variants[variant]?.capabilities;
  if (variantCapabilities === undefined) return base;
  if (base === undefined) return variantCapabilities;

  const sourceRank: Record<CapabilitySource, number> = {
    catalog: 1,
    override: 2,
    live: 3,
  };
  const source =
    sourceRank[variantCapabilities.source] >= sourceRank[base.source]
      ? variantCapabilities.source
      : base.source;

  return {
    source,
    supported: uniqueCapabilities(base.supported, variantCapabilities.supported),
    unsupported: uniqueCapabilities(base.unsupported, variantCapabilities.unsupported),
  };
}

function validateCandidate(
  candidate: Candidate,
  catalog: ResolvedOpenCodeCatalog,
  requiredCapabilities: readonly string[],
): CapabilityStatus {
  assertModelRef(candidate, "candidate");
  const provider = hasOwn(catalog.providers, candidate.provider)
    ? catalog.providers[candidate.provider]
    : undefined;
  if (provider === undefined) {
    fail("provider_not_found", { provider: candidate.provider });
  }
  if (provider.authenticated !== true) {
    fail("provider_unauthenticated", { provider: candidate.provider });
  }

  const model = hasOwn(provider.models, candidate.model)
    ? provider.models[candidate.model]
    : undefined;
  if (model === undefined) {
    fail("model_not_found", {
      provider: candidate.provider,
      model: candidate.model,
    });
  }

  const declaration = mergeCapabilities(
    model,
    candidate.model,
    candidate.variant,
    candidate.provider,
  );
  const required = uniqueCapabilities(requiredCapabilities, candidate.requires);
  for (const capability of required) {
    assertRouteToken(capability, "requiredCapabilities");
    if (declaration?.unsupported?.includes(capability)) {
      fail("capability_unsupported", {
        provider: candidate.provider,
        model: candidate.model,
        capability,
      });
    }
    if (!declaration?.supported?.includes(capability)) {
      fail("capability_unknown", {
        provider: candidate.provider,
        model: candidate.model,
        capability,
      });
    }
  }
  return capabilityStatus(declaration);
}

function modelRef(candidate: Candidate): ModelRef {
  return {
    provider: candidate.provider,
    model: candidate.model,
    ...(candidate.variant === undefined ? {} : { variant: candidate.variant }),
  };
}

function validateCapabilityList(value: unknown, field: string): void {
  if (value === undefined) return;
  if (!Array.isArray(value)) fail("invalid_config", { field });
  for (const capability of value) {
    assertRouteToken(capability as string, field);
  }
}

function validateCapabilityDeclaration(value: unknown, field: string): void {
  if (!isRecord(value)) fail("invalid_config", { field });
  if (
    value.source !== "catalog" &&
    value.source !== "override" &&
    value.source !== "live"
  ) {
    fail("invalid_config", { field: `${field}.source` });
  }
  validateCapabilityList(value.supported, `${field}.supported`);
  validateCapabilityList(value.unsupported, `${field}.unsupported`);
}

function validateRouteConfig(config: RoutingConfig): void {
  if (!isRecord(config) || config.version !== 1 || !isRecord(config.roles)) {
    fail("invalid_config", { field: "config" });
  }
  if (config.aliases !== undefined) {
    if (!isRecord(config.aliases)) {
      fail("invalid_config", { field: "config.aliases" });
    }
    for (const [alias, target] of Object.entries(config.aliases)) {
      assertRouteToken(alias, "config.aliases");
      assertRouteToken(target as string, "config.aliases");
    }
  }
  for (const [role, route] of Object.entries(config.roles)) {
    assertRouteToken(role, "config.roles");
    if (!isRecord(route) || route.fallback === undefined) {
      fail("invalid_config", { field: `roles.${role}` });
    }
    if (
      route.fallback !== "none" &&
      route.fallback !== "ordered_candidates" &&
      route.fallback !== "same_capability"
    ) {
      fail("invalid_config", { field: `roles.${role}.fallback` });
    }
    assertRouteToken(route.agent as string, `roles.${role}.agent`);
    if (route.candidates !== undefined && !Array.isArray(route.candidates)) {
      fail("invalid_config", { field: `roles.${role}.candidates` });
    }
    for (const candidate of route.candidates ?? []) {
      if (!isRecord(candidate)) {
        fail("invalid_config", { field: `roles.${role}.candidates` });
      }
      assertRouteToken(candidate.provider as string, `roles.${role}.candidate.provider`);
      assertRouteToken(candidate.model as string, `roles.${role}.candidate.model`);
      if (candidate.variant !== undefined) {
        assertRouteToken(candidate.variant as string, `roles.${role}.candidate.variant`);
      }
      validateCapabilityList(candidate.requires, `roles.${role}.candidate.requires`);
    }
    validateCapabilityList(route.requiredCapabilities, `roles.${role}.requiredCapabilities`);
  }
}

function validateCatalog(catalog: ResolvedOpenCodeCatalog): void {
  if (!isRecord(catalog) || !isRecord(catalog.agents) || !isRecord(catalog.providers)) {
    fail("invalid_config", { field: "catalog" });
  }
  for (const [provider, value] of Object.entries(catalog.providers)) {
    if (!isRecord(value) || !isRecord(value.models)) {
      fail("invalid_config", { field: `catalog.providers.${provider}` });
    }
    assertRouteToken(provider, "catalog.providers");
    if (
      value.authenticated !== true &&
      value.authenticated !== false &&
      value.authenticated !== "unknown"
    ) {
      fail("invalid_config", { field: `catalog.providers.${provider}.authenticated` });
    }
    if (value.identity !== undefined && typeof value.identity !== "string") {
      fail("invalid_config", { field: `catalog.providers.${provider}.identity` });
    }
    for (const [model, entry] of Object.entries(value.models)) {
      assertRouteToken(model, `catalog.providers.${provider}.models`);
      if (!isRecord(entry)) {
        fail("invalid_config", {
          field: `catalog.providers.${provider}.models.${model}`,
        });
      }
      if (entry.capabilities !== undefined) {
        validateCapabilityDeclaration(
          entry.capabilities,
          `catalog.providers.${provider}.models.${model}.capabilities`,
        );
      }
      if (entry.variants !== undefined) {
        if (!isRecord(entry.variants)) {
          fail("invalid_config", {
            field: `catalog.providers.${provider}.models.${model}.variants`,
          });
        }
        for (const [variant, variantEntry] of Object.entries(entry.variants)) {
          assertRouteToken(
            variant,
            `catalog.providers.${provider}.models.${model}.variants`,
          );
          if (!isRecord(variantEntry)) {
            fail("invalid_config", {
              field: `catalog.providers.${provider}.models.${model}.variants.${variant}`,
            });
          }
          if (variantEntry.capabilities !== undefined) {
            validateCapabilityDeclaration(
              variantEntry.capabilities,
              `catalog.providers.${provider}.models.${model}.variants.${variant}.capabilities`,
            );
          }
        }
      }
    }
  }
  for (const [agent, value] of Object.entries(catalog.agents)) {
    if (!isRecord(value)) {
      fail("invalid_config", { field: `catalog.agents.${agent}` });
    }
    assertRouteToken(agent, "catalog.agents");
    if (value.available !== undefined && typeof value.available !== "boolean") {
      fail("invalid_config", { field: `catalog.agents.${agent}.available` });
    }
    if (value.model !== undefined) {
      assertModelRef(value.model as ModelRef, `catalog.agents.${agent}.model`);
    }
  }
}

function resolveRole(
  request: ResolveRouteRequest,
  registry: RoleRegistry,
): { id: string; route: RoleRoute } {
  validateRouteConfig(request.config);
  const id = registry.canonicalize(request.role, request.config.aliases);
  if (id === undefined || !registry.has(request.role, request.config.aliases)) {
    fail("role_not_found", { role: request.role });
  }
  const route = hasOwn(request.config.roles, id)
    ? request.config.roles[id]
    : hasOwn(request.config.roles, request.role)
      ? request.config.roles[request.role]
      : undefined;
  if (route === undefined) {
    fail("invalid_config", { field: `roles.${id}` });
  }
  return { id, route };
}

function validateAgent(
  route: RoleRoute,
  catalog: ResolvedOpenCodeCatalog,
): AgentCatalogEntry {
  const agent = hasOwn(catalog.agents, route.agent)
    ? catalog.agents[route.agent]
    : undefined;
  if (agent === undefined) {
    fail("agent_not_found", { agent: route.agent });
  }
  if (agent.available === false) {
    fail("agent_unavailable", { agent: route.agent });
  }
  if (!["primary", "subagent", "all"].includes(agent.mode)) {
    fail("agent_mode_invalid", { agent: route.agent });
  }
  return agent;
}

function sourceForCandidate(
  index: number,
  inherited: boolean,
): RouteSource {
  if (inherited) return "inherited";
  return index === 0 ? "agent_config" : "fallback";
}

export function resolveRoute(request: ResolveRouteRequest): ResolveRouteResult {
  validateCatalog(request.catalog);
  const registry = request.registry ?? createDefaultRoleRegistry();
  const { id: role, route } = resolveRole(request, registry);
  const agent = validateAgent(route, request.catalog);
  const requiredCapabilities = uniqueCapabilities(
    route.requiredCapabilities,
    request.requiredCapabilities,
  );

  if (route.fallback === "same_capability" && requiredCapabilities.length === 0) {
    fail("invalid_config", { field: "same_capability.requiredCapabilities" });
  }

  if (request.explicit !== undefined) {
    const capabilityStatus = validateCandidate(
      request.explicit,
      request.catalog,
      requiredCapabilities,
    );
    const receipt = createRouteReceipt({
      role,
      agent: route.agent,
      requested: request.explicit,
      resolved: { ...request.explicit, source: "explicit" },
      fallback: route.fallback,
      capabilityStatus,
      providerIdentity: hasOwn(request.catalog.providers, request.explicit.provider)
        ? request.catalog.providers[request.explicit.provider]?.identity ?? "unknown"
        : "unknown",
    });
    return {
      receipt,
      attempts: [{ candidate: modelRef(request.explicit), status: "selected" }],
    };
  }

  let candidates: readonly Candidate[];
  let inherited = false;
  if (route.candidates !== undefined && route.candidates.length > 0) {
    candidates = route.candidates;
  } else if (agent.model !== undefined) {
    candidates = [agent.model];
  } else if (route.inheritParent === true && request.parentModel !== undefined) {
    candidates = [request.parentModel];
    inherited = true;
  } else {
    fail("no_route", { role, agent: route.agent });
  }

  const requested = modelRef(candidates[0]);
  const attempts: RouteAttempt[] = [];
  for (let index = 0; index < candidates.length; index += 1) {
    if (route.fallback === "none" && index > 0) break;
    const candidate = candidates[index];
    try {
      const capabilityStatus = validateCandidate(
        candidate,
        request.catalog,
        requiredCapabilities,
      );
      const source = sourceForCandidate(index, inherited);
      attempts.push({ candidate: modelRef(candidate), status: "selected" });
      const providerIdentity = hasOwn(request.catalog.providers, candidate.provider)
        ? request.catalog.providers[candidate.provider]?.identity ?? "unknown"
        : "unknown";
      return {
        receipt: createRouteReceipt({
          role,
          agent: route.agent,
          requested,
          resolved: { ...modelRef(candidate), source },
          fallback: route.fallback,
          capabilityStatus,
          providerIdentity,
        }),
        attempts,
      };
    } catch (error) {
      if (!(error instanceof RouteResolutionError)) throw error;
      attempts.push({
        candidate: modelRef(candidate),
        status: "rejected",
        error: error.code,
      });
      if (route.fallback === "none") throw error;
    }
  }

  fail("no_route", {
    role,
    agent: route.agent,
    attempts: attempts.length,
  });
}

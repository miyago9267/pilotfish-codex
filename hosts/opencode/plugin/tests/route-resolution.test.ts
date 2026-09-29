import { describe, expect, test } from "bun:test";
import {
  RouteResolutionError,
  resolveRoute,
  type ResolvedOpenCodeCatalog,
  type RoutingConfig,
} from "../src/route-resolution.ts";

const catalog: ResolvedOpenCodeCatalog = {
  agents: {
    scout: { mode: "subagent", available: true },
    verifier: { mode: "subagent", available: true },
  },
  providers: {
    direct: {
      authenticated: true,
      identity: "direct",
      models: {
        scout: {
          capabilities: {
            supported: ["tools", "streaming"],
            source: "catalog",
          },
        },
        verifier: {
          capabilities: {
            supported: ["tools", "reasoning"],
            source: "catalog",
          },
          variants: {
            high: {
              capabilities: {
                supported: ["tools", "reasoning"],
                source: "catalog",
              },
            },
          },
        },
      },
    },
    cliproxyapi: {
      authenticated: true,
      identity: "proxy-resolved",
      models: {
        verifier: {
          capabilities: {
            supported: ["tools", "reasoning"],
            source: "override",
          },
          variants: {
            high: {
              capabilities: {
                supported: ["tools", "reasoning"],
                source: "override",
              },
            },
          },
        },
      },
    },
    unauthenticated: {
      authenticated: false,
      models: { scout: {} },
    },
  },
};

const baseConfig: RoutingConfig = {
  version: 1,
  roles: {
    scout: {
      agent: "scout",
      candidates: [{ provider: "direct", model: "scout" }],
      fallback: "none",
    },
  },
};

describe("route resolution", () => {
  test("resolves separate provider, model, and variant fields", () => {
    const result = resolveRoute({
      role: "scout",
      config: baseConfig,
      catalog,
      requiredCapabilities: ["tools"],
    });

    expect(result.receipt.requested).toEqual({
      provider: "direct",
      model: "scout",
    });
    expect(result.receipt.resolved).toEqual({
      provider: "direct",
      model: "scout",
      source: "agent_config",
    });
    expect(result.receipt.fallback).toBe("none");
    expect(result.receipt.capability_status).toBe("declared");
  });

  test("uses an available fallback and records a proxy boundary", () => {
    const config: RoutingConfig = {
      version: 1,
      roles: {
        verifier: {
          agent: "verifier",
          candidates: [
            { provider: "unauthenticated", model: "scout" },
            { provider: "cliproxyapi", model: "verifier", variant: "high" },
          ],
          fallback: "ordered_candidates",
        },
      },
    };

    const result = resolveRoute({
      role: "verifier",
      config,
      catalog,
      requiredCapabilities: ["reasoning"],
    });

    expect(result.receipt.resolved).toEqual({
      provider: "cliproxyapi",
      model: "verifier",
      variant: "high",
      source: "fallback",
    });
    expect(result.receipt.provider_identity).toBe("proxy-resolved");
    expect(result.receipt.capability_status).toBe("override");
    expect(result.attempts).toHaveLength(2);
  });

  test("does not silently fall back for an explicit model", () => {
    const config: RoutingConfig = {
      version: 1,
      roles: {
        scout: {
          agent: "scout",
          candidates: [{ provider: "direct", model: "scout" }],
          fallback: "ordered_candidates",
        },
      },
    };

    expect(() =>
      resolveRoute({
        role: "scout",
        config,
        catalog,
        explicit: { provider: "unauthenticated", model: "scout" },
      }),
    ).toThrowError(RouteResolutionError);
  });

  test("records inherited parent model only when the route opts in", () => {
    const config: RoutingConfig = {
      version: 1,
      roles: {
        scout: {
          agent: "scout",
          fallback: "none",
          inheritParent: true,
        },
      },
    };

    const result = resolveRoute({
      role: "scout",
      config,
      catalog,
      parentModel: { provider: "direct", model: "scout" },
    });

    expect(result.receipt.resolved).toEqual({
      provider: "direct",
      model: "scout",
      source: "inherited",
    });
  });

  test("records unknown capability status when the catalog has no declaration", () => {
    const unknownCatalog = {
      ...catalog,
      providers: {
        ...catalog.providers,
        direct: {
          ...catalog.providers.direct,
          models: { ...catalog.providers.direct.models, scout: {} },
        },
      },
    };

    const result = resolveRoute({ role: "scout", config: baseConfig, catalog: unknownCatalog });

    expect(result.receipt.capability_status).toBe("unknown");
    const { source: _source, ...resolvedModel } = result.receipt.resolved;
    expect(resolvedModel).toEqual(result.receipt.requested);
  });

  test("same_capability rejects a fallback without the required capability", () => {
    const config: RoutingConfig = {
      version: 1,
      roles: {
        scout: {
          agent: "scout",
          candidates: [
            { provider: "unauthenticated", model: "scout" },
            { provider: "direct", model: "scout" },
          ],
          fallback: "same_capability",
        },
      },
    };

    const result = resolveRoute({
      role: "scout",
      config,
      catalog,
      requiredCapabilities: ["tools"],
    });

    expect(result.receipt.resolved.provider).toBe("direct");
    expect(result.receipt.fallback).toBe("same_capability");
  });

  test("fails closed for missing model, variant, and capability", () => {
    const missingModel: RoutingConfig = {
      version: 1,
      roles: {
        scout: {
          agent: "scout",
          candidates: [{ provider: "direct", model: "missing" }],
          fallback: "none",
        },
      },
    };

    expect(() =>
      resolveRoute({ role: "scout", config: missingModel, catalog }),
    ).toThrowError(RouteResolutionError);

    const missingVariant: RoutingConfig = {
      version: 1,
      roles: {
        scout: {
          agent: "scout",
          candidates: [{ provider: "direct", model: "scout", variant: "high" }],
          fallback: "none",
        },
      },
    };

    expect(() =>
      resolveRoute({ role: "scout", config: missingVariant, catalog }),
    ).toThrowError(RouteResolutionError);

    expect(() =>
      resolveRoute({
        role: "scout",
        config: baseConfig,
        catalog,
        requiredCapabilities: ["vision"],
      }),
    ).toThrowError(RouteResolutionError);
  });

  test("rejects malformed customer catalog as invalid configuration", () => {
    const malformedCatalog = {
      ...catalog,
      providers: {
        ...catalog.providers,
        direct: {
          ...catalog.providers.direct,
          models: { ...catalog.providers.direct.models, scout: null },
        },
      },
    } as unknown as ResolvedOpenCodeCatalog;

    expect(() =>
      resolveRoute({ role: "scout", config: baseConfig, catalog: malformedCatalog }),
    ).toThrowError(/invalid_config/);
  });
});

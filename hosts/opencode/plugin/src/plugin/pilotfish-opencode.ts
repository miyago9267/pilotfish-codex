import { tool, type Plugin } from "@opencode-ai/plugin";
import { isAbsolute, relative, resolve } from "node:path";
import {
  resolveRoute,
  RouteResolutionError,
  type ResolvedOpenCodeCatalog,
  type RoleRoute,
  type RoutingConfig,
} from "../route-resolution.js";
import { serializeRouteReceipt } from "../receipt.js";
import { DEFAULT_ROLE_DEFINITIONS } from "../role-contract.js";

export type PilotfishPluginOptions = {
  catalogPath?: string;
  routingPath?: string;
};

const DEFAULT_CATALOG_PATH = ".opencode/pilotfish/catalog.json";
const DEFAULT_ROUTING_PATH = ".opencode/pilotfish/routing.json";

function optionPath(
  options: PilotfishPluginOptions,
  key: keyof PilotfishPluginOptions,
  fallback: string,
): string {
  const value = options[key];
  if (value === undefined) return fallback;
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    value.includes("://")
  ) {
    throw new RouteResolutionError("invalid_config", { field: `plugin.${key}` });
  }
  return value;
}

function safeProjectPath(directory: string, configuredPath: string): string {
  const root = resolve(directory);
  const path = resolve(root, configuredPath);
  const relativePath = relative(root, path);
  if (
    isAbsolute(relativePath) ||
    relativePath === ".." ||
    relativePath.startsWith("../")
  ) {
    throw new RouteResolutionError("invalid_config", { field: "plugin.path" });
  }
  return path;
}

async function readJson<T>(path: string, label: string): Promise<T> {
  const file = Bun.file(path);
  if (!(await file.exists())) {
    throw new RouteResolutionError("invalid_config", { field: `${label}.missing` });
  }
  try {
    return (await file.json()) as T;
  } catch {
    throw new RouteResolutionError("invalid_config", { field: `${label}.json` });
  }
}

async function readOptionalJson<T>(path: string, label: string): Promise<T | undefined> {
  const file = Bun.file(path);
  if (!(await file.exists())) return undefined;
  try {
    return (await file.json()) as T;
  } catch {
    throw new RouteResolutionError("invalid_config", { field: `${label}.json` });
  }
}

function nativeRouting(): RoutingConfig {
  const roles: Record<string, RoleRoute> = {};
  for (const role of DEFAULT_ROLE_DEFINITIONS) {
    roles[role.id] = { agent: role.id, fallback: "none" };
  }
  return { version: 1, roles };
}

function pluginOptions(value: Record<string, unknown> | undefined): PilotfishPluginOptions {
  return {
    catalogPath: typeof value?.catalogPath === "string" ? value.catalogPath : undefined,
    routingPath: typeof value?.routingPath === "string" ? value.routingPath : undefined,
  };
}

export function createPilotfishRouteTool(options: PilotfishPluginOptions = {}) {
  return tool({
    description:
      "Validate one customer-owned Pilotfish role route for an OpenCode role invocation. This reports a route receipt; it does not change the current session model.",
    args: {
      role: tool.schema.string().describe("Pilotfish role or customer alias"),
      provider: tool.schema.string().optional().describe("Explicit provider override"),
      model: tool.schema.string().optional().describe("Explicit model override"),
      variant: tool.schema.string().optional().describe("Explicit model variant"),
      requiredCapabilities: tool.schema
        .array(tool.schema.string())
        .optional()
        .describe("Capabilities required by this role invocation"),
      parentProvider: tool.schema.string().optional(),
      parentModel: tool.schema.string().optional(),
      parentVariant: tool.schema.string().optional(),
    },
    async execute(args, context) {
      const hasExplicit =
        args.provider !== undefined ||
        args.model !== undefined ||
        args.variant !== undefined;
      if (hasExplicit && (args.provider === undefined || args.model === undefined)) {
        throw new RouteResolutionError("invalid_config", {
          field: "explicit.provider_and_model",
        });
      }

      const hasParent =
        args.parentProvider !== undefined ||
        args.parentModel !== undefined ||
        args.parentVariant !== undefined;
      if (hasParent && (args.parentProvider === undefined || args.parentModel === undefined)) {
        throw new RouteResolutionError("invalid_config", {
          field: "parentModel.provider_and_model",
        });
      }

      try {
        const catalog = await readJson<ResolvedOpenCodeCatalog>(
          safeProjectPath(
            context.directory,
            optionPath(options, "catalogPath", DEFAULT_CATALOG_PATH),
          ),
          "catalog",
        );
        const config =
          (await readOptionalJson<RoutingConfig>(
          safeProjectPath(
            context.directory,
            optionPath(options, "routingPath", DEFAULT_ROUTING_PATH),
          ),
          "routing",
          )) ?? nativeRouting();
        const result = resolveRoute({
          role: args.role,
          config,
          catalog,
          explicit:
            args.provider === undefined || args.model === undefined
              ? undefined
              : {
                  provider: args.provider,
                  model: args.model,
                  ...(args.variant === undefined ? {} : { variant: args.variant }),
                },
          parentModel:
            args.parentProvider === undefined || args.parentModel === undefined
              ? undefined
              : {
                  provider: args.parentProvider,
                  model: args.parentModel,
                  ...(args.parentVariant === undefined
                    ? {}
                    : { variant: args.parentVariant }),
                },
          requiredCapabilities: args.requiredCapabilities,
        });
        context.metadata({
          title: `Pilotfish route: ${result.receipt.role}`,
          metadata: { receipt: result.receipt, attempts: result.attempts },
        });
        return {
          title: `Pilotfish route: ${result.receipt.resolved.provider}/${result.receipt.resolved.model}`,
          output: serializeRouteReceipt(result.receipt),
          metadata: { receipt: result.receipt, attempts: result.attempts },
        };
      } catch (error) {
        if (error instanceof RouteResolutionError) {
          return {
            title: `Pilotfish route rejected: ${error.code}`,
            output: JSON.stringify({ code: error.code, details: error.details }),
            metadata: { code: error.code, details: error.details },
          };
        }
        throw error;
      }
    },
  });
}

export const PilotfishOpenCodePlugin: Plugin = async (_input, options) => ({
  tool: {
    pilotfish_route: createPilotfishRouteTool(pluginOptions(options)),
  },
});

export default PilotfishOpenCodePlugin;

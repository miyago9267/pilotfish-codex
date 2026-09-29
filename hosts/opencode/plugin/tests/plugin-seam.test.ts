import { describe, expect, test } from "bun:test";
import { mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { createPilotfishRouteTool, PilotfishOpenCodePlugin } from "../src/plugin/pilotfish-opencode.ts";

const catalog = {
  agents: { scout: { mode: "subagent", available: true } },
  providers: {
    direct: {
      authenticated: true,
      identity: "direct",
      models: {
        scout: {
          capabilities: { supported: ["tools"], source: "catalog" },
        },
      },
    },
  },
};

const routing = {
  version: 1,
  roles: {
    scout: {
      agent: "scout",
      candidates: [{ provider: "direct", model: "scout" }],
      fallback: "none",
    },
  },
};

describe("OpenCode plugin seam", () => {
  test("only exposes an explicit route tool and does not mutate model hooks", async () => {
    const hooks = await PilotfishOpenCodePlugin({} as never);

    expect(Object.keys(hooks)).toEqual(["tool"]);
    expect(hooks.tool?.pilotfish_route).toBeDefined();
  });

  test("reads customer-owned files and returns a redacted receipt", async () => {
    const directory = join("/tmp", `pilotfish-opencode-${crypto.randomUUID()}`);
    await mkdir(join(directory, ".opencode", "pilotfish"), { recursive: true });
    await Bun.write(
      join(directory, ".opencode", "pilotfish", "catalog.json"),
      JSON.stringify(catalog),
    );
    await Bun.write(
      join(directory, ".opencode", "pilotfish", "routing.json"),
      JSON.stringify(routing),
    );

    try {
      const routeTool = createPilotfishRouteTool();
      const result = await routeTool.execute(
        { role: "scout" },
        {
          worktree: directory,
          directory,
          sessionID: "test",
          messageID: "test",
          agent: "scout",
          abort: new AbortController().signal,
          metadata: () => undefined,
          ask: async () => undefined,
        },
      );

      expect(typeof result).toBe("object");
      if (typeof result !== "string") {
        expect(result.output).toContain('"provider":"direct"');
        expect(result.output).not.toContain("api_key");
      }
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  test("uses native agent model metadata when the optional overlay is absent", async () => {
    const directory = join("/tmp", `pilotfish-opencode-native-${crypto.randomUUID()}`);
    await mkdir(join(directory, ".opencode", "pilotfish"), { recursive: true });
    await Bun.write(
      join(directory, ".opencode", "pilotfish", "catalog.json"),
      JSON.stringify({
        ...catalog,
        agents: {
          scout: {
            mode: "subagent",
            available: true,
            model: { provider: "direct", model: "scout" },
          },
        },
      }),
    );

    try {
      const routeTool = createPilotfishRouteTool();
      const result = await routeTool.execute(
        { role: "scout" },
        {
          worktree: directory,
          directory,
          sessionID: "test",
          messageID: "test",
          agent: "scout",
          abort: new AbortController().signal,
          metadata: () => undefined,
          ask: async () => undefined,
        },
      );

      expect(typeof result).toBe("object");
      if (typeof result !== "string") {
        expect(result.output).toContain('"source":"agent_config"');
      }
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

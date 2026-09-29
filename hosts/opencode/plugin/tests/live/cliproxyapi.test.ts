import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const liveTest = process.env.PILOTFISH_CLIPROXYAPI_LIVE === "1" ? test : test.skip;
const repository = join(import.meta.dir, "../..");
const installer = join(repository, "install", "install.sh");

describe("CLIProxyAPI custom-provider smoke", () => {
  liveTest("runs a role session through the configured local endpoint", async () => {
    const apiKey = process.env.PILOTFISH_CLIPROXYAPI_KEY;
    if (apiKey === undefined || apiKey.length === 0) {
      throw new Error("PILOTFISH_CLIPROXYAPI_KEY is required for this live smoke");
    }

    const baseURL = (
      process.env.PILOTFISH_CLIPROXYAPI_URL ?? "http://127.0.0.1:8317/v1"
    ).replace(/\/$/, "");
    const modelsResponse = await fetch(`${baseURL}/models`, {
      headers: { authorization: `Bearer ${apiKey}` },
    });
    if (!modelsResponse.ok) {
      throw new Error(`CLIProxyAPI models probe returned HTTP ${modelsResponse.status}`);
    }
    const models = (await modelsResponse.json()) as {
      data?: Array<{ id?: string }>;
    };
    const model = process.env.PILOTFISH_CLIPROXYAPI_MODEL ?? models.data?.[0]?.id;
    if (
      model === undefined ||
      model.length === 0 ||
      /[\s\u0000-\u001f\u007f]/.test(model) ||
      model.includes("://")
    ) {
      throw new Error("CLIProxyAPI returned no usable model ID");
    }

    const target = await mkdtemp(join(tmpdir(), "pilotfish-opencode-cliproxyapi-"));
    const home = await mkdtemp(join(tmpdir(), "pilotfish-opencode-cliproxyapi-home-"));
    try {
      await mkdir(join(target, ".opencode", "pilotfish"), { recursive: true });
      await Bun.write(
        join(target, ".opencode", "opencode.json"),
        JSON.stringify({
          provider: {
            cliproxyapi: {
              npm: "@ai-sdk/openai-compatible",
              options: {
                baseURL,
                apiKey: "{env:PILOTFISH_CLIPROXYAPI_KEY}",
              },
              models: { [model]: { name: "CLIProxyAPI live model" } },
            },
          },
        }),
      );
      await Bun.write(
        join(target, ".opencode", "pilotfish", "catalog.json"),
        JSON.stringify({
          agents: {
            scout: {
              mode: "subagent",
              available: true,
              model: { provider: "cliproxyapi", model },
            },
          },
          providers: {
            cliproxyapi: {
              authenticated: true,
              identity: "proxy-resolved",
              models: {
                [model]: {
                  capabilities: {
                    supported: ["tools", "streaming"],
                    source: "live",
                  },
                },
              },
            },
          },
        }),
      );

      const installed = Bun.spawnSync(["sh", installer, "--target", target, "--enable"], {
        cwd: repository,
        stdout: "pipe",
        stderr: "pipe",
      });
      expect(installed.exitCode).toBe(0);

      const opencode = Bun.which("opencode");
      if (opencode === null) throw new Error("opencode is required for the live smoke");
      const reservation = Bun.serve({ port: 0, fetch: () => new Response() });
      const serverPort = reservation.port;
      reservation.stop();
      let opencodeServer: Bun.Subprocess | undefined;
      opencodeServer = Bun.spawn(
        [opencode, "serve", "--hostname", "127.0.0.1", "--port", String(serverPort), "--log-level", "ERROR"],
        {
          cwd: target,
          env: {
            PATH: process.env.PATH ?? "",
            HOME: home,
            XDG_CONFIG_HOME: join(home, ".config"),
            XDG_DATA_HOME: join(home, ".local", "share"),
            XDG_CACHE_HOME: join(home, ".cache"),
            NO_COLOR: "1",
            PILOTFISH_CLIPROXYAPI_KEY: apiKey,
          },
          stdout: "ignore",
          stderr: "ignore",
        },
      );
      try {
        const apiBase = `http://127.0.0.1:${serverPort}`;
        let healthy = false;
        for (let attempt = 0; attempt < 30; attempt += 1) {
          try {
            const health = await fetch(`${apiBase}/global/health`, {
              signal: AbortSignal.timeout(500),
            });
            if (health.ok) {
              healthy = true;
              break;
            }
          } catch {
            await new Promise((resolve) => setTimeout(resolve, 250));
          }
        }
        if (!healthy) throw new Error("OpenCode server did not become healthy");

        const directory = encodeURIComponent(target);
        const sessionResponse = await fetch(`${apiBase}/session?directory=${directory}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            agent: "scout",
            model: { providerID: "cliproxyapi", id: model },
          }),
        });
        if (!sessionResponse.ok) {
          throw new Error(`OpenCode CLIProxyAPI session creation returned HTTP ${sessionResponse.status}`);
        }
        const session = (await sessionResponse.json()) as { id?: string };
        if (session.id === undefined) throw new Error("OpenCode returned no session ID");

        const messageResponse = await fetch(
          `${apiBase}/session/${encodeURIComponent(session.id)}/message?directory=${directory}`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              agent: "scout",
              model: { providerID: "cliproxyapi", modelID: model },
              parts: [{ type: "text", text: "Reply with one short confirmation" }],
            }),
            signal: AbortSignal.timeout(90_000),
          },
        );
        if (!messageResponse.ok) {
          throw new Error(`OpenCode CLIProxyAPI role session returned HTTP ${messageResponse.status}`);
        }
      } finally {
        opencodeServer.kill();
        await opencodeServer.exited;
      }
    } finally {
      await rm(target, { recursive: true, force: true });
      await rm(home, { recursive: true, force: true });
    }
  }, 120_000);
});

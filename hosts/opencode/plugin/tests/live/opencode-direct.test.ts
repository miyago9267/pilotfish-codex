import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const liveTest = process.env.PILOTFISH_OPENCODE_LIVE === "1" ? test : test.skip;
const repository = join(import.meta.dir, "../..");
const installer = join(repository, "install", "install.sh");

function streamResponse(chunks: unknown[]): Response {
  const body = `${chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("")}data: [DONE]\n\n`;
  return new Response(body, {
    headers: { "content-type": "text/event-stream" },
  });
}

describe("OpenCode direct-provider smoke", () => {
  liveTest("runs a role session through a local OpenAI-compatible provider", async () => {
    let requestSeen = false;
    let routeToolSeen = false;
    let routeReceiptSeen = false;
    let routeCallIssued = false;
    const modelIds: string[] = [];
    const provider = Bun.serve({
      port: 0,
      async fetch(request) {
        const url = new URL(request.url);
        if (url.pathname.endsWith("/models")) {
          return Response.json({
            object: "list",
            data: [{ id: "scout", object: "model", owned_by: "fixture" }],
          });
        }
        if (request.method === "POST" && url.pathname.endsWith("/chat/completions")) {
          requestSeen = true;
          const payload = (await request.json()) as {
            model?: unknown;
            stream?: boolean;
            tools?: Array<{ function?: { name?: string } }>;
          };
          if (typeof payload.model === "string") modelIds.push(payload.model);
          const hasRouteTool = payload.tools?.some(
            (item) => item.function?.name === "pilotfish_route",
          ) ?? false;
          routeToolSeen ||= hasRouteTool;
          if (!hasRouteTool) {
            return Response.json({
              id: "chatcmpl-pilotfish-title",
              object: "chat.completion",
              created: 1,
              model: "scout",
              choices: [
                {
                  index: 0,
                  message: { role: "assistant", content: "SCOUT_TITLE" },
                  finish_reason: "stop",
                },
              ],
            });
          }
          if (!routeCallIssued) {
            routeCallIssued = true;
            const toolCall = {
              id: "call_pilotfish_route",
              type: "function",
              function: {
                name: "pilotfish_route",
                arguments: JSON.stringify({ role: "scout" }),
              },
            };
            if (payload.stream === true) {
              return streamResponse([
                {
                  id: "chatcmpl-pilotfish-route",
                  object: "chat.completion.chunk",
                  created: 1,
                  model: "scout",
                  choices: [{ index: 0, delta: { role: "assistant", tool_calls: [{ index: 0, ...toolCall }] }, finish_reason: null }],
                },
                {
                  id: "chatcmpl-pilotfish-route",
                  object: "chat.completion.chunk",
                  created: 1,
                  model: "scout",
                  choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
                },
              ]);
            }
            return Response.json({
              id: "chatcmpl-pilotfish-route",
              object: "chat.completion",
              created: 1,
              model: "scout",
              choices: [
                {
                  index: 0,
                  message: {
                    role: "assistant",
                    content: null,
                    tool_calls: [toolCall],
                  },
                  finish_reason: "tool_calls",
                },
              ],
            });
          }
          const serializedPayload = JSON.stringify(payload);
          routeReceiptSeen =
            serializedPayload.includes("source") && serializedPayload.includes("agent_config");
          return Response.json({
            id: "chatcmpl-pilotfish-fixture",
            object: "chat.completion",
            created: 1,
            model: "scout",
            choices: [
              {
                index: 0,
                message: { role: "assistant", content: "SCOUT_OK" },
                finish_reason: "stop",
              },
            ],
            usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          });
        }
        return new Response("not found", { status: 404 });
      },
    });

    const target = await mkdtemp(join(tmpdir(), "pilotfish-opencode-live-"));
    const home = await mkdtemp(join(tmpdir(), "pilotfish-opencode-live-home-"));
    let opencodeServer: Bun.Subprocess | undefined;
    try {
      await mkdir(join(target, ".opencode", "pilotfish"), { recursive: true });
      await Bun.write(
        join(target, ".opencode", "opencode.json"),
        JSON.stringify({
          provider: {
            fixture: {
              npm: "@ai-sdk/openai-compatible",
              options: {
                baseURL: `http://127.0.0.1:${provider.port}/v1`,
                apiKey: "fixture-only",
              },
              models: { scout: { name: "Fixture Scout" } },
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
              model: { provider: "fixture", model: "scout" },
            },
          },
          providers: {
            fixture: {
              authenticated: true,
              identity: "direct",
              models: {
                scout: {
                  capabilities: { supported: ["tools", "streaming"], source: "live" },
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
          },
          stdout: "ignore",
          stderr: "ignore",
        },
      );
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
          model: { providerID: "fixture", id: "scout" },
        }),
      });
      if (!sessionResponse.ok) {
        throw new Error(`OpenCode subagent session creation returned HTTP ${sessionResponse.status}`);
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
            model: { providerID: "fixture", modelID: "scout" },
            parts: [{ type: "text", text: "Return exactly SCOUT_OK" }],
          }),
        },
      );
      if (!messageResponse.ok) {
        throw new Error(`OpenCode subagent message returned HTTP ${messageResponse.status}`);
      }
      const requestsBeforeExistingMessage = modelIds.length;
      const existingMessageResponse = await fetch(
        `${apiBase}/session/${encodeURIComponent(session.id)}/message?directory=${directory}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            agent: "scout",
            model: { providerID: "fixture", modelID: "scout" },
            parts: [{ type: "text", text: "Return exactly EXISTING_OK" }],
          }),
        },
      );
      if (!existingMessageResponse.ok) {
        throw new Error(`OpenCode existing subagent message returned HTTP ${existingMessageResponse.status}`);
      }
      expect(requestSeen).toBe(true);
      expect(routeToolSeen).toBe(true);
      expect(routeReceiptSeen).toBe(true);
      expect(modelIds.length).toBeGreaterThan(requestsBeforeExistingMessage);
      expect(modelIds.every((modelId) => modelId === "scout")).toBe(true);
    } finally {
      opencodeServer?.kill();
      if (opencodeServer !== undefined) await opencodeServer.exited;
      provider.stop();
      await rm(target, { recursive: true, force: true });
      await rm(home, { recursive: true, force: true });
    }
  }, 60_000);
});

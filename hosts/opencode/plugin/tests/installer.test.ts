import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const repository = join(import.meta.dir, "..");
const installer = join(repository, "install", "install.sh");

function runInstaller(target: string, action: string) {
  return Bun.spawnSync(["sh", installer, "--target", target, action], {
    cwd: repository,
    stdout: "pipe",
    stderr: "pipe",
  });
}

describe("opt-in installer", () => {
  test("supports idempotent enable, disable, and rollback in a fresh target", async () => {
    const target = await mkdtemp(join(tmpdir(), "pilotfish-opencode-installer-"));

    try {
      expect(runInstaller(target, "--enable").exitCode).toBe(0);
      expect(await Bun.file(join(target, ".opencode", "agents", "scout.md")).exists()).toBe(true);
      expect(
        await Bun.file(join(target, ".opencode", "plugins", "pilotfish-opencode.js")).exists(),
      ).toBe(true);

      const repeat = runInstaller(target, "--enable");
      expect(repeat.exitCode).toBe(0);

      const nativeConfig = join(target, ".opencode", "opencode.json");
      const nativeConfigContent = '{"provider":{"customer":{"models":{}}}}\n';
      await Bun.write(nativeConfig, nativeConfigContent);
      expect(runInstaller(target, "--disable").exitCode).toBe(0);
      expect(await Bun.file(join(target, ".opencode", "agents", "scout.md")).exists()).toBe(false);
      expect(await Bun.file(nativeConfig).text()).toBe(nativeConfigContent);
      expect((await readFile(join(target, ".opencode", "pilotfish", "install.manifest"), "utf8"))).toContain(
        "state|disabled",
      );

      expect(runInstaller(target, "--rollback").exitCode).toBe(0);
      expect(await Bun.file(join(target, ".opencode", "agents", "scout.md")).exists()).toBe(false);
      expect(await Bun.file(nativeConfig).text()).toBe(nativeConfigContent);
      expect((await readFile(join(target, ".opencode", "pilotfish", "install.manifest"), "utf8"))).toContain(
        "state|rolled_back",
      );
    } finally {
      await rm(target, { recursive: true, force: true });
    }
  }, 30_000);
});

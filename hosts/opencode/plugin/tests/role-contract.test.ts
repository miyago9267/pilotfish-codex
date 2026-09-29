import { describe, expect, test } from "bun:test";
import {
  DEFAULT_ROLE_DEFINITIONS,
  RoleRegistry,
  createDefaultRoleRegistry,
} from "../src/role-contract.ts";

describe("role contract", () => {
  test("contains responsibility boundaries without runtime bindings", () => {
    expect(DEFAULT_ROLE_DEFINITIONS.length).toBe(5);

    for (const role of DEFAULT_ROLE_DEFINITIONS) {
      expect(role.id).toMatch(/^[a-z][a-z0-9-]*$/);
      expect(role.responsibility.length).toBeGreaterThan(0);
      expect(role.scope.length).toBeGreaterThan(0);
      expect(role.nonGoals.length).toBeGreaterThan(0);
      expect(role.input.length).toBeGreaterThan(0);
      expect(role.output.length).toBeGreaterThan(0);
      expect(role).not.toHaveProperty("provider");
      expect(role).not.toHaveProperty("model");
      expect(role).not.toHaveProperty("endpoint");
      expect(role).not.toHaveProperty("permission");
    }
  });

  test("keeps customer aliases outside the role definitions", () => {
    const registry = new RoleRegistry(DEFAULT_ROLE_DEFINITIONS, {
      Explore: "scout",
    });

    expect(registry.resolve("Explore")?.id).toBe("scout");
    expect(registry.resolve("scout")?.id).toBe("scout");
    expect(createDefaultRoleRegistry().resolve("Explore")).toBeUndefined();
  });
});

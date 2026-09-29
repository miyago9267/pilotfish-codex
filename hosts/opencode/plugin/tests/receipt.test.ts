import { describe, expect, test } from "bun:test";
import { createRouteReceipt } from "../src/receipt.ts";

describe("redacted route receipt", () => {
  test("contains route evidence but never prompt, credential, or endpoint data", () => {
    const receipt = createRouteReceipt({
      role: "verifier",
      agent: "verifier",
      requested: {
        provider: "openai",
        model: "gpt-test",
        variant: "high",
      },
      resolved: {
        provider: "cliproxyapi",
        model: "gpt-test",
        variant: "high",
        source: "fallback",
      },
      fallback: "ordered_candidates",
      capabilityStatus: "override",
      providerIdentity: "proxy-resolved",
    });

    expect(receipt).toEqual({
      version: 1,
      role: "verifier",
      agent: "verifier",
      requested: {
        provider: "openai",
        model: "gpt-test",
        variant: "high",
      },
      resolved: {
        provider: "cliproxyapi",
        model: "gpt-test",
        variant: "high",
        source: "fallback",
      },
      fallback: "ordered_candidates",
      capability_status: "override",
      provider_identity: "proxy-resolved",
    });

    const serialized = JSON.stringify(receipt);
    expect(serialized).not.toContain("prompt");
    expect(serialized).not.toContain("transcript");
    expect(serialized).not.toContain("api_key");
    expect(serialized).not.toContain("https://");
  });
});

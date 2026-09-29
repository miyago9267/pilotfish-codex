export type RoleDefinition = {
  readonly id: string;
  readonly responsibility: string;
  readonly scope: readonly string[];
  readonly nonGoals: readonly string[];
  readonly input: readonly string[];
  readonly output: readonly string[];
};

export type RoleAliases = Readonly<Record<string, string>>;

function assertRoleId(id: string, label: string): void {
  if (!/^[a-z][a-z0-9-]*$/.test(id)) {
    throw new TypeError(`${label} must be a lowercase role id`);
  }
}

function assertNonEmptyList(values: readonly string[], label: string): void {
  if (
    values.length === 0 ||
    values.some((value) => typeof value !== "string" || value.trim().length === 0)
  ) {
    throw new TypeError(`${label} must contain non-empty strings`);
  }
}

function validateDefinition(role: RoleDefinition): void {
  assertRoleId(role.id, "role id");
  for (const [value, label] of [
    [role.responsibility, "responsibility"],
  ] as const) {
    if (typeof value !== "string" || value.trim().length === 0) {
      throw new TypeError(`${label} must be non-empty`);
    }
  }
  assertNonEmptyList(role.scope, `${role.id}.scope`);
  assertNonEmptyList(role.nonGoals, `${role.id}.nonGoals`);
  assertNonEmptyList(role.input, `${role.id}.input`);
  assertNonEmptyList(role.output, `${role.id}.output`);
}

function validateAliases(aliases: RoleAliases): void {
  for (const [alias, target] of Object.entries(aliases)) {
    if (alias.trim().length === 0 || target.trim().length === 0) {
      throw new TypeError("role aliases must have non-empty names and targets");
    }
  }
}

export class RoleRegistry {
  private readonly definitions: ReadonlyMap<string, RoleDefinition>;
  private readonly aliases: RoleAliases;

  constructor(
    definitions: readonly RoleDefinition[],
    aliases: RoleAliases = {},
  ) {
    const map = new Map<string, RoleDefinition>();
    for (const role of definitions) {
      validateDefinition(role);
      if (map.has(role.id)) {
        throw new TypeError(`duplicate role id: ${role.id}`);
      }
      map.set(role.id, role);
    }
    validateAliases(aliases);
    this.definitions = map;
    this.aliases = { ...aliases };
  }

  canonicalize(id: string, extraAliases: RoleAliases = {}): string | undefined {
    if (typeof id !== "string" || id.trim().length === 0) return undefined;

    const aliases = { ...this.aliases, ...extraAliases };
    validateAliases(extraAliases);

    let current = id;
    const seen = new Set<string>();
    while (aliases[current] !== undefined) {
      if (seen.has(current)) {
        throw new TypeError(`role alias cycle includes ${current}`);
      }
      seen.add(current);
      current = aliases[current];
    }
    return current;
  }

  resolve(id: string, extraAliases: RoleAliases = {}): RoleDefinition | undefined {
    const canonical = this.canonicalize(id, extraAliases);
    return canonical === undefined ? undefined : this.definitions.get(canonical);
  }

  has(id: string, extraAliases: RoleAliases = {}): boolean {
    return this.resolve(id, extraAliases) !== undefined;
  }

  list(): readonly RoleDefinition[] {
    return [...this.definitions.values()];
  }
}

export const DEFAULT_ROLE_DEFINITIONS: readonly RoleDefinition[] = [
  {
    id: "scout",
    responsibility: "Bounded read-only reconnaissance and evidence collection.",
    scope: ["locate files, symbols, configuration, or documented behavior"],
    nonGoals: ["make decisions", "edit files", "claim that an unverified fact is correct"],
    input: ["a focused question", "allowed paths", "an evidence stop condition"],
    output: ["scope", "files or sources read", "findings", "evidence", "uncertainty", "next action"],
  },
  {
    id: "executor",
    responsibility: "Implementation of an approved and stable work contract.",
    scope: ["change only the assigned files or modules", "run the required bounded checks"],
    nonGoals: ["expand the contract", "choose a different architecture without escalation"],
    input: ["approved objective", "exclusive ownership", "constraints", "done criteria"],
    output: ["changed paths", "behavior", "verification", "remaining risk"],
  },
  {
    id: "verifier",
    responsibility: "Fresh-context attempt to refute a claimed implementation outcome.",
    scope: ["read the relevant diff or paths", "run targeted checks", "probe important edge cases"],
    nonGoals: ["edit or repair the implementation", "replace the main session's final judgment"],
    input: ["claimed outcome", "relevant paths", "acceptance checks"],
    output: ["CONFIRMED or REFUTED", "evidence", "unverified claims", "next action"],
  },
  {
    id: "security-reviewer",
    responsibility: "Read-only security evidence and threat review before approval.",
    scope: ["inspect auth, secrets, validation, permissions, and dependency surfaces"],
    nonGoals: ["write a fix", "grant permissions", "treat unknown capability as safe"],
    input: ["security question", "threat boundary", "relevant paths"],
    output: ["findings", "attack or misuse paths", "evidence", "severity", "REVISE or READY"],
  },
  {
    id: "security-executor",
    responsibility: "Approved security-sensitive implementation under a narrow contract.",
    scope: ["apply the approved security change", "run the required security checks"],
    nonGoals: ["weaken controls for convenience", "rotate or expose credentials", "expand access"],
    input: ["approved security plan", "ownership boundary", "done criteria", "rollback"],
    output: ["changed paths", "security behavior", "verification", "residual risk"],
  },
] as const;

export function createDefaultRoleRegistry(): RoleRegistry {
  return new RoleRegistry(DEFAULT_ROLE_DEFINITIONS);
}

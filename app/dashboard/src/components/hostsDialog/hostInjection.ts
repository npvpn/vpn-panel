import { z } from "zod";

export function previewDraftHosts(
  rows: Record<string, any>[],
  completeCatalog: boolean
) {
  return rows
    .map((host, index) =>
      previewHost(completeCatalog ? { ...host, order: index } : host)
    )
    .filter((host) => host.id !== null);
}

export function previewExcludedIds(
  saved: Record<string, any[]>,
  rows: Record<string, any>[],
  completeCatalog: boolean
): number[] {
  if (!completeCatalog) return [];
  const retained = new Set(rows.map((host) => host.host_id));
  return Object.values(saved)
    .flat()
    .map((host) => host.id)
    .filter((id): id is number => typeof id === "number" && !retained.has(id));
}

// Only selector metadata crosses the diagnostics API; no keys or connection credentials.
export function previewHost(host: Record<string, any>) {
  return {
    id:
      typeof host.host_id === "number"
        ? host.host_id
        : typeof host.id === "number"
        ? host.id
        : null,
    inbound_tag: host.inbound_tag || "",
    remark: host.remark || "",
    group_tag: host.group_tag || "",
    is_disabled: !!host.is_disabled,
    is_hidden: !!host.is_hidden,
    order: host.order || 0,
    client_config_id: host.client_config_id ?? null,
    host_injection: host.host_injection ?? null,
  };
}

const selectorSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("ids"),
      values: z
        .array(z.number().int().positive())
        // ключ перевода: сообщение zod по умолчанию — техническое и только по-английски
        .min(1, "hostsDialog.injection.errors.noHosts")
        .max(256)
        .refine((v) => new Set(v).size === v.length, "Host IDs must be unique"),
    })
    .strict(),
  z
    .object({
      type: z.literal("remarkRegex"),
      pattern: z
        .string()
        .min(1, "hostsDialog.injection.errors.noPattern")
        .max(256),
    })
    .strict(),
  z
    .object({
      type: z.literal("tagRegex"),
      pattern: z
        .string()
        .min(1, "hostsDialog.injection.errors.noPattern")
        .max(256),
    })
    .strict(),
  z.object({ type: z.literal("sameTagAsRecipient") }).strict(),
]);
export const injectionGroupSchema = z
  .object({
    selector: selectorSchema,
    selectFrom: z.enum(["HIDDEN", "NOT_HIDDEN", "ALL"]).default("HIDDEN"),
    tagPrefix: z
      .string()
      .min(1)
      .max(128)
      .refine((v) => !!v.trim())
      .nullable()
      .default(null),
    useHostRemarkAsTag: z.boolean().default(false),
    useHostTagAsTag: z.boolean().default(false),
  })
  .strict()
  .refine(
    (v) =>
      Number(v.tagPrefix !== null) +
        Number(v.useHostRemarkAsTag) +
        Number(v.useHostTagAsTag) ===
      1,
    "Choose exactly one tagging mode"
  );
export const injectionSchema = z
  .object({
    enabled: z.boolean().default(true),
    injectHosts: z.array(injectionGroupSchema).max(32).default([]),
    addVirtualHostAsOutbound: z.boolean().default(false),
  })
  .strict()
  .superRefine((v, ctx) => {
    if (v.enabled && !v.injectHosts.length && !v.addVirtualHostAsOutbound)
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Select source hosts or include own connection",
      });
    if (!v.enabled && (v.injectHosts.length || v.addVirtualHostAsOutbound))
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Disabled injection must not have groups",
      });
  });
export type HostInjection = z.infer<typeof injectionSchema>;
export type InjectionGroup = z.infer<typeof injectionGroupSchema>;
export const newInjectionGroup = (): InjectionGroup => ({
  selector: { type: "ids", values: [] },
  selectFrom: "ALL",
  tagPrefix: "proxy",
  useHostRemarkAsTag: false,
  useHostTagAsTag: false,
});

type InjectionTemplate = {
  id: number;
  slug: string;
  body: string;
  effective_injection?: unknown;
  effective_injection_error?: boolean;
};

export function templateInjection(
  host: { client_config_id?: number | null },
  templates: InjectionTemplate[]
): HostInjection | null {
  const chosen = templates.find((t) => t.id === host.client_config_id);
  const fallback = templates.find((t) => t.slug === "default");
  const resolved = chosen || fallback;
  if (resolved?.effective_injection_error)
    throw new Error("Invalid template injection");
  if (resolved && "effective_injection" in resolved)
    return resolved.effective_injection == null
      ? null
      : injectionSchema.parse(resolved.effective_injection);
  const body = (chosen?.body.trim() ? chosen.body : fallback?.body) || "{}";
  const document = JSON.parse(body);
  if ("npvpn" in document && "remnawave" in document)
    throw new Error("Choose npvpn or remnawave, not both");
  const directive = document.npvpn ?? document.remnawave;
  return directive === undefined ? null : injectionSchema.parse(directive);
}
export function effectiveInjection(
  host: { host_injection?: unknown; client_config_id?: number | null },
  templates: InjectionTemplate[]
): HostInjection | null {
  const value =
    host.host_injection == null
      ? templateInjection(host, templates)
      : injectionSchema.parse(host.host_injection);
  return value?.enabled ? value : null;
}

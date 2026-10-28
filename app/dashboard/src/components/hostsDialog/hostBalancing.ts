import { z } from "zod";

const units: Record<string, number> = { ns: 1e-9, us: 1e-6, "µs": 1e-6, "μs": 1e-6, ms: 1e-3, s: 1, m: 60, h: 3600 };
export function durationSeconds(value: string): number {
  if (value === "0") return 0;
  const parts = [...value.matchAll(/(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)/g)];
  if (!parts.length || parts.map(p => p[0]).join("") !== value) return NaN;
  return parts.reduce((sum, p) => sum + Number(p[1]) * units[p[2]], 0);
}
const duration = (min: number, inclusive = false) => z.string().refine(value => {
  const seconds = durationSeconds(value);
  return Number.isFinite(seconds) && seconds <= 9223372036.854775807 && (inclusive ? seconds >= min : seconds > min);
}, { message: min === 10 ? "hostsDialog.balancing.errors.minDuration" : "hostsDialog.balancing.errors.invalidDuration" });
const url = z.string().url().refine(v => /^https?:\/\//i.test(v), "Use an HTTP(S) URL");
const integer = z.number().int().max(2147483647);
const pingProbe = z.object({ url, interval: duration(0), enableConcurrency: z.boolean() }).strict();
const burstProbe = z.object({ url, interval: duration(10, true), timeout: duration(0), sampling: integer.min(1), connectivity: z.union([z.literal(""), url]) }).strict();
export const balancingSchema = z.discriminatedUnion("strategy", [
  z.object({ strategy: z.literal("random"), settings: z.null().optional(), probe: z.null().optional() }).strict(),
  z.object({ strategy: z.literal("roundRobin"), settings: z.null().optional(), probe: z.null().optional() }).strict(),
  z.object({ strategy: z.literal("leastPing"), settings: z.null().optional(), probe: pingProbe }).strict(),
  z.object({ strategy: z.literal("leastLoad"), settings: z.object({
    expected: integer.min(0), maxRTT: duration(0, true), tolerance: z.number().min(0).max(1),
    baselines: z.array(duration(0)),
    costs: z.array(z.object({ match: z.string().min(1), regexp: z.boolean(), value: z.number().finite().positive() }).strict()),
  }).strict(), probe: burstProbe }).strict(),
]);
export function hasActiveEntryNodes(ids: number[], nodes: { id?: number | null; status?: string | null }[]): boolean {
  return nodes.some(node => node.id != null && ids.includes(node.id) && node.status !== "disabled");
}
export type HostBalancing = z.infer<typeof balancingSchema>;
export function balancingDefaults(strategy: string): HostBalancing | null {
  const probe = { url: "https://www.google.com/generate_204", interval: "15s" };
  switch (strategy) {
    case "random": case "roundRobin": return { strategy, settings: null, probe: null };
    case "leastPing": return { strategy, settings: null, probe: { ...probe, enableConcurrency: false } };
    case "leastLoad": return { strategy, settings: { expected: 2, maxRTT: "1s", tolerance: 0.1, baselines: [], costs: [] }, probe: { ...probe, timeout: "3s", sampling: 3, connectivity: "" } };
    default: return null;
  }
}

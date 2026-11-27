import { FetchError } from "ofetch";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { z } from "zod";
import { fetch } from "./http";

const targetSchema = z.object({
  address: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  exit_node_id: z.number().int().positive(),
  inbound_tag: z.string().min(1),
});
export type RouteTarget = z.infer<typeof targetSchema>;

const intentSchema = z.object({
  operation_id: z.string().uuid(),
  expected_revision: z.number().int().nonnegative(),
  target: z.string().min(1),
  enabled: z.boolean(),
  expected_destination: targetSchema.optional(),
});
type RouteIntent = z.infer<typeof intentSchema>;
export type RouteChange = Omit<RouteIntent, "operation_id" | "expected_destination"> & {
  expected_destination: RouteTarget;
};

type RouteState = {
  revision: number;
  target: string | null;
  enabled: boolean;
  listen_address: string;
  listen_port: number;
  targets: Record<string, RouteTarget>;
  confirmed_destination?: RouteTarget | null;
  listener: "up" | "down" | "external" | "unknown";
  backend: "up" | "down" | "unknown";
};
type Operation = Omit<RouteIntent, "expected_destination"> & {
  revision: number | null;
  outcome: "applied" | "rejected" | "pending" | "rollback_failed";
  detail: string;
  operator: string;
  created_at: string;
  target_address: string;
  target_port: number;
  exit_node_id: number;
  inbound_tag: string;
};
type Snapshot = {
  supported: boolean;
  state: RouteState | null;
  history: Operation[];
};

export function recordedDestination(record: Operation): RouteTarget {
  return {
    address: record.target_address,
    port: record.target_port,
    exit_node_id: record.exit_node_id,
    inbound_tag: record.inbound_tag,
  };
}

export function confirmedDestination(state: RouteState) {
  return state.confirmed_destination ?? (state.target ? state.targets[state.target] : undefined);
}

export function alreadyEnabled(state: RouteState, key: string) {
  const active = confirmedDestination(state);
  const selected = state.targets[key];
  return state.enabled && state.target === key && active && selected &&
    active.address === selected.address && active.port === selected.port &&
    active.exit_node_id === selected.exit_node_id && active.inbound_tag === selected.inbound_tag;
}

export function canRestore(record: Operation, state: RouteState) {
  const disablesCurrent = !record.enabled && record.target === state.target;
  if ((record.enabled && alreadyEnabled(state, record.target)) || (disablesCurrent && !state.enabled)) {
    return false;
  }
  const target = disablesCurrent ? confirmedDestination(state) : state.targets[record.target];
  return record.outcome === "applied" && record.revision !== null &&
    record.revision < state.revision &&
    target && target.address === record.target_address && target.port === record.target_port &&
    target.exit_node_id === record.exit_node_id && target.inbound_tag === record.inbound_tag;
}

function readIntent(key: string): RouteIntent | null {
  try {
    const saved = sessionStorage.getItem(key);
    if (!saved) return null;
    return intentSchema.parse(JSON.parse(saved));
  } catch {
    return null;
  }
}

export function errorDetail(error: unknown) {
  if (error instanceof FetchError && typeof error.data?.detail === "string") {
    return error.data.detail;
  }
  return error instanceof Error ? error.message : "";
}

// getRandomValues also works on plain HTTP in a local panel installation.
function operationId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

export function usePilotRoute(nodeId: number, operator: string) {
  const path = `/node/${nodeId}/haproxy-pilot`;
  const queryKey = ["haproxy-pilot", operator, nodeId];
  const storageKey = JSON.stringify([import.meta.env.VITE_BASE_API, ...queryKey]);
  const client = useQueryClient();
  const [saved, setSaved] = useState(() => readIntent(storageKey));
  const query = useQuery(queryKey, () => fetch<Snapshot>(path, { retry: 0 }), {
    retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
  });
  const history = query.data?.history || [];
  const completed = saved && history.some(record =>
    record.operation_id === saved.operation_id && record.outcome !== "pending"
  );
  useEffect(() => {
    if (completed && readIntent(storageKey)?.operation_id === saved?.operation_id) {
      sessionStorage.removeItem(storageKey);
      setSaved(null);
    }
  }, [completed, saved, storageKey]);

  const mutation = useMutation(async (intent: RouteIntent) => {
    // Strip server-only journal fields while preserving the authorized destination.
    const body = intentSchema.parse(intent);
    sessionStorage.setItem(storageKey, JSON.stringify(body));
    setSaved(body);
    return fetch<Snapshot>(path, { method: "POST", body, retry: 0 });
  }, {
    retry: false,
    onSuccess: async (data) => {
      await client.cancelQueries(queryKey);
      client.setQueryData(queryKey, data);
    },
    onError: async (error, intent) => {
      if (error instanceof FetchError && [400, 403, 404, 409, 422].includes(error.statusCode || 0) &&
          readIntent(storageKey)?.operation_id === intent.operation_id) {
        sessionStorage.removeItem(storageKey);
        setSaved(null);
      }
      await client.invalidateQueries(queryKey);
    },
  });
  const journalPending = history.find(record => record.outcome === "pending");
  const pending = journalPending
    ? { ...journalPending, expected_destination: recordedDestination(journalPending) }
    : (!completed && saved) || null;
  const state = query.isSuccess ? query.data.state : null;
  const busy = query.isFetching || mutation.isLoading;

  const apply = (change: RouteChange) => {
    if (state && state.revision === change.expected_revision && !busy && !pending && state.listener !== "external") {
      mutation.mutate({ ...change, operation_id: operationId() });
    }
  };
  return {
    state, history, pending, busy, apply,
    supported: query.data?.supported,
    error: errorDetail(query.error) || errorDetail(mutation.error),
    loading: query.isLoading,
    refresh: () => { mutation.reset(); void query.refetch(); },
    retry: () => { if (pending && !busy) mutation.mutate(pending); },
  };
}

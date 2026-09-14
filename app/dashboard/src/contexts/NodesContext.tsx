import { useQuery } from "react-query";
import { fetch } from "service/http";
import { z } from "zod";
import { create } from "zustand";
import { FilterUsageType, useDashboard } from "./DashboardContext";

/** SI ТБ, как у хостеров в счетах (не TiB). */
export const SI_TB_BYTES = 1_000_000_000_000;

export function tbStringToBytes(raw: unknown): number | null {
  if (raw == null || raw === "") {
    return null;
  }
  const text = String(raw).trim().replace(",", ".");
  if (!text) {
    return null;
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  return Math.round(value * SI_TB_BYTES);
}

export function bytesToTbString(bytes: number | null | undefined): string {
  if (bytes == null || bytes <= 0) {
    return "";
  }
  return String(bytes / SI_TB_BYTES);
}

const hostingTrafficLimitTb = z
  .union([z.string(), z.number(), z.null()])
  .optional()
  .refine(
    (value) => {
      if (value == null || value === "") {
        return true;
      }
      const parsed = Number(String(value).trim().replace(",", "."));
      return Number.isFinite(parsed) && parsed > 0;
    },
    { message: "Must be a positive number in TB" }
  );

export const NodeSchema = z.object({
  name: z.string().min(1),
  address: z.string().min(1),
  port: z
    .number()
    .min(1)
    .or(z.string().transform((v) => parseFloat(v))),
  api_port: z
    .number()
    .min(1)
    .or(z.string().transform((v) => parseFloat(v))),
  protocol: z.enum(["rest", "rpyc"]),
  xray_version: z.string().nullable().optional(),
  id: z.number().nullable().optional(),
  status: z
    .enum(["connected", "connecting", "error", "disabled"])
    .nullable()
    .optional(),
  message: z.string().nullable().optional(),
  add_as_new_host: z.boolean().optional(),
  usage_coefficient: z.number().or(z.string().transform((v) => parseFloat(v))),
  inbounds: z.array(z.string()).optional(),
  role: z.enum(["entry", "exit", "direct"]).optional(),
  cascade_routes: z
    .array(
      z.object({
        exit_node_id: z.number().min(1),
        entry_inbound_tag: z.string().min(1),
        cascade_inbound_tag: z.string().min(1),
      })
    )
    .optional(),
  is_bs: z.boolean().optional(),
  cascade_balancer_strategy: z
    .enum(["random", "roundRobin", "leastPing", "leastLoad"])
    .optional(),
  hosting_traffic_limit_bytes: z.number().nullable().optional(),
  hosting_traffic_limit_tb: hostingTrafficLimitTb,
});

export type NodeType = z.infer<typeof NodeSchema>;

export const getNodeDefaultValues = (): NodeType => ({
  name: "",
  address: "",
  port: 62050,
  api_port: 62051,
  protocol: "rest",
  xray_version: "",
  usage_coefficient: 1,
  inbounds: [],
  role: "direct",
  cascade_routes: [],
  is_bs: false,
  cascade_balancer_strategy: "random",
  hosting_traffic_limit_bytes: null,
  hosting_traffic_limit_tb: "",
});

function withHostingLimitBytes(body: NodeType) {
  const { hosting_traffic_limit_tb, ...rest } = body;
  return {
    ...rest,
    hosting_traffic_limit_bytes: tbStringToBytes(hosting_traffic_limit_tb),
  };
}

export const FetchNodesQueryKey = "fetch-nodes-query-key";

export type NodeStore = {
  nodes: NodeType[];
  addNode: (node: NodeType) => Promise<unknown>;
  fetchNodes: () => Promise<NodeType[]>;
  fetchNodesUsage: (query: FilterUsageType) => Promise<void>;
  updateNode: (node: NodeType) => Promise<unknown>;
  reconnectNode: (node: NodeType) => Promise<unknown>;
  deletingNode?: NodeType | null;
  deleteNode: () => Promise<unknown>;
  setDeletingNode: (node: NodeType | null) => void;
};

export const useNodesQuery = () => {
  const { isEditingNodes } = useDashboard();
  return useQuery({
    queryKey: FetchNodesQueryKey,
    queryFn: useNodes.getState().fetchNodes,
    refetchInterval: isEditingNodes ? 3000 : undefined,
    refetchOnWindowFocus: false,
  });
};

export const useNodes = create<NodeStore>((set, get) => ({
  nodes: [],
  addNode(body) {
    return fetch("/node", { method: "POST", body: withHostingLimitBytes(body) });
  },
  fetchNodes() {
    return fetch("/nodes");
  },
  fetchNodesUsage(query: FilterUsageType) {
    return fetch("/nodes/usage", { query });
  },
  updateNode(body) {
    return fetch(`/node/${body.id}`, {
      method: "PUT",
      body: withHostingLimitBytes(body),
    });
  },
  setDeletingNode(node) {
    set({ deletingNode: node });
  },
  reconnectNode(body) {
    return fetch(`/node/${body.id}/reconnect`, {
      method: "POST",
    });
  },
  deleteNode: () => {
    return fetch(`/node/${get().deletingNode?.id}`, {
      method: "DELETE",
    });
  },
}));

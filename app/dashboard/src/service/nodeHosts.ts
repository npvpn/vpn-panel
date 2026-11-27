import { useQuery } from "react-query";
import { fetch } from "./http";

export type NodeHostRole = "direct" | "entry" | "exit" | "linked";

type HostWithRoles = {
  host_id: number;
  remark: string;
  roles: NodeHostRole[];
};

type NodeHost = HostWithRoles & {
  inbound_tag: string;
  is_disabled: boolean;
  sources: HostWithRoles[];
};

type NodeHostResponse = {
  hosts: NodeHost[];
  incomplete_host_ids: number[];
};

export const nodeHostsQueryKey = "node-hosts";

export function useNodeHosts(nodeId: number, operator: string) {
  return useQuery(
    [nodeHostsQueryKey, operator, nodeId],
    ({ signal }) => fetch<NodeHostResponse>(`/node/${nodeId}/hosts`, { signal, retry: 0 }),
    { cacheTime: 0, retry: false }
  );
}

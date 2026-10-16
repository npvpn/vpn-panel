import { PanelSettings, SubscriptionMessageServerField } from "types/PanelSettings";

export type HappPreviewScenario =
  | "normal"
  | "expired"
  | "revoked"
  | "unsupported"
  | "device"
  | "bs";

export type HappPreviewHost = {
  remark: string;
  is_disabled?: boolean | null;
  bot_usernames?: string[];
  node_ids?: number[];
  order?: number | null;
};

export type HappPreviewServer = {
  name: string;
  isStub: boolean;
};

const SCENARIO_SERVER_FIELD: Record<
  Exclude<HappPreviewScenario, "normal" | "bs">,
  SubscriptionMessageServerField
> = {
  expired: "sub_expired_server_text",
  revoked: "sub_revoked_server_text",
  unsupported: "sub_unsupported_client_server_text",
  device: "sub_device_limit_server_text",
};

const SCENARIO_ANNOUNCE_FIELD: Record<
  Exclude<HappPreviewScenario, "normal">,
  keyof PanelSettings
> = {
  expired: "sub_expired_announce_text",
  revoked: "sub_revoked_announce_text",
  unsupported: "sub_unsupported_client_announce_text",
  device: "sub_device_limit_announce_text",
  bs: "sub_bs_limit_announce_text",
};

export const FIELD_SCENARIO: Record<string, HappPreviewScenario> = {
  sub_client_note: "normal",
  sub_expired_announce_text: "expired",
  sub_expired_server_text: "expired",
  sub_revoked_announce_text: "revoked",
  sub_revoked_server_text: "revoked",
  sub_unsupported_client_announce_text: "unsupported",
  sub_unsupported_client_server_text: "unsupported",
  sub_device_limit_announce_text: "device",
  sub_device_limit_server_text: "device",
  sub_bs_limit_announce_text: "bs",
  sub_bs_limit_server_text: "bs",
};

export function flattenHosts(
  hostsByInbound: Record<string, HappPreviewHost[]>
): HappPreviewHost[] {
  const hosts: HappPreviewHost[] = [];
  for (const list of Object.values(hostsByInbound || {})) {
    if (!Array.isArray(list)) continue;
    hosts.push(...list);
  }
  return hosts.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
}

export function hostsForBot(
  hosts: HappPreviewHost[],
  botUsername: string,
  bsNodeIds: Set<number>
): Array<HappPreviewHost & { isBs: boolean }> {
  const username = botUsername.trim().toLowerCase();
  return hosts
    .filter((host) => !host.is_disabled)
    .filter((host) =>
      (host.bot_usernames || []).some(
        (name) => name.trim().toLowerCase() === username
      )
    )
    .map((host) => ({
      ...host,
      isBs: (host.node_ids || []).some((id) => bsNodeIds.has(id)),
    }));
}

export function bsStubRemark(lines: string[]): string {
  return lines.map((line) => line.trim()).filter(Boolean).join(" ");
}

export function previewAnnounce(
  settings: PanelSettings,
  scenario: HappPreviewScenario
): string {
  const fallback = substitutePlaceholders(settings.sub_client_note);
  if (scenario === "normal") return fallback;
  const key = SCENARIO_ANNOUNCE_FIELD[scenario];
  const text = substitutePlaceholders(String(settings[key] || ""));
  return text.trim() ? text : fallback;
}

export function previewServers(
  settings: PanelSettings,
  scenario: HappPreviewScenario,
  hosts: Array<HappPreviewHost & { isBs: boolean }>,
  deviceHardMode: boolean
): HappPreviewServer[] {
  if (scenario === "normal") {
    return hosts.map((host) => ({
      name: host.remark || "—",
      isStub: false,
    }));
  }
  if (scenario === "bs") {
    const stub = bsStubRemark(settings.sub_bs_limit_server_text) || "—";
    return hosts.map((host) =>
      host.isBs
        ? { name: stub, isStub: true }
        : { name: host.remark || "—", isStub: false }
    );
  }
  const lines = settings[SCENARIO_SERVER_FIELD[scenario]] || [];
  const stubs: HappPreviewServer[] = (lines.length ? lines : ["—"]).map(
    (name) => ({ name, isStub: true })
  );
  if (scenario === "device" && !deviceHardMode) {
    return [
      ...stubs,
      ...hosts.map((host) => ({ name: host.remark || "—", isStub: false })),
    ];
  }
  return stubs;
}

export function substitutePlaceholders(value: string): string {
  return (value || "")
    .replace(/<tg_id>/g, "420757333")
    .replace(/<days_left>/g, "7");
}

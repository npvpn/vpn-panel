/** Сериализация формы в PUT /api/hosts без неиспользуемых полей заглушки. */
export type HostForPayload = {
  inbound_tag: string;
  host_id?: number;
  remark: string;
  is_placeholder?: boolean;
  bot_usernames?: string[];
  xhttp_extra?: string | null;
  finalmask?: string | null;
  template_injection?: unknown;
  [key: string]: unknown;
};

export function groupHosts(
  hosts: HostForPayload[],
  inboundTags: string[]
): Record<string, any[]> {
  const payload: Record<string, any[]> = Object.fromEntries(
    inboundTags.map((tag) => [tag, [] as any[]])
  );

  hosts.forEach((host, index) => {
    const { inbound_tag, host_id, template_injection, ...rest } = host;
    if (!payload[inbound_tag]) payload[inbound_tag] = [];

    const identity = typeof host_id === "number" ? { id: host_id } : {};
    if (host.is_placeholder) {
      payload[inbound_tag].push({
        ...identity,
        order: index,
        remark: host.remark,
        is_placeholder: true,
        bot_usernames: host.bot_usernames ?? [],
      });
      return;
    }

    const finalmaskText = rest.finalmask ?? "";
    payload[inbound_tag].push({
      ...rest,
      ...identity,
      order: index,
      xhttp_extra: rest.xhttp_extra ? JSON.parse(rest.xhttp_extra) : null,
      finalmask: finalmaskText.trim() ? JSON.parse(finalmaskText) : null,
    });
  });

  return payload;
}

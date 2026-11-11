export function isSoloPanel(botCount: number): boolean {
  return botCount === 0;
}

export function isSingleSubscription(botCount: number): boolean {
  return botCount < 2;
}

export type PreviewHost = {
  remark?: string;
  is_disabled?: boolean | null;
  bot_usernames?: string[];
};

export function previewHostList<T extends PreviewHost>(
  hosts: T[],
  botCount: number,
  botUsername: string
): T[] {
  const enabled = hosts.filter((host) => !host.is_disabled);
  if (isSingleSubscription(botCount)) return enabled;
  const username = botUsername.trim().toLowerCase();
  return enabled.filter((host) =>
    (host.bot_usernames || []).some(
      (name) => name.trim().toLowerCase() === username
    )
  );
}

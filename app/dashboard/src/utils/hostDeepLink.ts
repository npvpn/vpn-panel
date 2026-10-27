/** Куда вести `#/?host=<username>`: модалка хостов, вкладка «По ботам», фильтр бота. */

export type HostDeepLinkPlan = {
  open: boolean;
  tabIndex: number;
  selectedBot: string;
};

export function normalizeHostUsername(raw: string | null | undefined): string {
  return (raw || "").trim().replace(/^@/, "");
}

export function planHostDeepLink(
  raw: string | null | undefined,
  botUsernames: string[]
): HostDeepLinkPlan {
  const username = normalizeHostUsername(raw);
  if (!username) {
    return { open: false, tabIndex: 0, selectedBot: "" };
  }
  // С одним ботом вкладки «По ботам» нет — открываем диалог как есть.
  if (botUsernames.length < 2) {
    return { open: true, tabIndex: 0, selectedBot: "" };
  }
  return {
    open: true,
    tabIndex: 1,
    selectedBot: botUsernames.includes(username) ? username : "",
  };
}

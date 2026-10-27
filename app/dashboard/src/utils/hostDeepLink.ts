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

export type HostDeepLinkUi = {
  pending: boolean;
  tabIndex: number;
  selectedBot: string;
};

/** Сброс формы при новом списке хостов. Пока план ссылки не применён, вкладку не трогаем. */
export function resetHostsFormTab(ui: HostDeepLinkUi): HostDeepLinkUi {
  if (ui.pending) return ui;
  return { ...ui, tabIndex: 0, selectedBot: "" };
}

/**
 * План применяется один раз, когда боты и хосты уже пришли.
 * Начальный `{}` в сторе — ещё не ответ `/hosts`.
 */
export function applyHostDeepLinkWhenReady(
  ui: HostDeepLinkUi,
  input: {
    username: string;
    botUsernames: string[];
    auxLoading: boolean;
    hostsRequestSettled: boolean;
  }
): HostDeepLinkUi {
  if (!ui.pending || input.auxLoading || !input.hostsRequestSettled) return ui;
  const plan = planHostDeepLink(input.username, input.botUsernames);
  return {
    pending: false,
    tabIndex: plan.tabIndex,
    selectedBot: plan.selectedBot,
  };
}

/** Порядок эффектов диалога: сброс формы, затем план. Пустой стор план не снимает. */
export function settleHostDeepLink(
  username: string,
  botUsernames: string[]
): HostDeepLinkUi {
  let ui: HostDeepLinkUi = { pending: true, tabIndex: 0, selectedBot: "" };
  ui = resetHostsFormTab(ui);
  ui = applyHostDeepLinkWhenReady(ui, {
    username,
    botUsernames,
    auxLoading: false,
    hostsRequestSettled: false,
  });
  ui = resetHostsFormTab(ui);
  return applyHostDeepLinkWhenReady(ui, {
    username,
    botUsernames,
    auxLoading: false,
    hostsRequestSettled: true,
  });
}

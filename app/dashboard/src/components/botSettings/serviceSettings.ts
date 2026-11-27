import type { Bot, BotSettings } from "types/Bot";

export type ServiceView =
  | { mode: "create"; returnTo: string }
  | { mode: "edit"; username: string };

export const serviceView = (
  username?: string | null,
  returnTo = ""
): ServiceView =>
  username ? { mode: "edit", username } : { mode: "create", returnTo };

export const cancelServiceCreation = (view: ServiceView): ServiceView | null =>
  view.mode === "create" && view.returnTo ? serviceView(view.returnTo) : null;

type ServiceDraft = {
  settings: BotSettings;
  botUsername: string;
  botTitle: string;
};

const getDraftKey = (username: string) => {
  if (!username) return "botSettings_create_draft";
  // The old key for `new` could contain either a creation or an edit draft.
  if (username === "new") return "botSettings_service_draft_new";
  return `botSettings_draft_${username}`;
};

export function saveServiceDraft(
  storage: Pick<Storage, "setItem">,
  username: string,
  draft: ServiceDraft
) {
  storage.setItem(
    getDraftKey(username),
    JSON.stringify({ ...draft, savedAt: Date.now() })
  );
}

export function readServiceDraft(
  storage: Pick<Storage, "getItem">,
  username: string
): ServiceDraft | null {
  const draft = storage.getItem(getDraftKey(username));
  if (!draft) return null;

  try {
    return JSON.parse(draft);
  } catch {
    return null;
  }
}

export function restoreServiceDraft(
  storage: Pick<Storage, "getItem">,
  username: string,
  serverSettings: BotSettings,
  service?: Bot
): ServiceDraft | null {
  const draft = readServiceDraft(storage, username);
  if (!draft || !(serverSettings.managed || service?.managed)) return draft;

  return {
    settings: {
      ...draft.settings,
      bot_url: serverSettings.bot_url,
      web_url: serverSettings.web_url,
      sub_support_url: serverSettings.sub_support_url,
      sub_subscription_domain: serverSettings.sub_subscription_domain,
      managed: serverSettings.managed,
    },
    botUsername: service?.username || "",
    botTitle: service?.title || "",
  };
}

export function removeServiceDraft(
  storage: Pick<Storage, "removeItem">,
  username: string
) {
  storage.removeItem(getDraftKey(username));
}

export async function deleteConfirmedService(
  service: Pick<Bot, "username">,
  request: (path: string, options: { method: "DELETE" }) => Promise<unknown>,
  storage: Pick<Storage, "removeItem">
) {
  await request(`/bots/${encodeURIComponent(service.username)}`, {
    method: "DELETE",
  });
  removeServiceDraft(storage, service.username);
}

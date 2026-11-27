import assert from "node:assert/strict";
import test from "node:test";
import {
  cancelServiceCreation,
  deleteConfirmedService,
  readServiceDraft,
  restoreServiceDraft,
  saveServiceDraft,
  serviceView,
} from "../../app/dashboard/src/components/botSettings/serviceSettings.ts";

function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  };
}

const settings = {
  bot_url: "https://t.me/saved_bot",
  web_url: "https://saved.example",
  sub_support_url: "https://t.me/support",
  sub_subscription_domain: "subscriptions.example",
  sub_profile_title: "Saved profile",
  sub_profile_url: "",
  bs_extra_reset_pool_on_prolong: false,
  show_ads: true,
};

const draft = (botUsername, botTitle) => ({ settings, botUsername, botTitle });

test("cancel creation returns to the service that opened it", () => {
  const editing = serviceView("partner_bot");
  assert.deepEqual(editing, { mode: "edit", username: "partner_bot" });
  assert.deepEqual(
    cancelServiceCreation(serviceView(undefined, editing.username)),
    editing
  );
  assert.equal(cancelServiceCreation(serviceView()), null);
  assert.equal(cancelServiceCreation(editing), null);
});

test("a stored draft survives selecting other services and repeated restores", () => {
  const storage = makeStorage();
  const editing = serviceView("partner_bot");
  saveServiceDraft(
    storage,
    editing.username,
    draft("renamed_bot", "Partner draft")
  );

  const other = serviceView("other_bot");
  assert.equal(restoreServiceDraft(storage, other.username, settings), null);
  const returned = cancelServiceCreation(
    serviceView(undefined, editing.username)
  );
  const restored = restoreServiceDraft(storage, returned.username, settings);
  assert.equal(restored.botUsername, "renamed_bot");
  assert.equal(restored.botTitle, "Partner draft");
  assert.deepEqual(
    restoreServiceDraft(storage, returned.username, settings),
    restored
  );
});

test("creation and a service named new have independent draft keys", () => {
  const storage = makeStorage({
    botSettings_draft_new: JSON.stringify(draft("new", "Ambiguous old draft")),
    botSettings_draft_partner: JSON.stringify(
      draft("partner", "Existing draft")
    ),
  });
  assert.equal(readServiceDraft(storage, ""), null);
  assert.equal(readServiceDraft(storage, "new"), null);
  assert.equal(readServiceDraft(storage, "partner").botTitle, "Existing draft");

  saveServiceDraft(storage, "", draft("candidate", "Creation draft"));
  saveServiceDraft(storage, "new", draft("new", "Service draft"));
  assert.equal(readServiceDraft(storage, "").botTitle, "Creation draft");
  assert.equal(readServiceDraft(storage, "new").botTitle, "Service draft");
  assert.equal(
    JSON.parse(storage.getItem("botSettings_draft_new")).botTitle,
    "Ambiguous old draft"
  );
});

test("restoring a managed service retains settings controlled by the admin service", () => {
  const storage = makeStorage();
  saveServiceDraft(storage, "managed_bot", draft("rename", "Draft name"));
  const serverSettings = {
    ...settings,
    bot_url: "https://t.me/managed_bot",
    sub_profile_title: "Current profile",
    managed: { key: "bot:1", version: "1", source: "admin", applied_at: null },
  };
  const restored = restoreServiceDraft(storage, "managed_bot", serverSettings, {
    username: "managed_bot",
    title: "Managed name",
  });
  assert.equal(restored.botUsername, "managed_bot");
  assert.equal(restored.botTitle, "Managed name");
  assert.equal(restored.settings.bot_url, serverSettings.bot_url);
  assert.equal(restored.settings.sub_profile_title, settings.sub_profile_title);
});

test("confirmed delete sends the selected username and clears its draft after success", async () => {
  const storage = makeStorage();
  saveServiceDraft(storage, "selected/bot", draft("replacement", "Saved edit"));
  saveServiceDraft(storage, "other", draft("other", "Other edit"));
  saveServiceDraft(storage, "", draft("candidate", "Creation draft"));
  const calls = [];
  let complete;
  const pending = deleteConfirmedService(
    { username: "selected/bot" },
    (path, options) => {
      calls.push([path, options]);
      return new Promise((resolve) => {
        complete = resolve;
      });
    },
    storage
  );

  assert.deepEqual(calls, [["/bots/selected%2Fbot", { method: "DELETE" }]]);
  assert.equal(
    readServiceDraft(storage, "selected/bot").botTitle,
    "Saved edit"
  );
  complete();
  await pending;
  assert.equal(readServiceDraft(storage, "selected/bot"), null);
  assert.equal(readServiceDraft(storage, "other").botTitle, "Other edit");
  assert.equal(readServiceDraft(storage, "").botTitle, "Creation draft");
});

test("failed deletion leaves the draft available for editing", async () => {
  const storage = makeStorage();
  saveServiceDraft(storage, "new", draft("new", "Saved edit"));
  await assert.rejects(
    deleteConfirmedService(
      { username: "new" },
      async () => {
        throw new Error("Request failed");
      },
      storage
    ),
    /Request failed/
  );
  assert.equal(readServiceDraft(storage, "new").botTitle, "Saved edit");
});

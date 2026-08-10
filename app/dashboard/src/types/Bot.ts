export type ManagedState = {
  key: string;
  version: string;
  source: string;
  applied_at: string | null;
};

export type Bot = {
  id: number;
  username: string;
  title?: string | null;
  source_bot_id?: number | null;
  admin_sync_enabled: boolean;
  managed?: ManagedState | null;
};

export type BotSettings = {
  sub_update_interval: string;
  sub_support_url: string;
  sub_profile_title: string;
  sub_routing_happ: string;
  sub_routing_v2raytun: string;
  sub_client_note: string;
  sub_profile_url: string;
  sub_subscription_domain: string;
  bot_url: string;
  web_url: string;
  sub_revoked_announce_text: string;
  sub_expired_announce_text: string;
  sub_device_limit_announce_text: string;
  sub_device_limit_hard_mode: boolean;
  sub_unsupported_client_announce_text: string;
  sub_revoked_server_text: string[];
  sub_expired_server_text: string[];
  sub_device_limit_server_text: string[];
  sub_unsupported_client_server_text: string[];
  sub_bs_limit_server_text: string[];
  sub_bs_limit_announce_text: string;
  sub_v2ray_json_template: string;
  sub_routing_json_default: string;
  sub_routing_json_bs: string;
  sub_custom_headers: string;
  bs_monthly_limit: number;
  bs_extra_reset_pool_on_prolong: boolean;
  show_ads: boolean;
  updated_at?: string;
  managed?: ManagedState | null;
};

export type AdminSyncUpdate = {
  enabled: boolean;
};

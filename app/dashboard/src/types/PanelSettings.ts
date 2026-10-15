export type PanelSettings = {
  sub_custom_headers: string;
  bs_monthly_limit: number;
  sub_routing_happ: string;
  sub_routing_v2raytun: string;
  subscription_legacy_secret_keys: string[];
  primary_jwt_secret?: string;
  sub_client_note: string;
  sub_revoked_announce_text: string;
  sub_expired_announce_text: string;
  sub_device_limit_announce_text: string;
  sub_unsupported_client_announce_text: string;
  sub_bs_limit_announce_text: string;
  sub_revoked_server_text: string[];
  sub_expired_server_text: string[];
  sub_device_limit_server_text: string[];
  sub_unsupported_client_server_text: string[];
  sub_bs_limit_server_text: string[];
};

export type SubscriptionMessageServerField =
  | "sub_revoked_server_text"
  | "sub_expired_server_text"
  | "sub_device_limit_server_text"
  | "sub_unsupported_client_server_text"
  | "sub_bs_limit_server_text";

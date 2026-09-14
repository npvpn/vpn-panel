import { fetch } from "service/http";

export type XrayTemplateVersionMeta = {
  version: number;
  comment: string | null;
  author_username: string;
  created_at: string | null;
  size: number;
};

export type XrayTemplateDocument = {
  id: number;
  slug: string;
  title: string;
  body: string;
  deletable: boolean;
  current: XrayTemplateVersionMeta | null;
};

export const listTemplates = () =>
  fetch("/settings/xray-templates") as Promise<XrayTemplateDocument[]>;

export const listVersions = (id: number) =>
  fetch(`/settings/xray-templates/${id}/versions`) as Promise<
    XrayTemplateVersionMeta[]
  >;

export const getVersion = (id: number, version: number) =>
  fetch(`/settings/xray-templates/${id}/versions/${version}`) as Promise<
    XrayTemplateVersionMeta & { body: string }
  >;

export const saveTemplate = (id: number, body: string, comment: string) =>
  fetch(`/settings/xray-templates/${id}`, {
    method: "PUT",
    body: { body, comment },
  }) as Promise<XrayTemplateVersionMeta>;

export const revertTemplate = (id: number, version: number) =>
  fetch(`/settings/xray-templates/${id}/revert/${version}`, {
    method: "POST",
  }) as Promise<XrayTemplateVersionMeta>;

// Новый конфиг бэкенд заводит копией дефолтного: видов документов нет, каждый
// документ — целый конфиг, который уедет клиенту (NPVPN-2024).
export const createConfig = (slug: string, title: string) =>
  fetch("/settings/xray-templates", {
    method: "POST",
    body: { slug, title },
  }) as Promise<{ id: number; slug: string; title: string }>;

export const deleteConfig = (id: number) =>
  fetch(`/settings/xray-templates/${id}`, { method: "DELETE" });

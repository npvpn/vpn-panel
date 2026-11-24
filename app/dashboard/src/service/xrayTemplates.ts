import { fetch } from "service/http";

export type XrayTemplateVersionMeta = {
  version: number;
  comment: string | null;
  author_username: string;
  created_at: string | null;
  size: number;
};

export type XrayTemplateHost = {
  remark: string;
  inbound_tag: string;
};

export type XrayTemplateDocument = {
  id: number;
  slug: string;
  title: string;
  body: string;
  // Можно ли отправить в архив (default — нельзя). Решает бэк, не фронт.
  archivable: boolean;
  // null — активный конфиг; иначе ISO-дата архивации (NPVPN-2366).
  archived_at: string | null;
  archived_by: string | null;
  // Хосты, привязанные к конфигу (у архивного они получают default) — чтобы перед
  // архивацией было видно, кого именно затронет.
  hosts: XrayTemplateHost[];
  effective_injection?: unknown;
  effective_injection_error?: boolean;
  current: XrayTemplateVersionMeta | null;
};

// Защита от бэка без полей архива (старый ответ с `deletable` или частичная
// доработка): без неё `archivable` = undefined, и бейдж «по умолчанию» вставал на
// каждый конфиг, а `hosts.length` падал. Старое поле — запасной источник права.
const normalizeDocument = (
  doc: Partial<XrayTemplateDocument> & { deletable?: boolean }
): XrayTemplateDocument =>
  ({
    ...doc,
    archivable: doc.archivable ?? doc.deletable ?? doc.slug !== "default",
    archived_at: doc.archived_at ?? null,
    archived_by: doc.archived_by ?? null,
    hosts: doc.hosts ?? [],
  } as XrayTemplateDocument);

export const listTemplates = (): Promise<XrayTemplateDocument[]> =>
  fetch("/settings/xray-templates").then(
    (docs: Partial<XrayTemplateDocument>[]) => docs.map(normalizeDocument)
  );

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

// Архив вместо удаления (NPVPN-2366, ADR 0005): привязки хостов сохраняются,
// восстановление возвращает конфиг вместе с ними и с историей версий.
export const archiveConfig = (id: number): Promise<void> =>
  fetch(`/settings/xray-templates/${id}/archive`, { method: "POST" });

export const restoreConfig = (id: number): Promise<void> =>
  fetch(`/settings/xray-templates/${id}/restore`, { method: "POST" });

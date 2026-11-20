// ВРЕМЕННЫЙ мок архива клиентских конфигов (NPVPN-2366): фронт рисуется по контракту
// раньше, чем бэк научится архивировать. Включается только VITE_MOCK_XRAY_ARCHIVE=true.
// Когда бэк отдаёт archived_at/archived_by/hosts/archivable и эндпоинты
// archive/restore — этот файл удаляется вместе с веткой MOCK_ARCHIVE в xrayTemplates.ts.
//
// Архив живёт в памяти вкладки: перезагрузка страницы его сбрасывает. Сам бэк об архиве
// не знает — сохранение хостов и рендер подписки под моком работают по-старому.
import { fetch } from "service/http";
import type {
  XrayTemplateDocument,
  XrayTemplateHost,
} from "service/xrayTemplates";

type RawDocument = Omit<
  XrayTemplateDocument,
  "archived_at" | "archived_by" | "hosts" | "archivable"
> & { deletable?: boolean };

type HostsByInbound = Record<
  string,
  { remark: string; client_config_id?: number | null }[]
>;

const archive = new Map<number, { archived_at: string; archived_by: string }>();
let adminName: Promise<string> | null = null;
let rawById = new Map<number, RawDocument>();

const delay = () => new Promise((resolve) => setTimeout(resolve, 300));

// Ошибка в форме ofetch: компонент читает err.response.status / err.response._data.detail.
const conflict = (detail: string) =>
  Object.assign(new Error(detail), {
    response: { status: 409, _data: { detail } },
  });

const currentAdmin = () => {
  adminName ??= (fetch("/admin") as Promise<{ username: string }>)
    .then((admin) => admin.username)
    .catch(() => "admin");
  return adminName;
};

export const decorateTemplates = async (
  docs: RawDocument[]
): Promise<XrayTemplateDocument[]> => {
  rawById = new Map(docs.map((doc) => [doc.id, doc]));
  const hosts = (await fetch("/hosts").catch(() => ({}))) as HostsByInbound;
  const bound = new Map<number, XrayTemplateHost[]>();
  Object.entries(hosts).forEach(([inbound_tag, list]) =>
    list.forEach((host) => {
      if (host.client_config_id != null) {
        const items = bound.get(host.client_config_id) ?? [];
        items.push({ remark: host.remark, inbound_tag });
        bound.set(host.client_config_id, items);
      }
    })
  );
  return docs.map(({ deletable, ...doc }) => ({
    ...doc,
    archivable: deletable ?? doc.slug !== "default",
    archived_at: archive.get(doc.id)?.archived_at ?? null,
    archived_by: archive.get(doc.id)?.archived_by ?? null,
    hosts: bound.get(doc.id) ?? [],
  }));
};

export const mockArchive = async (id: number) => {
  await delay();
  const doc = rawById.get(id);
  if (!doc) throw conflict("template not found");
  if (doc.slug === "default") throw conflict("the default config cannot be archived");
  if (archive.has(id)) throw conflict("config is already archived");
  archive.set(id, {
    archived_at: new Date().toISOString(),
    archived_by: await currentAdmin(),
  });
};

export const mockRestore = async (id: number) => {
  await delay();
  if (!archive.has(id)) throw conflict("config is not archived");
  archive.delete(id);
};

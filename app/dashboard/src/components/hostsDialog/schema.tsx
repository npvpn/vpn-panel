import { z } from "zod";

export const hostItemSchema = z
  .object({
    // NPVPN-2044: id хоста обязателен к передаче назад — без него бэкенд
    // пересоздаст хост (upsert в crud.update_hosts сопоставляет по id) и потеряет
    // отметку аренды вместе с закреплениями пользователей. undefined = новый хост.
    //
    // Поле названо host_id, а не id, НАМЕРЕННО: useFieldArray из react-hook-form
    // занимает имя `id` под свой строковый ключ строки и перетёр бы число —
    // payload уехал бы с ключом формы вместо настоящего id. Переименование
    // обратно в `id` делает groupHosts при отправке.
    host_id: z.number().optional(),
    inbound_tag: z.string().min(1),
    order: z.number().int(),
    remark: z.string().min(1, "Remark is required"),
    address: z.string(),
    port: z
      .string()
      .or(z.number())
      .nullable()
      .transform((value) => {
        if (typeof value === "number") return value;
        if (value !== null && !isNaN(parseInt(value)))
          return Number(parseInt(value));
        return null;
      }),
    path: z.string().nullable(),
    sni: z.string().nullable(),
    host: z.string().nullable(),
    mux_enable: z.boolean().default(false),
    allowinsecure: z.boolean().nullable().default(false),
    is_disabled: z.boolean().default(true),
    fragment_setting: z.string().nullable(),
    noise_setting: z.string().nullable(),
    random_user_agent: z.boolean().default(false),
    security: z.string(),
    alpn: z.string(),
    fingerprint: z.string(),
    use_sni_as_host: z.boolean().default(false),
    xhttp_extra: z
      .string()
      .nullable()
      .optional()
      .refine(
        (v) => {
          if (!v) return true;
          try {
            const parsed = JSON.parse(v);
            return (
              typeof parsed === "object" &&
              !Array.isArray(parsed) &&
              parsed !== null
            );
          } catch {
            return false;
          }
        },
        { message: "Must be a valid JSON object" }
      ),
    bot_usernames: z.array(z.string()).default([]),
    // NPVPN-2044: боты, которым хост отмечен арендованным. Подмножество
    // bot_usernames — бэкенд отвергает аренду без привязки.
    rented_bot_usernames: z.array(z.string()).default([]),
    node_ids: z.array(z.number()).default([]),
    client_config_id: z.number().nullable().default(null),
    // NPVPN-2072: сужение адресов настраивается на хосте. Пустое поле = null
    // («отдавать все адреса»), а не 0 — ноль означал бы выдачу без адресов.
    address_subset_enabled: z.boolean().default(false),
    address_subset_size: z
      .string()
      .or(z.number())
      .nullable()
      .optional()
      .transform((value) => {
        if (value === null || value === undefined || value === "") return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? Math.max(1, Math.trunc(parsed)) : null;
      }),
    address_rotation_days: z
      .string()
      .or(z.number())
      .nullable()
      .optional()
      .transform((value) => {
        if (value === null || value === undefined || value === "") return null;
        const parsed = Number(value);
        return Number.isFinite(parsed) ? Math.max(1, Math.trunc(parsed)) : null;
      }),
  })
  .superRefine((data, ctx) => {
    if (!data.address && (!data.node_ids || data.node_ids.length === 0)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["address"],
        message: "Address or linked nodes required",
      });
    }
  });

export const hostsFormSchema = z.object({
  hosts: z.array(hostItemSchema),
});

/** @deprecated kept for imports that still expect record shape name */
export const hostsSchema = hostsFormSchema;

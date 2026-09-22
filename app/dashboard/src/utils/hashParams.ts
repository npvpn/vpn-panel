/**
 * Query-параметры deep-link лежат в хэше (`#/?node=5`), а не в path: роутер
 * панели хэшевый (createHashRouter), а сама сборка смонтирована статикой на
 * /dashboard/ — подпуть вида /dashboard/nodes/5/ отдал бы 404.
 */
export function readHashParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.split("?")[1] || "");
}

/** Часть хэша до `?` — обычно `#/` у createHashRouter. */
function hashRouteBase(): string {
  const [route] = window.location.hash.split("?");
  return route || "#/";
}

/** Обновляет query в хэше, не добавляя запись в history (replaceState). */
export function writeHashParams(params: URLSearchParams): void {
  const base = hashRouteBase();
  const query = params.toString();
  const hash = query ? `${base}?${query}` : base;
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${hash}`
  );
}

/** Убирает один deep-link параметр; остальные (например search) сохраняет. */
export function clearHashParam(name: string): void {
  const params = readHashParams();
  if (!params.has(name)) return;
  params.delete(name);
  writeHashParams(params);
}

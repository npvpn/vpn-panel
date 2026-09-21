/**
 * Query-параметры deep-link лежат в хэше (`#/?node=5`), а не в path: роутер
 * панели хэшевый (createHashRouter), а сама сборка смонтирована статикой на
 * /dashboard/ — подпуть вида /dashboard/nodes/5/ отдал бы 404.
 */
export function readHashParams(): URLSearchParams {
  return new URLSearchParams(window.location.hash.split("?")[1] || "");
}

/** Deep-link в хэше, который надо вернуть после логина.

Хэшевый роутер при неудачной загрузке дашборда уводит на `#/login` и
стирает `?host=` / `?node=`. Эти параметры забираем до перехода и
подставляем обратно после входа.
*/

const DEEP_LINK_PARAMS = ["host", "node"] as const;

export function loginReturnSearch(search: string): string {
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const name of DEEP_LINK_PARAMS) {
    const value = params.get(name);
    if (value) kept.set(name, value);
  }
  const query = kept.toString();
  return query ? `?${query}` : "";
}

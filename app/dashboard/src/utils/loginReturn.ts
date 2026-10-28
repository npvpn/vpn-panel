/** Deep-link в хэше, который надо вернуть после логина.

Хэшевый роутер при неудачной загрузке дашборда уводит на `#/login` и
стирает `?host=` / `?node=`. Эти параметры забираем до перехода и
подставляем обратно после входа.
*/

const DEEP_LINK_PARAMS = ["host", "node"] as const;

export const LOGIN_RETURN_KEY = "npvpn-dashboard-return";

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

type LoginReturnWrite = {
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

type LoginReturnRead = {
  getItem(key: string): string | null;
  removeItem(key: string): void;
};

/** Перед уходом на /login оставляем только host и node. Пустой адрес стирает старый возврат. */
export function rememberLoginReturn(
  search: string,
  storage: LoginReturnWrite
): void {
  const kept = loginReturnSearch(search);
  if (kept) storage.setItem(LOGIN_RETURN_KEY, kept);
  else storage.removeItem(LOGIN_RETURN_KEY);
}

/** После входа забираем адрес один раз. */
export function takeLoginReturn(storage: LoginReturnRead): string {
  const value = storage.getItem(LOGIN_RETURN_KEY) || "";
  storage.removeItem(LOGIN_RETURN_KEY);
  return value;
}

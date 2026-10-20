// Привязка хоста к ботам в окне настроек хоста. Чистые функции без React —
// их исполняют тесты (tests/test_hosts_dialog_logic_js.py) прямо в Node.

// «Выбрать всех» (NPVPN-2215): добавляет ботов из списка (при поиске — только
// найденных), уже выбранные остаются на своих местах и не дублируются.
export function selectAllBots(
  current: string[],
  candidates: string[]
): string[] {
  const selected = new Set(current);
  return [
    ...current,
    ...candidates.filter((username) => !selected.has(username)),
  ];
}

// Аренда возможна только у привязанного бота: снимая бота с хоста, снимаем и
// его аренду. Иначе сервер отвечал 400 «rented bot is not bound to host» на
// сохранении, и форма не сохранялась (NPVPN-2215; на вкладке «По ботам» это
// уже делалось при выключении доступа).
export function withoutUnboundRentals(
  rented: string[],
  bound: string[]
): string[] {
  const boundSet = new Set(bound);
  return rented.filter((username) => boundSet.has(username));
}

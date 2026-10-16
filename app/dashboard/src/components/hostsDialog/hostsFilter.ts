// Какие хосты показать в списке вкладки «Хосты». Чистые функции без React —
// их исполняют тесты (tests/test_hosts_dialog_logic_js.py) прямо в Node.

export type HostFilterValues = {
  remark?: string;
  address?: string;
  inbound_tag?: string;
  is_disabled?: boolean;
};

export type HostFilters = {
  search: string;
  inboundFilter: string;
  activeOnly: boolean;
};

// Хосты, уже показанные при текущих фильтрах (по id строки useFieldArray), и
// все строки, что были в списке в прошлый раз, — по ним видно добавленные.
export type ShownHosts = {
  filterKey: string;
  ids: Set<string>;
  knownRowIds: Set<string>;
};

export function hostMatchesFilters(
  host: HostFilterValues | undefined,
  { search, inboundFilter, activeOnly }: HostFilters
): boolean {
  if (!host) return false;

  if (inboundFilter && host.inbound_tag !== inboundFilter) {
    return false;
  }

  if (activeOnly && host.is_disabled) {
    return false;
  }

  const query = search.trim().toLowerCase();

  if (query) {
    const remark = (host.remark || "").toLowerCase();
    const address = (host.address || "").toLowerCase();
    if (!remark.includes(query) && !address.includes(query)) {
      return false;
    }
  }

  return true;
}

export function filtersKey({
  search,
  inboundFilter,
  activeOnly,
}: HostFilters): string {
  return JSON.stringify([
    search.trim().toLowerCase(),
    inboundFilter,
    activeOnly,
  ]);
}

// NPVPN-2215: фильтры решают, какие хосты показать, в момент их смены, а не
// на каждое нажатие клавиши. Уже показанный хост остаётся в списке, даже если
// после правки перестал подходить (переименовали «VPN …» в «VP …» при поиске
// «VPN», выключили при «Только активные»): иначе строка исчезала посреди
// редактирования, а вместе с ней закрывалось и окно её настроек. С новыми
// фильтрами список «уже показанных» начинается заново.
//
// Так же виден только что добавленный или продублированный хост, даже если
// под фильтры не подходит: иначе он добавлялся, а в списке его не было.
// Добавленный — новый id среди знакомых строк. Если знакомых не осталось
// вовсе (первая загрузка, перезагрузка формы — у строк новые id), это не
// добавление, а новый список, и фильтры применяются честно.
export function selectVisibleHosts(
  rowIds: string[],
  hosts: (HostFilterValues | undefined)[],
  filters: HostFilters,
  shown: ShownHosts | null
): { indexes: number[]; shown: ShownHosts } {
  const filterKey = filtersKey(filters);
  const ids =
    shown && shown.filterKey === filterKey
      ? new Set(shown.ids)
      : new Set<string>();

  const knownRowIds = shown?.knownRowIds ?? new Set<string>();
  const isSameList = rowIds.some((id) => knownRowIds.has(id));
  if (isSameList) {
    rowIds.forEach((id) => {
      if (!knownRowIds.has(id)) ids.add(id);
    });
  }

  const indexes = rowIds
    .map((id, index) => ({ id, index }))
    .filter(
      ({ id, index }) =>
        ids.has(id) || hostMatchesFilters(hosts[index], filters)
    )
    .map(({ index }) => index);

  indexes.forEach((index) => ids.add(rowIds[index]));

  return {
    indexes,
    shown: { filterKey, ids, knownRowIds: new Set(rowIds) },
  };
}

// Порядок строк вкладки «По ботам»: сначала хосты, доступные выбранному боту,
// потом остальные; внутри групп — общий порядок хостов.
export type BotTabOrder = {
  key: string;
  // id строки → доступна ли она боту на момент фиксации порядка.
  availableAtStart: Map<string, boolean>;
};

// NPVPN-2215: группа строки фиксируется, когда выбирают бота или меняют
// фильтры (key), а не на каждый щелчок переключателя: иначе включённый хост
// улетал бы наверх прямо из-под курсора, а выключенный — вниз. Строки,
// которых раньше не было (добавленные), встают в группу по текущему
// состоянию.
export function orderBotTabRows(
  rowIds: string[],
  isAvailable: boolean[],
  key: string,
  previous: BotTabOrder | null
): { order: number[]; state: BotTabOrder } {
  const availableAtStart = new Map<string, boolean>();
  const known =
    previous && previous.key === key ? previous.availableAtStart : null;

  rowIds.forEach((id, index) => {
    availableAtStart.set(id, known?.get(id) ?? isAvailable[index]);
  });

  const order = rowIds
    .map((id, index) => ({ index, available: availableAtStart.get(id) }))
    .sort(
      (a, b) => Number(b.available) - Number(a.available) || a.index - b.index
    )
    .map(({ index }) => index);

  return { order, state: { key, availableAtStart } };
}

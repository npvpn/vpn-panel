// NPVPN-2215: сравнение значений хоста «по смыслу» — для пометки
// несохранённых изменений в окне настроек. Инпуты отдают то число, то строку
// ("2" и 2), очищенное поле — "" вместо null, а порядок в списках вроде
// bot_usernames зависит от порядка кликов. Без нормализации окно считало бы
// изменённым хост, который вернули к исходным значениям вручную.
function normalize(value: unknown): unknown {
  if (value === undefined || value === "") return null;
  if (typeof value === "number") return String(value);

  if (Array.isArray(value)) {
    const items = value.map(normalize);
    const isPrimitiveList = items.every(
      (item) => item === null || typeof item !== "object"
    );
    return isPrimitiveList ? items.map(String).sort() : items;
  }

  if (value && typeof value === "object") {
    // Пустые поля отбрасываем: отсутствующее поле и поле со значением
    // ""/null/undefined — одно и то же «не задано».
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, normalize((value as Record<string, unknown>)[key])])
        .filter(([, item]) => item !== null)
    );
  }

  return value;
}

export function isSameHostValues(a: unknown, b: unknown): boolean {
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}

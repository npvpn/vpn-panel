import { FC } from "react";
import { useTranslation } from "react-i18next";
import { filterFieldProps, Select } from "./constants";

type Props = {
  isActive: boolean;
  onChange: (active: boolean) => void;
};

// Фильтр — селектом, как соседние «Все инбаунды» / «Все боты»: показывает
// текущее значение, поэтому не читается как описание состояния и не меняет
// ширину при переключении.
export const ActiveOnlySelect: FC<Props> = ({ isActive, onChange }) => {
  const { t } = useTranslation();

  return (
    <Select
      size="sm"
      flex="1"
      minW="140px"
      {...filterFieldProps}
      aria-label={t("hostsDialog.filterActiveOnly") ?? undefined}
      value={isActive ? "active" : ""}
      onChange={(e) => onChange(e.target.value === "active")}
    >
      <option value="">{t("hostsDialog.allHosts")}</option>
      <option value="active">{t("hostsDialog.activeOnly")}</option>
    </Select>
  );
};

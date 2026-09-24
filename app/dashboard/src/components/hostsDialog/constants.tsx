import {
  Select as ChakraSelect,
  FormErrorMessage,
  SelectProps,
  chakra,
  forwardRef,
} from "@chakra-ui/react";

import {
  ArrowDownIcon,
  ArrowsUpDownIcon,
  ArrowUpIcon,
  Cog6ToothIcon,
  DocumentDuplicateIcon,
  LinkIcon,
  InformationCircleIcon,
  PencilSquareIcon,
} from "@heroicons/react/24/outline";

import { Input as CustomInput } from "../Input";

export const DuplicateIcon = chakra(DocumentDuplicateIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const UpIcon = chakra(ArrowUpIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const DownIcon = chakra(ArrowDownIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const DragHandleIcon = chakra(ArrowsUpDownIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

// Все селекты модалки хостов — через этот компонент. Нативный выпадающий
// список браузер рисует белым, а в тёмной теме текст пунктов светлый и
// пропадает — поэтому фон и цвет пунктов задаём явно.
//
// Не chakra(ChakraSelect): такая обёртка превращает flex/minW/w в класс на
// самом <select>, а не на обёртке селекта, и та растягивается на всю строку.
// Здесь пропсы уходят в ChakraSelect как есть, а стили поля — через sx (он
// попадает на <select>; тёмная тема — селекторами, а не _dark: _dark из
// пропсов, например filterFieldProps, заменил бы его целиком).
const darkSelector = ".chakra-ui-dark &, [data-theme=dark] &";

const selectFieldSx = {
  bg: "white",
  "& > option, & > optgroup": { bg: "white", color: "gray.800" },
  [darkSelector]: { bg: "gray.700" },
  [`.chakra-ui-dark & > option, .chakra-ui-dark & > optgroup`]: {
    bg: "gray.750",
    color: "whiteAlpha.900",
  },
};

export const Select = forwardRef<SelectProps, "select">(
  ({ sx, ...props }, ref) => (
    <ChakraSelect ref={ref} {...props} sx={{ ...selectFieldSx, ...sx }} />
  )
);

export const Input = chakra(CustomInput, {
  baseStyle: {
    bg: "white",
    _dark: {
      bg: "gray.700",
    },
  },
});

export const InfoIcon = chakra(InformationCircleIcon, {
  baseStyle: {
    w: 4,
    h: 4,
    color: "gray.400",
    cursor: "pointer",
  },
});

export const Error = chakra(FormErrorMessage, {
  baseStyle: {
    color: "red.400",
    display: "block",
    textAlign: "left",
    w: "100%",
  },
});

export const ModalIcon = chakra(LinkIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const GearIcon = chakra(Cog6ToothIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const PencilIcon = chakra(PencilSquareIcon, {
  baseStyle: {
    w: 4,
    h: 4,
  },
});

// Fields edited inside the settings modal rather than inline on a host row.
export const ADVANCED_FIELD_KEYS = [
  "remark",
  "address",
  "port",
  "path",
  "sni",
  "host",
  "mux_enable",
  "allowinsecure",
  "fragment_setting",
  "noise_setting",
  "random_user_agent",
  "security",
  "alpn",
  "fingerprint",
  "use_sni_as_host",
  "xhttp_extra",
  "bot_usernames",
  "node_ids",
  "client_config_id",
  "address_subset_enabled",
  "address_subset_size",
  "address_rotation_days",
] as const;

// Whether the settings-modal gear icon should show its error dot: remark/address
// errors only count when those fields are actually shown inside that modal
// (they're hidden there, in favor of an inline field, when hideRemarkAddress is set).
export const hasAdvancedFieldErrors = (
  accordionErrors: any,
  hideRemarkAddress?: boolean
) =>
  ADVANCED_FIELD_KEYS.some((key) => {
    if (hideRemarkAddress && (key === "remark" || key === "address")) {
      return false;
    }
    return !!accordionErrors?.[key];
  });

// Поля панели фильтров над таблицами: одно скругление и цвет рамки с
// карточками строк (у Select по умолчанию радиус меньше, чем у Input).
export const filterFieldProps = {
  borderRadius: "6px",
  borderColor: "gray.200",
  _dark: { borderColor: "gray.600" },
};

// Таблицы модалки хостов: каждая строка — отдельная карточка с рамкой и
// скруглением, между строками зазор. Глобальная тема Table (chakra.config.ts)
// рисует рамку вокруг всей таблицы — её гасим. Рамку строки собирают ячейки:
// верх/низ у всех, лево/право и скругления у крайних — поэтому и подсветка
// при наведении висит на ячейках, а не на <tr>: фон <tr> скругления не знает.
const rowBorder = "1px solid var(--hosts-row-border)";

export const hostsTableSx = {
  "--hosts-row-border": "var(--chakra-colors-gray-200)",
  _dark: { "--hosts-row-border": "var(--chakra-colors-gray-600)" },
  borderSpacing: "0 6px !important",
  // border-spacing даёт зазор и над шапкой — снимаем его, чтобы отступ до
  // таблицы задавал только контейнер.
  mt: "-6px",
  // Шапка — полоса с заливкой без рамки: по ширине совпадает с карточками,
  // но не читается как ещё одна строка.
  th: {
    border: "none !important",
    borderRadius: "0 !important",
    bg: "gray.100",
    _dark: { bg: "gray.800" },
  },
  "th:first-of-type": {
    borderTopLeftRadius: "6px !important",
    borderBottomLeftRadius: "6px !important",
  },
  "th:last-of-type": {
    borderTopRightRadius: "6px !important",
    borderBottomRightRadius: "6px !important",
  },
  "tbody td": {
    borderTop: `${rowBorder} !important`,
    borderBottom: `${rowBorder} !important`,
    borderLeft: "none !important",
    borderRight: "none !important",
    borderRadius: "0 !important",
  },
  "tbody td:first-of-type": {
    borderLeft: `${rowBorder} !important`,
    borderTopLeftRadius: "6px !important",
    borderBottomLeftRadius: "6px !important",
  },
  "tbody td:last-of-type": {
    borderRight: `${rowBorder} !important`,
    borderTopRightRadius: "6px !important",
    borderBottomRightRadius: "6px !important",
  },
  "tbody tr:hover > td": {
    bg: "gray.50",
    _dark: { bg: "gray.750" },
  },
};

import { useColorModeValue, useToken } from "@chakra-ui/react";
import { StylesConfig } from "react-select";

interface BotOption {
  value: string;
  label: string;
}

type BotSelectVariant = "default" | "filter";

interface UseBotSelectStylesProps {
  variant?: BotSelectVariant;
  // "sm" — под компактные (size="sm") поля, как в ряду фильтров диалога
  // хостов: высота 32, шрифт 14px, скругление 6px.
  size?: "md" | "sm";
}

export const useBotSelectStyles = ({
  variant = "default",
  size = "md",
}: UseBotSelectStylesProps = {}): StylesConfig<BotOption, false> => {
  const height = size === "sm" ? 32 : 40;
  const sizeStyles = size === "sm" ? { fontSize: 14, borderRadius: 6 } : {};

  const bgToken = useColorModeValue(
    variant === "filter" ? "chakra-body-bg" : "white",
    variant === "filter" ? "gray.800" : "gray.700"
  );

  const textToken = useColorModeValue("gray.800", "white");

  const borderToken = useColorModeValue(
    variant === "filter" ? "gray.200" : "gray.200",
    "gray.600"
  );

  const placeholderToken = useColorModeValue("gray.500", "gray.400");
  const hoverToken = useColorModeValue("primary.50", "primary.900");
  const selectedToken = useColorModeValue("primary.500", "primary.200");

  const [bg, text, border, placeholder, hover, selected] = useToken("colors", [
    bgToken,
    textToken,
    borderToken,
    placeholderToken,
    hoverToken,
    selectedToken,
  ]);

  return {
    control: (base, state) => ({
      ...base,
      ...sizeStyles,
      minHeight: height,
      height,
      backgroundColor: bg,
      borderColor: state.isFocused ? selected : border,
      boxShadow: "none",
      "&:hover": {
        borderColor: border,
      },
    }),

    valueContainer: (base) => ({
      ...base,
      height,
      padding: "0 12px",
    }),

    input: (base) => ({
      ...base,
      color: text,
    }),

    singleValue: (base) => ({
      ...base,
      color: text,
    }),

    placeholder: (base) => ({
      ...base,
      color: placeholder,
    }),

    menu: (base) => ({
      ...base,
      ...(size === "sm" ? { fontSize: 14 } : {}),
      backgroundColor: bg,
    }),

    indicatorsContainer: (base) => ({
      ...base,
      ...(size === "sm" ? { height } : {}),
    }),

    option: (base, state) => ({
      ...base,
      backgroundColor: state.isSelected
        ? selected
        : state.isFocused
        ? hover
        : bg,
      color: state.isSelected ? "white" : text,
    }),

    clearIndicator: (base) => ({
      ...base,
      color: placeholder,
    }),

    dropdownIndicator: (base) => ({
      ...base,
      color: placeholder,
    }),

    menuPortal: (base) => ({
      ...base,
      zIndex: 9999,
    }),
  };
};

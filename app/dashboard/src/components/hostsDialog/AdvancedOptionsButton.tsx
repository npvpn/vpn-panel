import { Box, IconButton, Tooltip } from "@chakra-ui/react";
import { FC } from "react";
import { useTranslation } from "react-i18next";
import { GearIcon } from "./constants";

// Шестерёнка «Настройки хоста» — в строке вкладки «Хосты» и (NPVPN-2215)
// вкладки «По ботам». Красная точка — ошибки в полях окна настроек.
export const AdvancedOptionsButton: FC<{
  hasErrors?: boolean;
  onClick: () => void;
}> = ({ hasErrors, onClick }) => {
  const { t } = useTranslation();

  return (
    <Tooltip label={t("hostsDialog.advancedOptions")} placement="left">
      <Box position="relative" display="inline-block">
        <IconButton
          aria-label={t("hostsDialog.advancedOptions")}
          size="xs"
          variant="ghost"
          onClick={onClick}
        >
          <GearIcon />
        </IconButton>

        {hasErrors && (
          <Box
            position="absolute"
            top="1px"
            right="1px"
            w="8px"
            h="8px"
            borderRadius="full"
            bg="red.500"
            border="2px solid"
            borderColor="white"
            _dark={{ borderColor: "gray.700" }}
            pointerEvents="none"
          />
        )}
      </Box>
    </Tooltip>
  );
};

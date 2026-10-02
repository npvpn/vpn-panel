import {
  Badge,
  Box,
  Button,
  HStack,
  Input,
  InputGroup,
  InputLeftElement,
  Switch,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
} from "@chakra-ui/react";
import { MagnifyingGlassIcon } from "@heroicons/react/24/outline";
import { FC, useCallback, useEffect, useMemo } from "react";
import { FieldArrayWithId, useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Bot } from "types/Bot";
import { z } from "zod";
import { ActiveOnlySelect } from "./ActiveOnlySelect";
import { filterFieldProps, hostsTableSx, Select } from "./constants";
import { hostsFormSchema } from "./schema";

type HostField = FieldArrayWithId<z.infer<typeof hostsFormSchema>, "hosts">;

// Выбранный бот, поиск и фильтр живут в HostsDialog: сама вкладка
// монтируется, только пока открыта (иначе она, подписанная на все хосты,
// пересчитывалась бы в фоне на каждое изменение на вкладке «Хосты»), а эти
// значения должны переживать переключение вкладок.
export type BotTabFilters = {
  selectedBot: string;
  search: string;
  activeOnly: boolean;
};

export const EMPTY_BOT_TAB_FILTERS: BotTabFilters = {
  selectedBot: "",
  search: "",
  activeOnly: false,
};

type Props = {
  fields: HostField[];
  bots: Bot[];
  filters: BotTabFilters;
  onFiltersChange: (update: Partial<BotTabFilters>) => void;
};

// NPVPN-2044: пустой bot_usernames — законное состояние «хост не виден никому»
// (привязок нет вовсе). Раньше выключение последнего бота
// подставляло ВСЕХ ботов, потому что пустой список означал «всем», — то есть
// снятие последнего тумблера давало ровно противоположное намерению.
function nextBotUsernames(
  current: string[],
  bot: string,
  enable: boolean
): string[] {
  if (enable) {
    return current.includes(bot) ? current : [...current, bot];
  }

  return current.filter((username) => username !== bot);
}

// Колонки, которые на узком экране прячутся — остаются remark и переключатель.
const wideOnly = { base: "none", md: "table-cell" };

// На узком экране колонка инбаунда скрыта, и левый край карточки строки
// рисует remark — вторая ячейка.
const botTableSx = {
  ...hostsTableSx,
  "tbody td:nth-of-type(2)": {
    borderLeft: {
      base: "1px solid var(--hosts-row-border) !important",
      md: "none !important",
    },
    borderTopLeftRadius: { base: "6px !important", md: "0 !important" },
    borderBottomLeftRadius: { base: "6px !important", md: "0 !important" },
  },
  "th:nth-of-type(2)": {
    borderTopLeftRadius: { base: "6px !important", md: "0 !important" },
    borderBottomLeftRadius: { base: "6px !important", md: "0 !important" },
  },
};

export const BotHostsTab: FC<Props> = ({
  fields,
  bots,
  filters,
  onFiltersChange,
}) => {
  const { t } = useTranslation();
  const form = useFormContext<z.infer<typeof hostsFormSchema>>();

  const { selectedBot, search, activeOnly } = filters;
  const setSelectedBot = (selectedBot: string) =>
    onFiltersChange({ selectedBot });
  const setSearch = (search: string) => onFiltersChange({ search });
  const setActiveOnly = (activeOnly: boolean) =>
    onFiltersChange({ activeOnly });

  useEffect(() => {
    if (!bots.some((bot) => bot.username === selectedBot)) {
      setSelectedBot(bots[0]?.username ?? "");
    }
  }, [bots, selectedBot]);

  const allBotUsernames = useMemo(
    () => bots.map((bot) => bot.username),
    [bots]
  );

  // Подписи ботов для подсказки — в том же формате, что на вкладке «Хосты».
  const botDisplayNames = useMemo(
    () =>
      new Map(
        bots.map((bot) => [
          bot.username,
          bot.title ? `${bot.title} (@${bot.username})` : `@${bot.username}`,
        ])
      ),
    [bots]
  );

  const watchedHosts = useWatch({ control: form.control, name: "hosts" });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();

    return (
      fields
        .map((field, index) => {
          const host = watchedHosts?.[index];
          const botUsernames: string[] = host?.bot_usernames || [];
          // NPVPN-2044: доступ даёт только привязка — исключений больше нет.
          const isAvailable = botUsernames.includes(selectedBot);
          // Аренда — отдельная отметка: в счёт идёт только отмеченный хост,
          // служебную привязку (на время разбирательства) тарифицировать нельзя.
          const isRented = (host?.rented_bot_usernames || []).includes(selectedBot);

          return {
            id: field.id,
            index,
            inboundTag: host?.inbound_tag ?? "",
            remark: host?.remark ?? "",
            address: host?.address ?? "",
            isHostDisabled: !!host?.is_disabled,
            botsLabel:
              botUsernames.length === 0
                ? t("hostsDialog.availableBots.none")
                : botUsernames.map((username) => `@${username}`).join(", "),
            botsTooltip: botUsernames
              .map(
                (username) => botDisplayNames.get(username) ?? `@${username}`
              )
              .join(", "),
            isAvailable,
            isRented,
          };
        })
        // «Активный» здесь — строка с включённым тумблером: доступная выбранному
        // боту.
        .filter(
          (row) =>
            (!activeOnly || row.isAvailable) &&
            (!query ||
              row.remark.toLowerCase().includes(query) ||
              row.address.toLowerCase().includes(query))
        )
    );
  }, [
    fields,
    watchedHosts,
    selectedBot,
    allBotUsernames,
    botDisplayNames,
    search,
    activeOnly,
    t,
  ]);

  const availableCount = rows.filter((row) => row.isAvailable).length;
  // Доступные боту, но выключенные глобально — бот их сейчас не выдаёт.
  const availableDisabledCount = rows.filter(
    (row) => row.isAvailable && row.isHostDisabled
  ).length;
  const canEnableAll = rows.some((row) => !row.isAvailable);
  const canDisableAll = rows.some((row) => row.isAvailable);

  const toggleHost = useCallback(
    (index: number, enable: boolean) => {
      const current: string[] =
        form.getValues(`hosts.${index}.bot_usernames`) || [];

      form.setValue(
        `hosts.${index}.bot_usernames`,
        nextBotUsernames(current, selectedBot, enable),
        { shouldDirty: true }
      );

      // NPVPN-2044: отбирая доступ, снимаем и аренду — иначе бэкенд ответит 400
      // «rented bot is not bound to host» при сохранении формы.
      if (!enable) {
        const rented: string[] =
          form.getValues(`hosts.${index}.rented_bot_usernames`) || [];
        if (rented.includes(selectedBot)) {
          form.setValue(
            `hosts.${index}.rented_bot_usernames`,
            rented.filter((username) => username !== selectedBot),
            { shouldDirty: true }
          );
        }
      }
    },
    [form, selectedBot]
  );

  // NPVPN-2044: аренда — отдельная отметка. Доступ даёт привязка, а в счёт
  // попадает только отмеченный арендованным хост.
  const toggleRented = useCallback(
    (index: number, enable: boolean) => {
      const current: string[] =
        form.getValues(`hosts.${index}.rented_bot_usernames`) || [];
      const next = enable
        ? current.includes(selectedBot)
          ? current
          : [...current, selectedBot]
        : current.filter((username) => username !== selectedBot);

      form.setValue(`hosts.${index}.rented_bot_usernames`, next, {
        shouldDirty: true,
      });
    },
    [form, selectedBot]
  );

  // Действует только на видимые строки (с учётом поиска и фильтра), так что
  // «отключить все» после поиска трогает лишь найденные хосты.
  const toggleAllVisible = (enable: boolean) => {
    rows
      .filter((row) => (enable ? !row.isAvailable : row.isAvailable))
      .forEach((row) => toggleHost(row.index, enable));
  };

  const thCell = {
    px: 3,
    py: 2,
    textAlign: "center" as const,
    color: "gray.600",
    position: "sticky" as const,
    top: 0,
    zIndex: 1,
    _dark: { color: "gray.400" },
  };

  const tdCell = {
    px: 3,
    py: 2,
    textAlign: "center" as const,
  };

  return (
    <Box display="flex" flexDirection="column" minH={0} h="full">
      <HStack mt={1} spacing={2} rowGap={2} flexWrap="wrap" flexShrink={0}>
        <InputGroup flex="2" minW="180px" size="sm">
          <InputLeftElement pointerEvents="none">
            <MagnifyingGlassIcon width="16px" color="gray" />
          </InputLeftElement>

          <Input
            placeholder={t("hostsDialog.search") ?? undefined}
            {...filterFieldProps}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </InputGroup>

        <Select
          size="sm"
          flex="1"
          minW="140px"
          {...filterFieldProps}
          aria-label={t("hostsDialog.botTab.selectBot") ?? undefined}
          value={selectedBot}
          onChange={(e) => setSelectedBot(e.target.value)}
        >
          {bots.map((bot) => (
            <option key={bot.username} value={bot.username}>
              @{bot.username}
              {bot.title ? ` (${bot.title})` : ""}
            </option>
          ))}
        </Select>

        <ActiveOnlySelect
          isActive={activeOnly}
          onChange={setActiveOnly}
          activeLabel={t("hostsDialog.botTab.availableOnly")}
        />
      </HStack>

      <HStack
        mt={3}
        spacing={2}
        rowGap={2}
        flexWrap="wrap"
        justifyContent="space-between"
        flexShrink={0}
      >
        <Text fontSize="sm" opacity={0.7}>
          {t("hostsDialog.botTab.summary", {
            available: availableCount,
            total: rows.length,
          })}
          {availableDisabledCount > 0 &&
            ` · ${t("hostsDialog.botTab.summaryDisabled", {
              disabled: availableDisabledCount,
            })}`}
        </Text>

        <HStack spacing={2}>
          <Button
            size="xs"
            variant="outline"
            isDisabled={!canEnableAll}
            onClick={() => toggleAllVisible(true)}
          >
            {t("hostsDialog.botTab.enableAll")}
          </Button>
          <Button
            size="xs"
            variant="outline"
            isDisabled={!canDisableAll}
            onClick={() => toggleAllVisible(false)}
          >
            {t("hostsDialog.botTab.disableAll")}
          </Button>
        </HStack>
      </HStack>

      <Box
        mt={2}
        flex="1 1 0"
        minH={0}
        overflowY="auto"
        pr={1}
        pb={4}
        sx={{
          overscrollBehavior: "contain",
          "&::-webkit-scrollbar": { width: "4px" },
          "&::-webkit-scrollbar-track": { background: "transparent" },
          "&::-webkit-scrollbar-thumb": {
            background: "rgba(0, 0, 0, 0.2)",
            borderRadius: "999px",
          },
        }}
      >
        {rows.length === 0 ? (
          <Text opacity={0.7} fontSize="sm" py={4} textAlign="center">
            {t("hostsDialog.notFound")}
          </Text>
        ) : (
          <Table size="sm" variant="unstyled" layout="fixed" sx={botTableSx}>
            <Thead>
              <Tr>
                <Th {...thCell} w="18%" display={wideOnly}>
                  {t("hostsDialog.columnInbound")}
                </Th>
                <Th {...thCell} w={{ base: "auto", md: "30%" }}>
                  Remark
                </Th>
                <Th {...thCell} w="22%" display={wideOnly}>
                  Address
                </Th>
                <Th {...thCell} w="18%" display={wideOnly}>
                  {t("hostsDialog.columnBot")}
                </Th>
                <Th {...thCell} w="112px" whiteSpace="nowrap">
                  {t("hostsDialog.botTab.columnAvailable")}
                </Th>
                <Th {...thCell} w="112px" whiteSpace="nowrap">
                  {t("hostsDialog.botTab.columnRented")}
                </Th>
              </Tr>
            </Thead>
            <Tbody>
              {rows.map((row) => (
                <Tr key={row.id}>
                  <Td {...tdCell} textAlign="left" display={wideOnly}>
                    <Tooltip label={row.inboundTag} placement="top">
                      <Badge
                        colorScheme="gray"
                        fontSize="0.7rem"
                        maxW="100%"
                        isTruncated
                      >
                        {row.inboundTag}
                      </Badge>
                    </Tooltip>
                  </Td>

                  <Td {...tdCell}>
                    <HStack spacing={2} justifyContent="center" minW={0}>
                      <Tooltip
                        label={row.remark}
                        placement="top"
                        isDisabled={!row.remark}
                      >
                        <Text fontSize="sm" isTruncated>
                          {row.remark || "—"}
                        </Text>
                      </Tooltip>
                      {row.isHostDisabled && (
                        <Tooltip
                          label={t("hostsDialog.botTab.hostDisabledHint")}
                          placement="top"
                        >
                          <Badge
                            colorScheme="orange"
                            fontSize="0.65rem"
                            flexShrink={0}
                          >
                            {t("hostsDialog.botTab.hostDisabled")}
                          </Badge>
                        </Tooltip>
                      )}
                    </HStack>
                    <Text
                      fontSize="xs"
                      opacity={0.6}
                      isTruncated
                      display={{ base: "block", md: "none" }}
                    >
                      {row.address || "—"}
                    </Text>
                  </Td>

                  <Td {...tdCell} display={wideOnly}>
                    <Tooltip
                      label={row.address}
                      placement="top"
                      isDisabled={!row.address}
                    >
                      <Text fontSize="sm" opacity={0.7} isTruncated>
                        {row.address || "—"}
                      </Text>
                    </Tooltip>
                  </Td>

                  <Td {...tdCell} display={wideOnly}>
                    <Tooltip
                      label={row.botsTooltip}
                      placement="top"
                      isDisabled={!row.botsTooltip}
                    >
                      <Text fontSize="sm" opacity={0.7} isTruncated>
                        {row.botsLabel}
                      </Text>
                    </Tooltip>
                  </Td>

                  <Td {...tdCell}>
                    {(
                      <Switch
                        colorScheme="primary"
                        verticalAlign="middle"
                        aria-label={
                          t("hostsDialog.botTab.columnAvailable") ?? undefined
                        }
                        isChecked={row.isAvailable}
                        onChange={(e) =>
                          toggleHost(row.index, e.target.checked)
                        }
                      />
                    )}
                  </Td>

                  <Td {...tdCell}>
                    <Tooltip
                      label={t("hostsDialog.botTab.rentedHint")}
                      placement="top"
                      isDisabled={row.isAvailable}
                    >
                      <Box display="inline-flex">
                        <Switch
                          colorScheme="primary"
                          verticalAlign="middle"
                          aria-label={
                            t("hostsDialog.botTab.columnRented") ?? undefined
                          }
                          isChecked={row.isRented}
                          isDisabled={!row.isAvailable}
                          onChange={(e) =>
                            toggleRented(row.index, e.target.checked)
                          }
                        />
                      </Box>
                    </Tooltip>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Box>
    </Box>
  );
};

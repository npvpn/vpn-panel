import {
  Badge,
  Flex,
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
import { useBotSelectStyles } from "hooks/useBotSelectStyles";
import { FC, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactSelect from "react-select";
import { FieldArrayWithId, useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Bot } from "types/Bot";
import { resolveBotTabSelection } from "utils/hostDeepLink";
import { z } from "zod";
import { filterFieldProps, hostsTableSx } from "./constants";
import { hostsFormSchema } from "./schema";
import { NodeType } from "contexts/NodesContext";
import {
  proxyALPN,
  proxyFingerprint,
  proxyHostSecurity,
} from "constants/Proxies";
import { AdvancedOptionsButton } from "./AdvancedOptionsButton";
import { ActiveOnlySelect } from "./ActiveOnlySelect";
import { HostAdvancedOptionsModal } from "./HostAdvancedOptionsModal";
import { hasAdvancedFieldErrors } from "./constants";
import { BotTabOrder, orderBotTabRows } from "./hostsFilter";

type HostField = FieldArrayWithId<z.infer<typeof hostsFormSchema>, "hosts">;

type BotOption = { value: string; label: string };

// Выбранный бот и поиск живут в HostsDialog: сама вкладка
// монтируется, только пока открыта (иначе она, подписанная на все хосты,
// пересчитывалась бы в фоне на каждое изменение на вкладке «Хосты»), а эти
// значения должны переживать переключение вкладок.
// NPVPN-2215: фильтра «Только доступные» здесь нет — доступные боту хосты и
// так наверху, а остальные приглушены. Вкладка про то, что боту включено, а
// что нет, и видна должна быть вся картина; под фильтром выключенная строка
// к тому же сразу пропадала, и включить её обратно было нельзя.
// Зато есть «Только активные», как на вкладке «Хосты»: прячет хосты,
// выключенные глобально (из задачи NPVPN-2182) — они только шумят.
export type BotTabFilters = {
  selectedBot: string;
  search: string;
  activeOnly: boolean;
};

export const EMPTY_BOT_TAB_FILTERS: BotTabFilters = {
  selectedBot: "",
  search: "",
  activeOnly: true,
};

type Props = {
  fields: HostField[];
  bots: Bot[];
  nodes: NodeType[];
  inboundMap: Map<string, any>;
  filters: BotTabFilters;
  /** Ссылка на неизвестного бота: пустой фильтр не подменять первым ботом. */
  keepEmptyBot?: boolean;
  onFiltersChange: (update: Partial<BotTabFilters>) => void;
  // editedIndex — см. saveAndContinue в HostsDialog.
  onSaveAndContinue: (editedIndex?: number) => Promise<boolean>;
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

// NPVPN-2215: хосты, которых у выбранного бота нет, приглушены — хосты бота
// видны сразу, а остальные под рукой, чтобы их включить. Приглушается только
// содержимое: переключатели и шестерёнка остаются чёткими.
const dimmed = (row: { isAvailable: boolean }) =>
  row.isAvailable ? {} : { opacity: 0.45 };

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
  nodes,
  inboundMap,
  filters,
  keepEmptyBot = false,
  onFiltersChange,
  onSaveAndContinue,
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
    const next = resolveBotTabSelection(
      selectedBot,
      bots.map((bot) => bot.username),
      keepEmptyBot
    );
    if (next !== selectedBot) setSelectedBot(next);
  }, [bots, selectedBot, keepEmptyBot]);

  const botSelectStyles = useBotSelectStyles({ size: "sm" });

  // Подпись — как была в обычном select: @username (title). Поиск
  // react-select идёт по ней, так что находит и по username, и по названию.
  const botOptions = useMemo<BotOption[]>(
    () =>
      bots.map((bot) => ({
        value: bot.username,
        label: `@${bot.username}${bot.title ? ` (${bot.title})` : ""}`,
      })),
    [bots]
  );

  const selectedBotOption =
    botOptions.find((option) => option.value === selectedBot) ?? null;

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
  const hostErrors = form.formState.errors.hosts;

  // NPVPN-2215: настройки хоста правятся и отсюда — фильтра по боту на
  // вкладке «Хосты» больше нет, и всё про хосты одного бота собрано здесь.
  // Окно одно на вкладку, открыто для хоста с этим индексом.
  const [advancedIndex, setAdvancedIndex] = useState<number | null>(null);

  // Строки с учётом поиска; фильтр «Только активные» — ниже, чтобы знать,
  // сколько выключенных он спрятал.
  const searchedRows = useMemo(() => {
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
        .filter(
          (row) =>
            !query ||
            row.remark.toLowerCase().includes(query) ||
            row.address.toLowerCase().includes(query)
        )
    );
  }, [
    fields,
    watchedHosts,
    selectedBot,
    allBotUsernames,
    botDisplayNames,
    search,
    t,
  ]);

  const rows = useMemo(
    () =>
      activeOnly
        ? searchedRows.filter((row) => !row.isHostDisabled)
        : searchedRows,
    [searchedRows, activeOnly]
  );
  // Выключенные не прячем молча: сводка говорит, сколько их скрыто, — среди
  // них могут быть привязанные к боту, которые он начнёт выдавать, как только
  // хост включат.
  const hiddenDisabledCount = searchedRows.length - rows.length;

  // NPVPN-2215: доступные боту — наверху, см. orderBotTabRows (порядок не
  // прыгает от щелчков переключателя, только от смены бота и поиска).
  const orderRef = useRef<BotTabOrder | null>(null);
  const orderedRows = useMemo(() => {
    const { order, state } = orderBotTabRows(
      rows.map((row) => row.id),
      rows.map((row) => row.isAvailable),
      JSON.stringify([selectedBot, search.trim().toLowerCase(), activeOnly]),
      orderRef.current
    );
    orderRef.current = state;
    return order.map((index) => rows[index]);
  }, [rows, selectedBot, search, activeOnly]);

  const availableCount = rows.filter((row) => row.isAvailable).length;
  // Доступные боту, но выключенные глобально — бот их сейчас не выдаёт.
  const availableDisabledCount = rows.filter(
    (row) => row.isAvailable && row.isHostDisabled
  ).length;
  const canEnableAll = rows.some((row) => !row.isAvailable);
  const canDisableAll = rows.some((row) => row.isAvailable);

  const bindingsLocked = selectedBot === "";

  const toggleHost = useCallback(
    (index: number, enable: boolean) => {
      if (!selectedBot) return;
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
      if (!selectedBot) return;
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

  // На телефоне поля ячеек уже: иначе колонки переключателей съедали всю
  // ширину, и от remark оставалось «🚀 …» (NPVPN-2215).
  const thCell = {
    px: { base: 1, md: 3 },
    py: 2,
    textAlign: "center" as const,
    color: "gray.600",
    position: "sticky" as const,
    top: 0,
    zIndex: 1,
    _dark: { color: "gray.400" },
  };

  const tdCell = {
    px: { base: 1, md: 3 },
    py: 2,
    textAlign: "center" as const,
  };

  return (
    <Box display="flex" flexDirection="column" minH={0} h="full">
      {/* NPVPN-2215: одна строка — бот и поиск слева (бот первым: от него
          зависит всё ниже), сводка и массовые действия справа. Без фильтра
          доступности поиск на всю ширину растягивался. Flex с gap, а не
          HStack: отступы HStack — margin слева, он перебивал ml="auto" и
          сдвигал первый элемент перенесённой строки. */}
      <Flex mt={1} gap={2} flexWrap="wrap" flexShrink={0}>
        {/* С поиском: ботов бывает много, а в обычном select название не
            начать вводить. */}
        {/* Ширины подобраны так, чтобы строка помещалась целиком: поиск
            гибкий и сжимается первым, сводка с кнопками не переносится. */}
        <Box w={{ base: "full", md: "240px" }}>
          <ReactSelect<BotOption>
            aria-label={t("hostsDialog.botTab.selectBot") ?? undefined}
            options={botOptions}
            value={selectedBotOption}
            onChange={(option: BotOption | null) =>
              option && setSelectedBot(option.value)
            }
            noOptionsMessage={() => t("botSettings.noBotsFound")}
            isSearchable
            styles={botSelectStyles}
            menuPortalTarget={document.body}
            menuPosition="fixed"
          />
        </Box>

        <InputGroup
          w={{ base: "full", md: "auto" }}
          flex={{ md: "1 1 200px" }}
          maxW={{ md: "280px" }}
          size="sm"
        >
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

        <Box w={{ base: "full", md: "160px" }}>
          <ActiveOnlySelect isActive={activeOnly} onChange={setActiveOnly} />
        </Box>

        {/* На телефоне — сводка слева, под ней кнопки поровну во всю
            ширину; на десктопе — всё в ряд у правого края. */}
        <Flex
          ml="auto"
          w={{ base: "full", md: "auto" }}
          gap={3}
          rowGap={2}
          flexWrap="wrap"
          alignItems="center"
          justifyContent={{ base: "flex-start", md: "flex-end" }}
        >
          <Text fontSize="sm" opacity={0.7} whiteSpace="nowrap">
            {t("hostsDialog.botTab.summary", {
              available: availableCount,
              total: rows.length,
            })}
            {availableDisabledCount > 0 &&
              ` · ${t("hostsDialog.botTab.summaryDisabled", {
                disabled: availableDisabledCount,
              })}`}
            {hiddenDisabledCount > 0 &&
              ` · ${t("hostsDialog.botTab.summaryHidden", {
                hidden: hiddenDisabledCount,
              })}`}
          </Text>

          <HStack spacing={2} w={{ base: "full", md: "auto" }}>
            <Button
              size="sm"
              flex={{ base: 1, md: "none" }}
              variant="outline"
              isDisabled={bindingsLocked || !canEnableAll}
              onClick={() => toggleAllVisible(true)}
            >
              {t("hostsDialog.botTab.enableAll")}
            </Button>
            <Button
              size="sm"
              flex={{ base: 1, md: "none" }}
              variant="outline"
              isDisabled={bindingsLocked || !canDisableAll}
              onClick={() => toggleAllVisible(false)}
            >
              {t("hostsDialog.botTab.disableAll")}
            </Button>
          </HStack>
        </Flex>
      </Flex>

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
                <Th
                  {...thCell}
                  w={{ base: "auto", md: "30%" }}
                  textAlign={{ base: "left", md: "center" }}
                  pl={3}
                  whiteSpace="nowrap"
                >
                  Remark
                </Th>
                <Th {...thCell} w="22%" display={wideOnly}>
                  Address
                </Th>
                <Th {...thCell} w="18%" display={wideOnly}>
                  {t("hostsDialog.columnBot")}
                </Th>
                <Th
                  {...thCell}
                  w={{ base: "84px", md: "112px" }}
                  whiteSpace="nowrap"
                >
                  {t("hostsDialog.botTab.columnAvailable")}
                </Th>
                <Th
                  {...thCell}
                  w={{ base: "72px", md: "112px" }}
                  whiteSpace="nowrap"
                >
                  {t("hostsDialog.botTab.columnRented")}
                </Th>
                <Th {...thCell} w={{ base: "36px", md: "48px" }} px={1} />
              </Tr>
            </Thead>
            <Tbody>
              {orderedRows.map((row) => (
                <Tr key={row.id}>
                  <Td
                    {...tdCell}
                    {...dimmed(row)}
                    textAlign="left"
                    display={wideOnly}
                  >
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

                  <Td
                    {...tdCell}
                    {...dimmed(row)}
                    textAlign={{ base: "left", md: "center" }}
                    pl={3}
                  >
                    <HStack
                      spacing={2}
                      justifyContent={{ base: "flex-start", md: "center" }}
                      minW={0}
                    >
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

                  <Td {...tdCell} {...dimmed(row)} display={wideOnly}>
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

                  <Td {...tdCell} {...dimmed(row)} display={wideOnly}>
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
                        isDisabled={bindingsLocked}
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
                          isDisabled={bindingsLocked || !row.isAvailable}
                          onChange={(e) =>
                            toggleRented(row.index, e.target.checked)
                          }
                        />
                      </Box>
                    </Tooltip>
                  </Td>

                  <Td {...tdCell} px={1}>
                    <AdvancedOptionsButton
                      hasErrors={hasAdvancedFieldErrors(
                        hostErrors?.[row.index]
                      )}
                      onClick={() => setAdvancedIndex(row.index)}
                    />
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Box>

      {advancedIndex !== null && (
        <HostAdvancedOptionsModal
          isOpen
          onClose={() => setAdvancedIndex(null)}
          onSaveAndContinue={() => onSaveAndContinue(advancedIndex)}
          hostKey="hosts"
          index={advancedIndex}
          inbound={inboundMap.get(
            watchedHosts?.[advancedIndex]?.inbound_tag ?? ""
          )}
          register={form.register}
          control={form.control}
          accordionErrors={hostErrors?.[advancedIndex]}
          t={t}
          bots={bots}
          nodes={nodes}
          proxyHostSecurity={proxyHostSecurity}
          proxyALPN={proxyALPN}
          proxyFingerprint={proxyFingerprint}
          remark={watchedHosts?.[advancedIndex]?.remark}
        />
      )}
    </Box>
  );
};

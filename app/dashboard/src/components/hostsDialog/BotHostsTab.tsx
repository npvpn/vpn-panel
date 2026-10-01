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
// (visibility=restricted без привязок). Раньше выключение последнего бота
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

// Замок (heroicons 20/solid lock-closed) в кружке тумблера: цвет обычный —
// хост действительно доступен, — но видно, что тумблер зафиксирован. Маска,
// а не вложенная иконка, чтобы не менять размеры и выравнивание колонки.
// NPVPN-2044: теперь он помечает ОБЩИЙ хост (visibility=shared): такой виден
// всем ботам по видимости, и привязкой его не отобрать — видимость меняется
// на вкладке «Хосты». Прежде замок означал другое: «список опустеет и хост
// уйдёт всем», проблемы, которой больше нет.
const lockIconMask = `url("data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path fill-rule="evenodd" clip-rule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"/></svg>'
)}")`;

const lockedThumbSx = {
  ".chakra-switch__thumb": { position: "relative" },
  ".chakra-switch__thumb::after": {
    content: '""',
    position: "absolute",
    inset: 0,
    m: "auto",
    w: "60%",
    h: "60%",
    bg: "primary.500",
    maskImage: lockIconMask,
    WebkitMaskImage: lockIconMask,
    maskSize: "contain",
    WebkitMaskSize: "contain",
    maskRepeat: "no-repeat",
    WebkitMaskRepeat: "no-repeat",
    maskPosition: "center",
    WebkitMaskPosition: "center",
  },
};

// Общий хост (visibility=shared) достаётся всем ботам панели, поэтому тумблер
// доступности для него только показывает состояние: отобрать хост у бота можно
// лишь сменив видимость на вкладке «Хосты». Поповер с кнопкой «Выключить хост»
// здесь был нужен, пока тумблер был мёртв из-за костыля «пустой список = всем»;
// теперь объяснения достаточно в тултипе.
const SharedHostSwitch: FC = () => {
  const { t } = useTranslation();

  return (
    <Tooltip label={t("hostsDialog.botTab.sharedTooltip")} placement="top">
      <Box display="inline-flex" verticalAlign="middle">
        <Switch
          colorScheme="primary"
          sx={lockedThumbSx}
          aria-label={t("hostsDialog.botTab.columnAvailable") ?? undefined}
          isChecked
          isReadOnly
          pointerEvents="none"
        />
      </Box>
    </Tooltip>
  );
};

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
          // NPVPN-2044: доступность решает видимость, а не пустота списка.
          const isShared = host?.visibility === "shared";
          const isAvailable = isShared || botUsernames.includes(selectedBot);

          return {
            id: field.id,
            index,
            inboundTag: host?.inbound_tag ?? "",
            remark: host?.remark ?? "",
            address: host?.address ?? "",
            isHostDisabled: !!host?.is_disabled,
            botsLabel: isShared
              ? t("hostsDialog.availableBots.all")
              : botUsernames.length === 0
                ? t("hostsDialog.availableBots.none")
                : botUsernames.map((username) => `@${username}`).join(", "),
            botsTooltip: (isShared ? allBotUsernames : botUsernames)
              .map(
                (username) => botDisplayNames.get(username) ?? `@${username}`
              )
              .join(", "),
            isAvailable,
            isShared,
          };
        })
        // «Активный» здесь — строка с включённым тумблером: доступная выбранному
        // боту. Общий хост (SharedHostSwitch) доступен всегда.
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
  const canDisableAll = rows.some((row) => row.isAvailable && !row.isShared);

  const toggleHost = useCallback(
    (index: number, enable: boolean) => {
      const current: string[] =
        form.getValues(`hosts.${index}.bot_usernames`) || [];

      form.setValue(
        `hosts.${index}.bot_usernames`,
        nextBotUsernames(current, selectedBot, enable),
        { shouldDirty: true }
      );
    },
    [form, selectedBot]
  );

  // Действует только на видимые строки (с учётом поиска и фильтра), так что
  // «отключить все» после поиска трогает лишь найденные хосты. Общие хосты
  // пропускаем: привязкой их доступность не изменить.
  const toggleAllVisible = (enable: boolean) => {
    rows
      .filter((row) =>
        enable ? !row.isAvailable && !row.isShared : row.isAvailable && !row.isShared
      )
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
                    {row.isShared ? (
                      <SharedHostSwitch />
                    ) : (
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
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Box>
    </Box>
  );
};

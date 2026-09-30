import {
  Box,
  Button,
  Collapse,
  Flex,
  HStack,
  Input,
  InputGroup,
  InputLeftElement,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Stack,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  useToast,
} from "@chakra-ui/react";
import { PlusIcon as HeroIconPlusIcon } from "@heroicons/react/24/outline";
import { MagnifyingGlassIcon } from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import { useHosts } from "contexts/HostsContext";
import { FC, useCallback, useEffect, useMemo, useState } from "react";
import { FormProvider, useFieldArray, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { Bot } from "types/Bot";
import { z } from "zod";
import { useDashboard } from "../contexts/DashboardContext";
import { NodeType } from "../contexts/NodesContext";
import { Icon } from "./Icon";
import { hostItemSchema, hostsFormSchema } from "./hostsDialog/schema";
import { filterFieldProps, ModalIcon, Select } from "./hostsDialog/constants";
import { ActiveOnlySelect } from "./hostsDialog/ActiveOnlySelect";
import { HostsList } from "./hostsDialog/HostsList";
import { AddHostForm, EMPTY_HOST } from "./hostsDialog/AddHostForm";
import {
  BotHostsTab,
  BotTabFilters,
  EMPTY_BOT_TAB_FILTERS,
} from "./hostsDialog/BotHostsTab";

type HostsDict = Record<string, any[]>;

function flattenHosts(hosts: HostsDict | null | undefined) {
  if (!hosts) return [];

  const items = Object.entries(hosts).flatMap(([inbound_tag, hostList]) =>
    (hostList as any[]).map((host) => ({
      ...host,
      inbound_tag,
      order: typeof host.order === "number" ? host.order : 0,
      xhttp_extra: host.xhttp_extra
        ? JSON.stringify(host.xhttp_extra, null, 2)
        : "",
    }))
  );

  return items.sort((a, b) => a.order - b.order || 0);
}

function groupHosts(
  hosts: z.infer<typeof hostsFormSchema>["hosts"],
  inboundTags: string[]
): HostsDict {
  const payload: HostsDict = Object.fromEntries(
    inboundTags.map((tag) => [tag, [] as any[]])
  );

  hosts.forEach((host, index) => {
    const { inbound_tag, ...rest } = host;

    if (!payload[inbound_tag]) {
      payload[inbound_tag] = [];
    }

    payload[inbound_tag].push({
      ...rest,
      order: index,
      xhttp_extra: rest.xhttp_extra ? JSON.parse(rest.xhttp_extra) : null,
    });
  });

  return payload;
}

export const HostsDialog: FC = () => {
  const { isEditingHosts, onEditingHosts, refetchUsers, inbounds } =
    useDashboard();

  const { isLoading, hosts, fetchHosts, isPostLoading, setHosts } = useHosts();

  const toast = useToast();
  const { t } = useTranslation();

  const [bots, setBots] = useState<Bot[]>([]);
  const [nodes, setNodes] = useState<NodeType[]>([]);
  // Боты и ноды грузятся отдельно от хостов (useHosts знает только о своих).
  // Пока их нет, держим лоадер: иначе интерфейс появлялся без вкладок, а они
  // «впрыгивали» позже и сдвигали всё вниз.
  const [isAuxLoading, setIsAuxLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [inboundFilter, setInboundFilter] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);

  const [isAddingHost, setIsAddingHost] = useState(false);
  const [tabIndex, setTabIndex] = useState(0);
  const [botTabFilters, setBotTabFilters] = useState<BotTabFilters>(
    EMPTY_BOT_TAB_FILTERS
  );
  const updateBotTabFilters = useCallback(
    (update: Partial<BotTabFilters>) =>
      setBotTabFilters((prev) => ({ ...prev, ...update })),
    []
  );

  // С одним ботом вкладка «По ботам» бессмысленна: единственного бота у хоста
  // не выключить (пустой список = «все боты»), все переключатели заблокированы.
  const hasBotTab = bots.length >= 2;

  const inboundMap = useMemo(() => {
    const map = new Map();

    const list =
      inbounds instanceof Map ? Array.from(inbounds.values()).flat() : [];

    for (const i of list) {
      map.set(i.tag, i);
    }

    return map;
  }, [inbounds]);

  const inboundTags = useMemo(() => {
    return hosts ? Object.keys(hosts) : [];
  }, [hosts]);

  useEffect(() => {
    if (!isEditingHosts) return;

    const loadData = async () => {
      setIsAuxLoading(true);

      try {
        const [, botsData, nodesData] = await Promise.all([
          fetchHosts(),
          fetch<Bot[]>("/bots").catch(() => [] as Bot[]),
          fetch<NodeType[]>("/nodes").catch(() => [] as NodeType[]),
        ]);

        setBots(botsData);
        setNodes(nodesData);
      } catch (error) {
        console.error("Failed to load data:", error);
      } finally {
        setIsAuxLoading(false);
      }
    };

    loadData();
  }, [isEditingHosts, fetchHosts]);

  const form = useForm<z.infer<typeof hostsFormSchema>>({
    resolver: zodResolver(hostsFormSchema),
    shouldUnregister: false,
    defaultValues: {
      hosts: [],
    },
  });

  const { fields, prepend, insert, move, remove } = useFieldArray({
    control: form.control,
    name: "hosts",
  });

  useEffect(() => {
    if (hosts && isEditingHosts) {
      form.reset({
        hosts: flattenHosts(hosts),
      });

      setSearch("");
      setInboundFilter("");
      setBotFilter("");
      setActiveOnly(false);
      setBotTabFilters(EMPTY_BOT_TAB_FILTERS);
    }
  }, [hosts, isEditingHosts, form]);

  const onClose = useCallback(() => {
    setSearch("");
    setInboundFilter("");
    setBotFilter("");
    setActiveOnly(false);
    setBotTabFilters(EMPTY_BOT_TAB_FILTERS);
    setIsAddingHost(false);
    setTabIndex(0);
    setIsAuxLoading(true);

    onEditingHosts(false);
  }, [onEditingHosts]);

  const submitHosts = useCallback(
    (
      hostsData: z.infer<typeof hostsFormSchema>,
      { closeAfter }: { closeAfter: boolean }
    ) => {
      const payload = groupHosts(hostsData.hosts, inboundTags);

      return setHosts(payload)
        .then(() => {
          toast({
            title: t("hostsDialog.savedSuccess"),
            status: "success",
            isClosable: true,
            position: "top",
            duration: 3000,
          });

          refetchUsers();

          if (closeAfter) {
            onClose();
          }
        })
        .catch((err) => {
          if (err?.response?.status === 409 || err?.response?.status === 400) {
            toast({
              title: err.response?._data?.detail,
              status: "error",
              isClosable: true,
              position: "top",
              duration: 3000,
            });
          }

          if (err?.response?.status === 422) {
            Object.keys(err.response._data.detail).forEach((key) => {
              toast({
                title: err.response._data.detail[key] + " (" + key + ")",
                status: "error",
                isClosable: true,
                position: "top",
                duration: 3000,
              });
            });
          }
        });
    },
    [setHosts, toast, t, refetchUsers, onClose, inboundTags]
  );

  const handleFormSubmit = useCallback(
    (hostsData: z.infer<typeof hostsFormSchema>) =>
      submitHosts(hostsData, { closeAfter: true }),
    [submitHosts]
  );

  const handleFormSubmitAndContinue = useCallback(
    (hostsData: z.infer<typeof hostsFormSchema>) =>
      submitHosts(hostsData, { closeAfter: false }),
    [submitHosts]
  );

  // Ошибки валидации подсвечиваются только в строках вкладки «Хосты» —
  // если сохраняют с вкладки «Боты», переводим туда, чтобы их было видно.
  const handleInvalidSubmit = useCallback(() => setTabIndex(0), []);

  // Добавление хоста — действие редкое, поэтому компактная кнопка: справа в
  // строке вкладок (только на «Хостах»), а без вкладок — в конце строки
  // фильтров. Форма по-прежнему раскрывается над списком; плюс в раскрытом
  // состоянии поворачивается в крестик.
  // Активная вкладка — ещё и полужирным, не только цветом подчёркивания.
  // Через sx, а не _selected: проп _selected заменил бы стиль темы для
  // выбранной вкладки целиком (цвет и подчёркивание), а не дополнил его.
  const tabProps = {
    fontWeight: "medium",
    sx: { "&[aria-selected=true]": { fontWeight: "semibold" } },
  };

  const addHostButton = (
    <Button
      size="sm"
      flexShrink={0}
      variant="outline"
      colorScheme="primary"
      borderRadius="6px"
      // В палитре primary и 50/100 — насыщенные, штатный hover outline-кнопки
      // (bg primary.50) сливается с текстом; берём полупрозрачный primary.500.
      _hover={{ bg: "rgba(57, 111, 228, 0.08)" }}
      _active={{ bg: "rgba(57, 111, 228, 0.16)" }}
      _dark={{
        _hover: { bg: "rgba(116, 154, 236, 0.12)" },
        _active: { bg: "rgba(116, 154, 236, 0.2)" },
      }}
      aria-expanded={isAddingHost}
      leftIcon={
        <HeroIconPlusIcon
          width="16px"
          strokeWidth={2}
          style={{
            transform: isAddingHost ? "rotate(45deg)" : "rotate(0deg)",
            transition: "transform 0.2s ease",
          }}
        />
      }
      onClick={() => setIsAddingHost((prev) => !prev)}
    >
      {t("hostsDialog.addNewHost")}
    </Button>
  );

  const handleHostAdded = useCallback(
    (host: z.infer<typeof hostItemSchema>) => {
      prepend({
        ...EMPTY_HOST,
        ...host,
      });

      setIsAddingHost(false);
    },
    [prepend]
  );

  return (
    <Modal isOpen={isEditingHosts} onClose={onClose}>
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />

      <ModalContent
        mx="3"
        mt="3vh"
        mb="3vh"
        w="full"
        maxW="1320px"
        h="94vh"
        maxH="94vh"
      >
        <ModalHeader pt={6}>
          <HStack spacing={4} align="center">
            <Icon color="primary">
              <ModalIcon color="white" />
            </Icon>

            <Box>
              <Text fontSize="lg" fontWeight="semibold">
                {t("hostsDialog.header")}
              </Text>

              <Text
                fontSize="sm"
                opacity={0.6}
                mt={1}
                maxW="490px"
                lineHeight="1.4"
              >
                {t("hostsDialog.title")}
              </Text>
            </Box>
          </HStack>
        </ModalHeader>

        <ModalCloseButton mt={3} />

        <ModalBody
          pb={0}
          pt={1}
          px={6}
          display="flex"
          flexDirection="column"
          minH={0}
          overflow="hidden"
        >
          <FormProvider {...form}>
            <form
              onSubmit={form.handleSubmit(
                handleFormSubmit,
                handleInvalidSubmit
              )}
              style={{
                display: "flex",
                flexDirection: "column",
                height: "100%",
                minHeight: 0,
                overflow: "hidden",
              }}
            >
              {isLoading || isAuxLoading ? (
                <Flex
                  flex="1"
                  direction="column"
                  align="center"
                  justify="center"
                  gap={3}
                >
                  <Spinner
                    size="lg"
                    thickness="3px"
                    color="primary.500"
                    emptyColor="gray.200"
                    _dark={{ emptyColor: "gray.600" }}
                  />
                  <Text fontSize="sm" opacity={0.7}>
                    {t("hostsDialog.loading")}
                  </Text>
                </Flex>
              ) : (
                <Tabs
                  index={hasBotTab ? tabIndex : 0}
                  onChange={setTabIndex}
                  colorScheme="primary"
                  size="md"
                  isLazy
                  lazyBehavior="keepMounted"
                  display="flex"
                  flexDirection="column"
                  flex="1 1 0"
                  minH={0}
                >
                  {hasBotTab && (
                    <TabList flexShrink={0}>
                      <Tab {...tabProps}>{t("hostsDialog.tabHosts")}</Tab>
                      <Tab {...tabProps}>{t("hostsDialog.tabBots")}</Tab>
                      {/* Не убираем, а прячем: кнопка выше вкладок, и без неё
                          строка вкладок проседала при переключении. */}
                      <Box
                        ml="auto"
                        alignSelf="center"
                        pb={1}
                        visibility={tabIndex === 0 ? "visible" : "hidden"}
                      >
                        {addHostButton}
                      </Box>
                    </TabList>
                  )}

                  <TabPanels flex="1 1 0" minH={0}>
                    <TabPanel px={0} pt={hasBotTab ? 3 : 0} pb={0} h="full">
                      <Box
                        display="flex"
                        flexDirection="column"
                        h="full"
                        minH={0}
                      >
                        <Box flexShrink={0}>
                          {/* SEARCH + FILTERS */}
                          <HStack mt={1} spacing={2} rowGap={2} flexWrap="wrap">
                            <InputGroup flex="2" minW="180px" size="sm">
                              <InputLeftElement pointerEvents="none">
                                <MagnifyingGlassIcon
                                  width="16px"
                                  color="gray"
                                />
                              </InputLeftElement>

                              <Input
                                placeholder={
                                  t("hostsDialog.search") ??
                                  "Search by remark or address..."
                                }
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
                              aria-label={
                                t("hostsDialog.filterInbound") ?? undefined
                              }
                              value={inboundFilter}
                              onChange={(e) => setInboundFilter(e.target.value)}
                              sx={{
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                              }}
                            >
                              <option value="">
                                {t("hostsDialog.allInbounds")}
                              </option>

                              {inboundTags.map((tag) => (
                                <option key={tag} value={tag}>
                                  {tag}
                                </option>
                              ))}
                            </Select>

                            {bots.length >= 2 && (
                              <Select
                                size="sm"
                                flex="1"
                                minW="140px"
                                {...filterFieldProps}
                                aria-label={
                                  t("hostsDialog.filterBot") ?? undefined
                                }
                                value={botFilter}
                                onChange={(e) => setBotFilter(e.target.value)}
                                sx={{
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                  overflow: "hidden",
                                }}
                              >
                                <option value="">
                                  {t("hostsDialog.allBots")}
                                </option>

                                {bots.map((bot) => (
                                  <option
                                    key={bot.username}
                                    value={bot.username}
                                  >
                                    @{bot.username}
                                    {bot.title ? ` (${bot.title})` : ""}
                                  </option>
                                ))}
                              </Select>
                            )}

                            <ActiveOnlySelect
                              isActive={activeOnly}
                              onChange={setActiveOnly}
                              activeLabel={t("hostsDialog.activeOnly")}
                            />

                            {!hasBotTab && addHostButton}
                          </HStack>

                          {/* ADD HOST FORM — в закреплённой части, вне
                              прокрутки: список можно листать, не закрывая
                              форму. pr как у области прокрутки списка. */}
                          <Collapse in={isAddingHost} animateOpacity>
                            <Box pt={2} pr={1}>
                              <AddHostForm
                                inboundTags={inboundTags}
                                defaultInboundTag={
                                  inboundFilter || inboundTags[0] || ""
                                }
                                bots={bots}
                                nodes={nodes}
                                inboundMap={inboundMap}
                                onAdded={handleHostAdded}
                              />
                            </Box>
                          </Collapse>
                        </Box>

                        <Box
                          mt={2}
                          flex="1 1 0"
                          minH={0}
                          overflowY="auto"
                          overflowX="auto"
                          pr={1}
                          pb={4}
                          sx={{
                            overscrollBehavior: "contain",

                            "&::-webkit-scrollbar": {
                              width: "4px",
                            },

                            "&::-webkit-scrollbar-track": {
                              background: "transparent",
                            },

                            "&::-webkit-scrollbar-thumb": {
                              background: "rgba(0, 0, 0, 0.2)",
                              borderRadius: "999px",
                            },
                          }}
                        >
                          {/* HOSTS LIST */}
                          <HostsList
                            fields={fields}
                            inboundTags={inboundTags}
                            inboundFilter={inboundFilter}
                            botFilter={botFilter}
                            activeOnly={activeOnly}
                            search={search}
                            bots={bots}
                            nodes={nodes}
                            inboundMap={inboundMap}
                            insert={insert}
                            move={move}
                            remove={remove}
                          />
                        </Box>
                      </Box>
                    </TabPanel>

                    {hasBotTab && (
                      <TabPanel px={0} pt={3} pb={0} h="full">
                        {/* Только пока вкладка открыта — см. BotTabFilters. */}
                        {tabIndex === 1 && (
                          <BotHostsTab
                            fields={fields}
                            bots={bots}
                            filters={botTabFilters}
                            onFiltersChange={updateBotTabFilters}
                          />
                        )}
                      </TabPanel>
                    )}
                  </TabPanels>
                </Tabs>
              )}

              <Stack
                direction={{ base: "column", md: "row" }}
                justifyContent="flex-end"
                align={{ base: "stretch", md: "center" }}
                py={3}
                px={0}
                spacing={2}
                flexShrink={0}
                bg="white"
                _dark={{
                  bg: "gray.700",
                }}
              >
                <Button
                  variant="outline"
                  type="button"
                  colorScheme="primary"
                  size="sm"
                  px={5}
                  whiteSpace="nowrap"
                  _hover={{ bg: "primary.500", color: "white" }}
                  disabled={isPostLoading}
                  onClick={form.handleSubmit(
                    handleFormSubmitAndContinue,
                    handleInvalidSubmit
                  )}
                >
                  {t("hostsDialog.applyAndContinue")}
                </Button>

                <Button
                  variant="solid"
                  type="submit"
                  colorScheme="primary"
                  size="sm"
                  px={5}
                  whiteSpace="nowrap"
                  disabled={isPostLoading}
                >
                  {t("hostsDialog.apply")}
                </Button>
              </Stack>
            </form>
          </FormProvider>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

import {
  Box,
  Button,
  Collapse,
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
  Select,
  Stack,
  Text,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { PlusIcon as HeroIconPlusIcon } from "@heroicons/react/24/outline";
import {
  ChevronDownIcon,
  MagnifyingGlassIcon,
} from "@heroicons/react/24/outline";
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
import { ModalIcon } from "./hostsDialog/constants";
import { HostsList } from "./hostsDialog/HostsList";
import { AddHostForm, EMPTY_HOST } from "./hostsDialog/AddHostForm";

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

  const [search, setSearch] = useState("");
  const [inboundFilter, setInboundFilter] = useState("");
  const [botFilter, setBotFilter] = useState("");

  const [isAddingHost, setIsAddingHost] = useState(false);

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
      try {
        await fetchHosts();

        const [botsData, nodesData] = await Promise.all([
          fetch<Bot[]>("/bots").catch(() => [] as Bot[]),
          fetch<NodeType[]>("/nodes").catch(() => [] as NodeType[]),
        ]);

        setBots(botsData);
        setNodes(nodesData);
      } catch (error) {
        console.error("Failed to load data:", error);
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
    }
  }, [hosts, isEditingHosts, form]);

  const onClose = useCallback(() => {
    setSearch("");
    setInboundFilter("");
    setBotFilter("");
    setIsAddingHost(false);

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

  const [isContinueSubmitting, setIsContinueSubmitting] = useState(false);

  const handleFormSubmit = useCallback(
    (hostsData: z.infer<typeof hostsFormSchema>) =>
      submitHosts(hostsData, { closeAfter: true }),
    [submitHosts]
  );

  const handleFormSubmitAndContinue = useCallback(
    (hostsData: z.infer<typeof hostsFormSchema>) => {
      setIsContinueSubmitting(true);
      return submitHosts(hostsData, { closeAfter: false }).finally(() =>
        setIsContinueSubmitting(false)
      );
    },
    [submitHosts]
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

      <ModalContent mx="3" w="full" maxW="2xl" h="90vh" maxH="90vh">
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
          pt={3}
          px={6}
          display="flex"
          flexDirection="column"
          minH={0}
          overflow="hidden"
        >
          <FormProvider {...form}>
            <form
              onSubmit={form.handleSubmit(handleFormSubmit)}
              style={{
                display: "flex",
                flexDirection: "column",
                height: "100%",
                minHeight: 0,
                overflow: "hidden",
              }}
            >
              {isLoading ? (
                <Text>{t("hostsDialog.loading")}</Text>
              ) : (
                <>
                  <Box flexShrink={0}>
                    {/* SEARCH + FILTERS */}
                    {(() => {
                      const searchInput = (
                        <InputGroup flex="1" minW={0}>
                          <InputLeftElement pointerEvents="none">
                            <MagnifyingGlassIcon width="16px" color="gray" />
                          </InputLeftElement>

                          <Input
                            placeholder={
                              t("hostsDialog.search") ??
                              "Search by remark or address..."
                            }
                            size="md"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                          />
                        </InputGroup>
                      );

                      const inboundSelect = (
                        <Select
                          size="md"
                          flex="1"
                          minW={0}
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
                      );

                      if (bots.length === 0) {
                        return (
                          <HStack mt={3} spacing={2}>
                            {searchInput}
                            {inboundSelect}
                          </HStack>
                        );
                      }

                      const botSelect = (
                        <Select
                          size="md"
                          flex="1"
                          minW={0}
                          aria-label={t("hostsDialog.filterBot") ?? undefined}
                          value={botFilter}
                          onChange={(e) => setBotFilter(e.target.value)}
                          sx={{
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                          }}
                        >
                          <option value="">{t("hostsDialog.allBots")}</option>

                          {bots.map((bot) => (
                            <option key={bot.username} value={bot.username}>
                              @{bot.username}
                              {bot.title ? ` (${bot.title})` : ""}
                            </option>
                          ))}
                        </Select>
                      );

                      return (
                        <VStack mt={3} spacing={2} align="stretch">
                          <HStack spacing={2}>{searchInput}</HStack>
                          <HStack spacing={2}>
                            {inboundSelect}
                            {botSelect}
                          </HStack>
                        </VStack>
                      );
                    })()}

                    {/* ADD HOST BUTTON */}
                    <Button
                      mt={3}
                      w="full"
                      variant="outline"
                      leftIcon={
                        <HeroIconPlusIcon width="20px" strokeWidth={2} />
                      }
                      rightIcon={
                        <ChevronDownIcon
                          width="16px"
                          style={{
                            transform: isAddingHost
                              ? "rotate(180deg)"
                              : "rotate(0deg)",
                            transition: "transform 0.2s ease",
                          }}
                        />
                      }
                      onClick={() => setIsAddingHost((prev) => !prev)}
                    >
                      {t("hostsDialog.addNewHost")}
                    </Button>
                  </Box>

                  <Box
                    mt={3}
                    flex="1 1 0"
                    minH={0}
                    overflowY="auto"
                    overflowX="hidden"
                    pr={2}
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
                    {/* ADD HOST FORM */}
                    <Collapse in={isAddingHost} animateOpacity>
                      <Box pt={0} pb={3}>
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

                    {/* HOSTS LIST */}
                    <HostsList
                      fields={fields}
                      inboundTags={inboundTags}
                      inboundFilter={inboundFilter}
                      botFilter={botFilter}
                      search={search}
                      bots={bots}
                      nodes={nodes}
                      inboundMap={inboundMap}
                      insert={insert}
                      move={move}
                      remove={remove}
                    />
                  </Box>
                </>
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
                  isLoading={isContinueSubmitting}
                  loadingText={t("hostsDialog.applyAndContinue")}
                  disabled={isPostLoading}
                  onClick={form.handleSubmit(handleFormSubmitAndContinue)}
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
                  isLoading={isPostLoading && !isContinueSubmitting}
                  loadingText={t("hostsDialog.apply")}
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

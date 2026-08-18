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
  const ordered = [...hosts].sort((a, b) => a.order - b.order);
  ordered.forEach((host, index) => {
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
    defaultValues: { hosts: [] },
  });

  const { append } = useFieldArray({
    control: form.control,
    name: "hosts",
  });

  useEffect(() => {
    if (hosts && isEditingHosts) {
      form.reset({ hosts: flattenHosts(hosts) });
      setSearch("");
      setInboundFilter("");
    }
  }, [hosts, isEditingHosts, form]);

  const onClose = useCallback(() => {
    setSearch("");
    setInboundFilter("");
    onEditingHosts(false);
  }, [onEditingHosts]);

  const handleFormSubmit = useCallback(
    (hostsData: z.infer<typeof hostsFormSchema>) => {
      const payload = groupHosts(hostsData.hosts, inboundTags);
      setHosts(payload)
        .then(() => {
          toast({
            title: t("hostsDialog.savedSuccess"),
            status: "success",
            isClosable: true,
            position: "top",
            duration: 3000,
          });
          refetchUsers();
          onClose();
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

  const handleHostAdded = useCallback(
    (host: z.infer<typeof hostItemSchema>) => {
      const current = form.getValues("hosts") || [];

      append({
        ...EMPTY_HOST,
        ...host,
        order: current.length,
      });

      setIsAddingHost(false);
    },
    [append, form]
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
                t("hostsDialog.loading")
              ) : (
                <>
                  <HStack mt={3} spacing={2} flexShrink={0}>
                    <InputGroup flex="1" minW={0}>
                      <InputLeftElement pointerEvents="none">
                        <MagnifyingGlassIcon width="16px" color="gray" />
                      </InputLeftElement>
                      <Input
                        placeholder={
                          t("hostsDialog.search") ?? "Search by remark..."
                        }
                        size="md"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </InputGroup>

                    <Select
                      size="md"
                      flex="1"
                      minW={0}
                      value={inboundFilter}
                      onChange={(e) => setInboundFilter(e.target.value)}
                      sx={{
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                      }}
                    >
                      <option value="">{t("hostsDialog.allInbounds")}</option>
                      {inboundTags.map((tag) => (
                        <option key={tag} value={tag}>
                          {tag}
                        </option>
                      ))}
                    </Select>
                  </HStack>

                  <Button
                    mt={3}
                    w="full"
                    flexShrink={0}
                    variant="outline"
                    leftIcon={<HeroIconPlusIcon width="20px" strokeWidth={2} />}
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

                  <Box
                    mt={3}
                    flex={1}
                    minH={0}
                    display="flex"
                    flexDirection="column"
                    overflow="hidden"
                  >
                    {/* ADD HOST FORM */}
                    <Collapse
                      in={isAddingHost}
                      animateOpacity
                      style={{
                        flexShrink: 0,
                      }}
                    >
                      <Box pb={3}>
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
                    <Box flex={1} minH={0} overflow="hidden">
                      <VStack
                        h="full"
                        minH={0}
                        align="stretch"
                        spacing={3}
                        overflowY="auto"
                        pr={2}
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
                        <HostsList
                          inboundTags={inboundTags}
                          inboundFilter={inboundFilter}
                          search={search}
                          bots={bots}
                          nodes={nodes}
                          inboundMap={inboundMap}
                        />
                      </VStack>
                    </Box>
                  </Box>
                </>
              )}

              {/* APPLY */}
              <HStack
                justifyContent="flex-end"
                py={3}
                px={0}
                flexShrink={0}
                bg="white"
                _dark={{
                  bg: "gray.700",
                }}
              >
                <Button
                  variant="solid"
                  mt="2"
                  type="submit"
                  colorScheme="primary"
                  size="sm"
                  px={5}
                  isLoading={isPostLoading}
                  disabled={isPostLoading}
                >
                  {t("hostsDialog.apply")}
                </Button>
              </HStack>
            </form>
          </FormProvider>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

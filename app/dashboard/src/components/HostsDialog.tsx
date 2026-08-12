import {
  Button,
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
import { MagnifyingGlassIcon } from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import { useHosts } from "contexts/HostsContext";
import { FC, useCallback, useEffect, useMemo, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { Bot } from "types/Bot";
import { z } from "zod";
import { useDashboard } from "../contexts/DashboardContext";
import { NodeType } from "../contexts/NodesContext";
import { Icon } from "./Icon";
import { hostsFormSchema } from "./hostsDialog/schema";
import { ModalIcon } from "./hostsDialog/constants";
import { HostsList } from "./hostsDialog/HostsList";

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

  return (
    <Modal isOpen={isEditingHosts} onClose={onClose}>
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3" w="fit-content" maxW="3xl">
        <ModalHeader pt={6}>
          <Icon color="primary">
            <ModalIcon color="white" />
          </Icon>
        </ModalHeader>
        <ModalCloseButton mt={3} />
        <ModalBody w="520px" pb={3} pt={3}>
          <FormProvider {...form}>
            <form onSubmit={form.handleSubmit(handleFormSubmit)}>
              <Text mb={3} opacity={0.8} fontSize="sm">
                {t("hostsDialog.title")}
              </Text>

              {isLoading ? (
                t("hostsDialog.loading")
              ) : (
                <VStack align="stretch" spacing={3} mb={2}>
                  <InputGroup>
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
                    value={inboundFilter}
                    onChange={(e) => setInboundFilter(e.target.value)}
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

                  <HostsList
                    inboundTags={inboundTags}
                    inboundFilter={inboundFilter}
                    search={search}
                    bots={bots}
                    nodes={nodes}
                    inboundMap={inboundMap}
                  />
                </VStack>
              )}

              <HStack justifyContent="flex-end" py={2}>
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

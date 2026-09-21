import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  CheckboxGroup,
  Divider,
  Flex,
  FormControl,
  FormLabel,
  HStack,
  IconButton,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  NumberDecrementStepper,
  NumberIncrementStepper,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  Select,
  SimpleGrid,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Textarea,
  Tooltip,
  VStack,
  chakra,
  useToast,
} from "@chakra-ui/react";
import { MapPinIcon, TrashIcon } from "@heroicons/react/24/outline";
import { useDashboard } from "contexts/DashboardContext";
import dayjs from "dayjs";
import { FC, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { Icon } from "./Icon";

const DeletePinIcon = chakra(TrashIcon, {
  baseStyle: {
    w: 4,
    h: 4,
  },
});

type AssignmentSource = "pin" | "auto" | "unknown";

type PinResponse = {
  host_id: number;
  node_ids: number[];
  created_at: string;
  expires_at: string;
  created_by: string;
  note?: string | null;
};

type HostAssignment = {
  host_id: number;
  remark: string;
  source: AssignmentSource;
  restorable: boolean;
  node_ids: number[];
  addresses: string[];
};

type DayAssignments = {
  day_index: number;
  date: string;
  hosts: HostAssignment[];
};

type PinnableNode = {
  node_id: number;
  name: string;
};

type PinnableHost = {
  host_id: number;
  remark: string;
  nodes: PinnableNode[];
};

const HISTORY_DAYS = 14;
// Тот же горизонт, что MAX_PIN_TTL_DAYS (app/services/address_history.py) и
// ARCHIVE_RETENTION_DAYS (app/xray/address_policy.py) — единственный источник
// там, но TS не может импортировать Python-константу (M4, NPVPN-2072), так
// что число здесь продублировано вручную и должно меняться синхронно с ними.
const MAX_TTL_DAYS = 90;
const DEFAULT_TTL_DAYS = 7;

const sourceColorScheme = (source: AssignmentSource): string => {
  if (source === "pin") return "purple";
  if (source === "auto") return "blue";
  return "gray";
};

export const AddressPinModal: FC = () => {
  const { addressPinsUser: user } = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();

  const [pins, setPins] = useState<PinResponse[]>([]);
  const [pinsLoading, setPinsLoading] = useState(false);
  const [pinsError, setPinsError] = useState<string | null>(null);
  const [deletingHostId, setDeletingHostId] = useState<number | null>(null);

  const [history, setHistory] = useState<DayAssignments[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [pinnableHosts, setPinnableHosts] = useState<PinnableHost[]>([]);
  const [pinnableHostsLoading, setPinnableHostsLoading] = useState(false);
  const [pinnableHostsError, setPinnableHostsError] = useState<string | null>(
    null
  );

  const [selectedHostId, setSelectedHostId] = useState<string>("");
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [ttlDays, setTtlDays] = useState<string>(String(DEFAULT_TTL_DAYS));
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Признаки для отображения хостов без имени (нет пересечения с историей).
  const remarkByHostId = new Map<number, string>();
  history.forEach((day) => {
    day.hosts.forEach((host) => {
      if (!remarkByHostId.has(host.host_id)) {
        remarkByHostId.set(host.host_id, host.remark);
      }
    });
  });
  pinnableHosts.forEach((host) => {
    remarkByHostId.set(host.host_id, host.remark);
  });

  const loadPins = useCallback(() => {
    if (!user) return;
    setPinsLoading(true);
    setPinsError(null);
    fetch(`/user/${user.username}/pins`, { method: "GET" })
      .then((res: PinResponse[]) => setPins(res || []))
      .catch(() => {
        setPinsError(t("addressPins.pinsLoadError"));
      })
      .finally(() => setPinsLoading(false));
  }, [user, t]);

  const loadHistory = useCallback(() => {
    if (!user) return;
    setHistoryLoading(true);
    setHistoryError(null);
    fetch(`/user/${user.username}/address_history`, {
      method: "GET",
      query: { days: HISTORY_DAYS },
    })
      .then((res: DayAssignments[]) => setHistory(res || []))
      .catch(() => {
        setHistoryError(t("addressPins.historyLoadError"));
      })
      .finally(() => setHistoryLoading(false));
  }, [user, t]);

  const loadPinnableHosts = useCallback(() => {
    if (!user) return;
    setPinnableHostsLoading(true);
    setPinnableHostsError(null);
    fetch(`/user/${user.username}/pinnable_hosts`, { method: "GET" })
      .then((res: PinnableHost[]) => setPinnableHosts(res || []))
      .catch(() => {
        setPinnableHostsError(t("addressPins.pinnableHostsLoadError"));
      })
      .finally(() => setPinnableHostsLoading(false));
  }, [user, t]);

  useEffect(() => {
    if (user) {
      loadPins();
      loadHistory();
      loadPinnableHosts();
    } else {
      setPins([]);
      setHistory([]);
      setPinnableHosts([]);
      setSelectedHostId("");
      setSelectedNodeIds([]);
      setTtlDays(String(DEFAULT_TTL_DAYS));
      setNote("");
      setCreateError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const onClose = () => {
    useDashboard.setState({ addressPinsUser: null });
  };

  const deletePin = (hostId: number) => {
    if (!user) return;
    setDeletingHostId(hostId);
    fetch(`/user/${user.username}/pins/${hostId}`, { method: "DELETE" })
      .then(() => {
        setPins((prev) => prev.filter((pin) => pin.host_id !== hostId));
        toast({
          title: t("addressPins.pinRemoved"),
          status: "success",
          isClosable: true,
          position: "top",
          duration: 3000,
        });
      })
      .catch(() => {
        toast({
          title: t("addressPins.pinRemoveError"),
          status: "error",
          isClosable: true,
          position: "top",
          duration: 3000,
        });
      })
      .finally(() => setDeletingHostId(null));
  };

  const hostLabel = (hostId: number): string => {
    const remark = remarkByHostId.get(hostId);
    return remark ? remark : t("addressPins.unknownHost", { hostId });
  };

  const selectedHost = useMemo(
    () =>
      pinnableHosts.find((host) => String(host.host_id) === selectedHostId) ||
      null,
    [pinnableHosts, selectedHostId]
  );

  const onSelectHost = (hostId: string) => {
    setSelectedHostId(hostId);
    setSelectedNodeIds([]);
    setCreateError(null);
  };

  const ttlDaysNumber = Number(ttlDays);
  const ttlDaysValid =
    Number.isFinite(ttlDaysNumber) &&
    ttlDaysNumber > 0 &&
    ttlDaysNumber <= MAX_TTL_DAYS;
  const canCreatePin =
    !!selectedHostId && selectedNodeIds.length > 0 && ttlDaysValid;

  const createPin = () => {
    if (!user || !canCreatePin) return;
    setCreating(true);
    setCreateError(null);
    fetch(`/user/${user.username}/pins`, {
      method: "POST",
      body: {
        host_id: Number(selectedHostId),
        node_ids: selectedNodeIds.map(Number),
        ttl_days: ttlDaysNumber,
        note: note.trim() ? note.trim() : undefined,
      },
    })
      .then((pin: PinResponse) => {
        setPins((prev) => [
          ...prev.filter((p) => p.host_id !== pin.host_id),
          pin,
        ]);
        setSelectedHostId("");
        setSelectedNodeIds([]);
        setTtlDays(String(DEFAULT_TTL_DAYS));
        setNote("");
        toast({
          title: t("addressPins.pinCreated"),
          status: "success",
          isClosable: true,
          position: "top",
          duration: 3000,
        });
      })
      .catch((err: any) => {
        setCreateError(
          err?.response?._data?.detail || t("addressPins.pinCreateError")
        );
      })
      .finally(() => setCreating(false));
  };

  return (
    /* NPVPN-2072: scrollBehavior="inside" обязателен — журнал выдачи длиной
       в ретеншн (до 90 дней) с isCentered вырастал выше вьюпорта, и модалка
       обрезалась сверху и снизу без единой полосы прокрутки. */
    <Modal
      isCentered
      isOpen={!!user}
      onClose={onClose}
      size="2xl"
      scrollBehavior="inside"
    >
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3">
        <ModalHeader pt={6}>
          <HStack gap={3}>
            <Icon color="purple">
              <MapPinIcon width="20px" height="20px" />
            </Icon>
            <Box>
              <Text fontWeight="semibold" fontSize="lg">
                {t("addressPins.title")}
              </Text>
              {user && (
                <Text fontSize="sm" color="gray.500">
                  {user.username}
                </Text>
              )}
            </Box>
          </HStack>
        </ModalHeader>
        <ModalCloseButton mt={3} />
        <ModalBody pb={6}>
          <Tabs colorScheme="primary" size="sm">
            <TabList>
              <Tab>{t("addressPins.tabPins")}</Tab>
              <Tab>{t("addressPins.tabHistory")}</Tab>
            </TabList>
            <TabPanels>
              {/* Действующие закрепления + создание нового */}
              <TabPanel px={0}>
                <Box borderWidth="1px" borderRadius="lg" p={3} mb={4}>
                  <Text fontWeight="semibold" fontSize="sm" mb={2}>
                    {t("addressPins.newPin")}
                  </Text>
                  {pinnableHostsError && (
                    <Alert status="error" mb={3} borderRadius="md" fontSize="sm">
                      <AlertIcon />
                      {pinnableHostsError}
                    </Alert>
                  )}
                  {pinnableHostsLoading ? (
                    <Flex justifyContent="center" py="4">
                      <Spinner size="sm" />
                    </Flex>
                  ) : pinnableHosts.length ? (
                    <VStack align="stretch" spacing={3}>
                      <FormControl>
                        <FormLabel fontSize="sm">
                          {t("addressPins.host")}
                        </FormLabel>
                        <Select
                          size="sm"
                          placeholder={t("addressPins.hostPlaceholder")}
                          value={selectedHostId}
                          onChange={(e) => onSelectHost(e.target.value)}
                        >
                          {pinnableHosts.map((host) => (
                            <option key={host.host_id} value={host.host_id}>
                              {host.remark}
                            </option>
                          ))}
                        </Select>
                      </FormControl>

                      {selectedHost && (
                        <FormControl>
                          <FormLabel fontSize="sm">
                            {t("addressPins.nodes")}
                          </FormLabel>
                          <CheckboxGroup
                            value={selectedNodeIds}
                            onChange={(values) =>
                              setSelectedNodeIds(values as string[])
                            }
                          >
                            <SimpleGrid columns={{ base: 1, sm: 2 }} spacing={1}>
                              {selectedHost.nodes.map((node) => (
                                <Checkbox
                                  key={node.node_id}
                                  value={String(node.node_id)}
                                  fontSize="sm"
                                >
                                  {node.name}
                                </Checkbox>
                              ))}
                            </SimpleGrid>
                          </CheckboxGroup>
                          {!selectedHost.nodes.length && (
                            <Text fontSize="xs" color="gray.500" mt={1}>
                              {t("addressPins.hostHasNoNodes")}
                            </Text>
                          )}
                        </FormControl>
                      )}

                      <HStack align="flex-start" spacing={3}>
                        <FormControl maxW="140px">
                          <FormLabel fontSize="sm">
                            {t("addressPins.ttlDays")}
                          </FormLabel>
                          <NumberInput
                            size="sm"
                            min={1}
                            max={MAX_TTL_DAYS}
                            value={ttlDays}
                            onChange={(valueString) => setTtlDays(valueString)}
                          >
                            <NumberInputField />
                            <NumberInputStepper>
                              <NumberIncrementStepper />
                              <NumberDecrementStepper />
                            </NumberInputStepper>
                          </NumberInput>
                          {!ttlDaysValid && (
                            <Text fontSize="xs" color="red.400" mt={1}>
                              {t("addressPins.ttlDaysHint", {
                                max: MAX_TTL_DAYS,
                              })}
                            </Text>
                          )}
                        </FormControl>
                        <FormControl flex={1}>
                          <FormLabel fontSize="sm">
                            {t("addressPins.note")}
                          </FormLabel>
                          <Textarea
                            size="sm"
                            rows={1}
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder={t("addressPins.notePlaceholder")}
                          />
                        </FormControl>
                      </HStack>

                      {createError && (
                        <Alert status="error" borderRadius="md" fontSize="sm">
                          <AlertIcon />
                          {createError}
                        </Alert>
                      )}

                      <Flex justify="flex-end">
                        <Button
                          size="sm"
                          colorScheme="primary"
                          onClick={createPin}
                          isDisabled={!canCreatePin}
                          isLoading={creating}
                        >
                          {t("addressPins.createPin")}
                        </Button>
                      </Flex>
                    </VStack>
                  ) : (
                    <Text color="gray.500" fontSize="sm">
                      {t("addressPins.noPinnableHosts")}
                    </Text>
                  )}
                </Box>

                {pinsError && (
                  <Alert status="error" mb={3} borderRadius="md">
                    <AlertIcon />
                    {pinsError}
                  </Alert>
                )}
                {pinsLoading ? (
                  <Flex justifyContent="center" py="6">
                    <Spinner size="sm" />
                  </Flex>
                ) : pins.length ? (
                  <VStack align="stretch" spacing={2}>
                    {pins.map((pin) => (
                      <Box
                        key={pin.host_id}
                        borderWidth="1px"
                        borderRadius="lg"
                        p={3}
                      >
                        <Flex justify="space-between" align="flex-start" gap={2}>
                          <Box>
                            <Text fontWeight="semibold" fontSize="sm">
                              {hostLabel(pin.host_id)}
                            </Text>
                            <Text fontSize="xs" color="gray.500">
                              {t("addressPins.nodeIds")}: {pin.node_ids.join(", ")}
                            </Text>
                            <Text fontSize="xs" color="gray.500">
                              {t("addressPins.expiresAt")}:{" "}
                              {/* M2, NPVPN-2072: PinResponse.expires_at приходит naive UTC
                                  (app/services/address_history.py), а голый dayjs(...)
                                  трактует такую строку как ЛОКАЛЬНОЕ время — известные
                                  грабли проекта с таймзонами. dayjs.utc(...).local()
                                  явно парсит как UTC и уже потом конвертирует в часовой
                                  пояс браузера. */}
                              {dayjs.utc(pin.expires_at).local().format("YYYY-MM-DD HH:mm")}
                            </Text>
                            <Text fontSize="xs" color="gray.500">
                              {t("addressPins.createdBy")}: {pin.created_by}
                            </Text>
                            {pin.note && (
                              <Text fontSize="xs" color="gray.500">
                                {t("addressPins.note")}: {pin.note}
                              </Text>
                            )}
                          </Box>
                          <Tooltip label={t("addressPins.removePin")} placement="top">
                            <IconButton
                              aria-label={t("addressPins.removePin")}
                              size="xs"
                              variant="ghost"
                              colorScheme="red"
                              icon={<DeletePinIcon />}
                              isLoading={deletingHostId === pin.host_id}
                              onClick={() => deletePin(pin.host_id)}
                            />
                          </Tooltip>
                        </Flex>
                      </Box>
                    ))}
                  </VStack>
                ) : (
                  <Text color="gray.500" fontSize="sm" py={4} textAlign="center">
                    {t("addressPins.pinsEmpty")}
                  </Text>
                )}
              </TabPanel>

              {/* История выдачи */}
              <TabPanel px={0}>
                {historyError && (
                  <Alert status="error" mb={3} borderRadius="md">
                    <AlertIcon />
                    {historyError}
                  </Alert>
                )}
                {historyLoading ? (
                  <Flex justifyContent="center" py="6">
                    <Spinner size="sm" />
                  </Flex>
                ) : history.length ? (
                  <VStack align="stretch" spacing={3} divider={<Divider />}>
                    {history.map((day) => (
                      <Box key={day.day_index}>
                        <Text fontWeight="semibold" fontSize="sm" mb={2}>
                          {day.date}
                        </Text>
                        <VStack align="stretch" spacing={1.5}>
                          {day.hosts.map((host) => (
                            <Flex
                              key={host.host_id}
                              justify="space-between"
                              align="center"
                              fontSize="sm"
                              gap={2}
                            >
                              <Text noOfLines={1} flex={1}>
                                {host.remark}
                              </Text>
                              {host.restorable ? (
                                <>
                                  <Badge colorScheme={sourceColorScheme(host.source)}>
                                    {t(`addressPins.source.${host.source}`)}
                                  </Badge>
                                  <Text
                                    fontSize="xs"
                                    color="gray.500"
                                    flexShrink={0}
                                    maxW="45%"
                                    noOfLines={1}
                                  >
                                    {/* M1, NPVPN-2072: раньше здесь печатался ТОЛЬКО
                                        node_ids. У легаси-хоста со статическим адресом
                                        node_ids всегда пуст (соответствия "адрес <-> нода"
                                        там нет по построению), и строка читалась как
                                        "адресов не было", хотя эндпоинт отдаёт их в
                                        addresses. Показываем адреса — они информативнее
                                        для саппорта и заполнены в обеих ветках. */}
                                    {host.addresses.length
                                      ? host.addresses.join(", ")
                                      : host.node_ids.length
                                        ? host.node_ids.join(", ")
                                        : "-"}
                                  </Text>
                                </>
                              ) : (
                                <Tooltip label={t("addressPins.notRestorableHint")}>
                                  <Badge colorScheme="red">
                                    {t("addressPins.notRestorable")}
                                  </Badge>
                                </Tooltip>
                              )}
                            </Flex>
                          ))}
                        </VStack>
                      </Box>
                    ))}
                  </VStack>
                ) : (
                  <Text color="gray.500" fontSize="sm" py={4} textAlign="center">
                    {t("addressPins.historyEmpty")}
                  </Text>
                )}
              </TabPanel>
            </TabPanels>
          </Tabs>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

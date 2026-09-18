import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Divider,
  Flex,
  HStack,
  IconButton,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Tooltip,
  VStack,
  chakra,
  useToast,
} from "@chakra-ui/react";
import { MapPinIcon, TrashIcon } from "@heroicons/react/24/outline";
import { useDashboard } from "contexts/DashboardContext";
import dayjs from "dayjs";
import { FC, useCallback, useEffect, useState } from "react";
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

const HISTORY_DAYS = 14;

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

  // Признаки для отображения хостов без имени (нет пересечения с историей).
  const remarkByHostId = new Map<number, string>();
  history.forEach((day) => {
    day.hosts.forEach((host) => {
      if (!remarkByHostId.has(host.host_id)) {
        remarkByHostId.set(host.host_id, host.remark);
      }
    });
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

  useEffect(() => {
    if (user) {
      loadPins();
      loadHistory();
    } else {
      setPins([]);
      setHistory([]);
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

  return (
    <Modal isCentered isOpen={!!user} onClose={onClose} size="2xl">
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
              {/* Действующие закрепления */}
              <TabPanel px={0}>
                <Alert status="info" borderRadius="md" fontSize="sm" mb={3}>
                  <AlertIcon />
                  {t("addressPins.createUnavailable")}
                </Alert>
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
                              {dayjs(pin.expires_at).format("YYYY-MM-DD HH:mm")}
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
                                    {host.node_ids.length
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

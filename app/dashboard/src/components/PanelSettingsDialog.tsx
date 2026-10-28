import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Box,
  Button,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  IconButton,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Tab,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Tooltip,
  VStack,
  useBreakpointValue,
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import { useDashboard } from "contexts/DashboardContext";
import { FC, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import {
  PanelSettings,
  SubscriptionMessageServerField,
} from "types/PanelSettings";
import { DeleteIcon } from "./DeleteUserModal";
import { FIELD_SCENARIO, HappPreviewScenario } from "./happPreview/happPreview";
import {
  HappScenarioSelect,
  HappSubscriptionPreview,
} from "./happPreview/HappSubscriptionPreview";
import { AutoResizeTextarea } from "./AutoResizeTextarea";
import { EyeIcon } from "@heroicons/react/24/outline";
import { XrayTemplatesPanel } from "./XrayTemplatesPanel";

const GB_IN_BYTES = 1073741824;

const emptySettings: PanelSettings = {
  sub_custom_headers: "",
  bs_monthly_limit: 0,
  sub_routing_happ: "",
  sub_routing_v2raytun: "",
  subscription_legacy_secret_keys: [],
  primary_jwt_secret: "",
  sub_client_note: "",
  sub_revoked_announce_text: "",
  sub_expired_announce_text: "",
  sub_device_limit_announce_text: "",
  sub_unsupported_client_announce_text: "",
  sub_bs_limit_announce_text: "",
  sub_revoked_server_text: [],
  sub_expired_server_text: [],
  sub_device_limit_server_text: [],
  sub_unsupported_client_server_text: [],
  sub_bs_limit_server_text: [],
};

const SERVER_TEXT_FIELDS: SubscriptionMessageServerField[] = [
  "sub_revoked_server_text",
  "sub_expired_server_text",
  "sub_device_limit_server_text",
  "sub_unsupported_client_server_text",
  "sub_bs_limit_server_text",
];

type ListFieldTexts = Record<SubscriptionMessageServerField, string>;

const toText = (values: string[] = []) => values.join("\n");
const toList = (value: string) =>
  value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
const toListFieldTexts = (settings: PanelSettings): ListFieldTexts => ({
  sub_revoked_server_text: toText(settings.sub_revoked_server_text),
  sub_expired_server_text: toText(settings.sub_expired_server_text),
  sub_device_limit_server_text: toText(settings.sub_device_limit_server_text),
  sub_unsupported_client_server_text: toText(
    settings.sub_unsupported_client_server_text
  ),
  sub_bs_limit_server_text: toText(settings.sub_bs_limit_server_text),
});

const copyList = (value: string[] | undefined) =>
  Array.isArray(value) ? [...value] : [];

const mergeSettings = (
  data: Partial<PanelSettings>,
  keepPrimary?: string
): PanelSettings => ({
  ...emptySettings,
  ...data,
  subscription_legacy_secret_keys: Array.isArray(
    data.subscription_legacy_secret_keys
  )
    ? data.subscription_legacy_secret_keys
    : [],
  sub_revoked_server_text: copyList(data.sub_revoked_server_text),
  sub_expired_server_text: copyList(data.sub_expired_server_text),
  sub_device_limit_server_text: copyList(data.sub_device_limit_server_text),
  sub_unsupported_client_server_text: copyList(
    data.sub_unsupported_client_server_text
  ),
  sub_bs_limit_server_text: copyList(data.sub_bs_limit_server_text),
  primary_jwt_secret:
    keepPrimary !== undefined ? keepPrimary : data.primary_jwt_secret || "",
});

// Индекс вкладки v2ray-json: у XrayTemplatesPanel своё сохранение,
// общий футер модалки к нему отношения не имеет.
const V2RAY_TAB_INDEX = 2;

const SUBSCRIPTION_FIELDS = [
  "sub_routing_happ",
  "sub_routing_v2raytun",
  "sub_custom_headers",
  "bs_monthly_limit",
] as const;

const MESSAGE_TEXT_FIELDS = [
  "sub_client_note",
  "sub_revoked_announce_text",
  "sub_expired_announce_text",
  "sub_device_limit_announce_text",
  "sub_unsupported_client_announce_text",
  "sub_bs_limit_announce_text",
] as const;

const sameList = (left: string[], right: string[]) =>
  left.length === right.length && left.every((item, i) => item === right[i]);

// Ключи в том виде, в каком их отправит save(): пустые строки не считаются изменением.
const normalizeKeys = (keys: string[]) =>
  keys.map((key) => key.trim()).filter(Boolean);

const isSubscriptionDirty = (a: PanelSettings, b: PanelSettings) =>
  SUBSCRIPTION_FIELDS.some((field) => a[field] !== b[field]);

const isMessagesDirty = (a: PanelSettings, b: PanelSettings) =>
  MESSAGE_TEXT_FIELDS.some((field) => a[field] !== b[field]) ||
  SERVER_TEXT_FIELDS.some((field) => !sameList(a[field], b[field]));

const isJwtDirty = (a: PanelSettings, b: PanelSettings) => {
  const left = normalizeKeys(a.subscription_legacy_secret_keys);
  const right = normalizeKeys(b.subscription_legacy_secret_keys);
  return (
    left.length !== right.length || left.some((key, i) => key !== right[i])
  );
};

// Значение ячейки диалога сброса: short — что видно в таблице,
// full — полный текст для подсказки, если short обрезан.
type ResetDiffValue = { short: string; full?: string };

type ResetDiffRow = {
  tab: "subscription" | "messages" | "jwt";
  label: string;
  from: ResetDiffValue[];
  to: ResetDiffValue[];
};

// Порядок групп в диалоге сброса; группа видна, только если в ней есть изменения.
const RESET_DIFF_TABS = [
  { tab: "subscription", labelKey: "panelSettings.tabSubscription" },
  { tab: "messages", labelKey: "panelSettings.tabMessages" },
  { tab: "jwt", labelKey: "panelSettings.tabJwtKey" },
] as const;

const PREVIEW_LENGTH = 60;
const KEY_PREVIEW_LENGTH = 8;

const preview = (
  value: string,
  empty: string,
  maxLength = PREVIEW_LENGTH
): ResetDiffValue => {
  const oneLine = value.replace(/\s+/g, " ").trim();
  if (!oneLine) return { short: empty };
  return oneLine.length > maxLength
    ? { short: `${oneLine.slice(0, maxLength)}…`, full: value }
    : { short: oneLine };
};

const previewKeys = (keys: string[], empty: string): ResetDiffValue[] => {
  const normalized = normalizeKeys(keys);
  if (normalized.length === 0) return [{ short: empty }];
  return normalized.map((key) => preview(key, empty, KEY_PREVIEW_LENGTH));
};

const thinScrollbarSx = {
  "&::-webkit-scrollbar": {
    width: "6px",
  },
  "&::-webkit-scrollbar-track": {
    background: "transparent",
  },
  "&::-webkit-scrollbar-thumb": {
    background: "var(--chakra-colors-gray-300)",
    borderRadius: "full",
  },
  "&::-webkit-scrollbar-thumb:hover": {
    background: "var(--chakra-colors-gray-400)",
  },
  scrollbarWidth: "thin",
  scrollbarColor: "var(--chakra-colors-gray-300) transparent",
} as const;

export const PanelSettingsDialog: FC = () => {
  const { isEditingPanelSettings, onEditingPanelSettings } = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<PanelSettings>(emptySettings);
  // Последнее состояние с сервера — от него считаются несохранённые изменения.
  const [initial, setInitial] = useState<PanelSettings>(emptySettings);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tabIndex, setTabIndex] = useState(0);
  const [pendingDefaults, setPendingDefaults] = useState<PanelSettings | null>(
    null
  );
  const [listFieldTexts, setListFieldTexts] = useState<ListFieldTexts>(
    toListFieldTexts(emptySettings)
  );
  const [previewScenario, setPreviewScenario] =
    useState<HappPreviewScenario>("normal");
  const discardConfirm = useDisclosure();
  // узкий экран: предпросмотр открывается поверх по кнопке, а не стоит под полями
  const previewOverlay = useDisclosure();
  const isWide = useBreakpointValue({ base: false, xl: true });
  const cancelResetRef = useRef<HTMLButtonElement>(null);
  const cancelDiscardRef = useRef<HTMLButtonElement>(null);

  const subscriptionDirty = isSubscriptionDirty(settings, initial);
  const messagesDirty = isMessagesDirty(settings, initial);
  const jwtDirty = isJwtDirty(settings, initial);
  const isDirty = subscriptionDirty || messagesDirty || jwtDirty;

  const showValidationErrorToast = (err: any) => {
    const detail = err?.response?._data?.detail;
    if (detail && typeof detail === "object") {
      Object.keys(detail).forEach((key) => {
        toast({
          title: `${detail[key]} (${key})`,
          status: "error",
          isClosable: true,
          position: "top",
        });
      });
      return;
    }
    toast({
      title: t("panelSettings.saveFailed"),
      description: typeof detail === "string" ? detail : undefined,
      status: "error",
      isClosable: true,
      position: "top",
    });
  };

  useEffect(() => {
    if (!isEditingPanelSettings) return;
    setSettings(emptySettings);
    setInitial(emptySettings);
    setTabIndex(0);
    setLoading(true);
    fetch("/settings/panel")
      .then((data: PanelSettings) => {
        const loaded = mergeSettings(data);
        setSettings(loaded);
        setInitial(loaded);
        setListFieldTexts(toListFieldTexts(loaded));
        setPreviewScenario("normal");
      })
      .catch(() =>
        toast({
          title: t("panelSettings.loadFailed"),
          status: "error",
          isClosable: true,
          position: "top",
        })
      )
      .finally(() => setLoading(false));
  }, [isEditingPanelSettings]);

  const updateSettings = (patch: Partial<PanelSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  };

  const updateLegacyKey = (index: number, value: string) => {
    const next = [...settings.subscription_legacy_secret_keys];
    next[index] = value;
    updateSettings({ subscription_legacy_secret_keys: next });
  };

  const removeLegacyKey = (index: number) => {
    updateSettings({
      subscription_legacy_secret_keys:
        settings.subscription_legacy_secret_keys.filter((_, i) => i !== index),
    });
  };

  const addLegacyKey = () => {
    updateSettings({
      subscription_legacy_secret_keys: [
        ...settings.subscription_legacy_secret_keys,
        "",
      ],
    });
  };

  // Сброс только подставляет заводские значения в форму, но меняет и вкладки,
  // которых сейчас не видно, — поэтому сначала показываем, что именно поменяется.
  const requestResetToDefaults = () => {
    setLoading(true);
    const primary = settings.primary_jwt_secret || "";
    fetch("/settings/panel/defaults")
      .then((data: PanelSettings) => {
        const defaults = mergeSettings(data, primary);
        if (
          !isSubscriptionDirty(settings, defaults) &&
          !isMessagesDirty(settings, defaults) &&
          !isJwtDirty(settings, defaults)
        ) {
          toast({
            title: t("panelSettings.resetNothing"),
            status: "info",
            isClosable: true,
            position: "top",
          });
          return;
        }
        setPendingDefaults(defaults);
      })
      .catch(() =>
        toast({
          title: t("panelSettings.loadFailed"),
          status: "error",
          isClosable: true,
          position: "top",
        })
      )
      .finally(() => setLoading(false));
  };

  const confirmResetToDefaults = () => {
    if (pendingDefaults) {
      setSettings(pendingDefaults);
      setListFieldTexts(toListFieldTexts(pendingDefaults));
    }
    setPendingDefaults(null);
  };

  const updateListField = (
    field: SubscriptionMessageServerField,
    value: string
  ) => {
    setListFieldTexts((current) => ({ ...current, [field]: value }));
    updateSettings({ [field]: toList(value) });
  };

  // видны только тексты выбранного сценария; скрытые поля остаются в форме,
  // несохранённые правки в них не теряются
  const fieldDisplay = (field: string) =>
    FIELD_SCENARIO[field] === previewScenario ? undefined : "none";

  const buildResetDiff = (target: PanelSettings): ResetDiffRow[] => {
    const empty = t("panelSettings.emptyValue");
    const rows: ResetDiffRow[] = [];
    const addText = (
      field: "sub_routing_happ" | "sub_routing_v2raytun" | "sub_custom_headers",
      labelKey: string
    ) => {
      if (settings[field] === target[field]) return;
      rows.push({
        tab: "subscription",
        label: t(labelKey),
        from: [preview(settings[field], empty)],
        to: [preview(target[field], empty)],
      });
    };
    addText("sub_routing_happ", "panelSettings.subRoutingHapp");
    addText("sub_routing_v2raytun", "panelSettings.subRoutingV2raytun");
    addText("sub_custom_headers", "panelSettings.subCustomHeaders");
    const addMessageText = (
      field: (typeof MESSAGE_TEXT_FIELDS)[number],
      labelKey: string
    ) => {
      if (settings[field] === target[field]) return;
      rows.push({
        tab: "messages",
        label: t(labelKey),
        from: [preview(settings[field], empty)],
        to: [preview(target[field], empty)],
      });
    };
    addMessageText("sub_client_note", "botSettings.subClientNote");
    addMessageText(
      "sub_revoked_announce_text",
      "botSettings.subRevokedAnnounceText"
    );
    addMessageText(
      "sub_expired_announce_text",
      "botSettings.subExpiredAnnounceText"
    );
    addMessageText(
      "sub_device_limit_announce_text",
      "botSettings.subDeviceLimitAnnounceText"
    );
    addMessageText(
      "sub_unsupported_client_announce_text",
      "botSettings.subUnsupportedClientAnnounceText"
    );
    addMessageText(
      "sub_bs_limit_announce_text",
      "botSettings.subBsLimitAnnounceText"
    );
    const addMessageList = (
      field: SubscriptionMessageServerField,
      labelKey: string
    ) => {
      if (sameList(settings[field], target[field])) return;
      rows.push({
        tab: "messages",
        label: t(labelKey),
        from: [preview(toText(settings[field]), empty)],
        to: [preview(toText(target[field]), empty)],
      });
    };
    addMessageList(
      "sub_revoked_server_text",
      "botSettings.subRevokedServerText"
    );
    addMessageList(
      "sub_expired_server_text",
      "botSettings.subExpiredServerText"
    );
    addMessageList(
      "sub_device_limit_server_text",
      "botSettings.subDeviceLimitServerText"
    );
    addMessageList(
      "sub_unsupported_client_server_text",
      "botSettings.subUnsupportedClientServerText"
    );
    addMessageList(
      "sub_bs_limit_server_text",
      "botSettings.subBsLimitServerText"
    );
    if (settings.bs_monthly_limit !== target.bs_monthly_limit) {
      rows.push({
        tab: "subscription",
        label: t("panelSettings.bsMonthlyLimitGb"),
        from: [{ short: String(settings.bs_monthly_limit / GB_IN_BYTES) }],
        to: [{ short: String(target.bs_monthly_limit / GB_IN_BYTES) }],
      });
    }
    if (isJwtDirty(settings, target)) {
      rows.push({
        tab: "jwt",
        label: t("panelSettings.legacyJwtKeys"),
        from: previewKeys(settings.subscription_legacy_secret_keys, empty),
        to: previewKeys(target.subscription_legacy_secret_keys, empty),
      });
    }
    return rows;
  };

  const resetDiff = pendingDefaults ? buildResetDiff(pendingDefaults) : [];

  const renderDiffValues = (values: ResetDiffValue[]) =>
    values.map((value, i) => (
      <Tooltip
        key={i}
        label={value.full}
        isDisabled={!value.full}
        fontFamily="mono"
        fontSize="xs"
        hasArrow
      >
        <Text cursor={value.full ? "help" : undefined}>{value.short}</Text>
      </Tooltip>
    ));

  const requestClose = () => {
    if (isDirty) {
      discardConfirm.onOpen();
      return;
    }
    onEditingPanelSettings(false);
  };

  const discardAndClose = () => {
    discardConfirm.onClose();
    onEditingPanelSettings(false);
  };

  const save = () => {
    setSaving(true);
    const { primary_jwt_secret: _primary, ...payload } = settings;
    const body = {
      ...payload,
      subscription_legacy_secret_keys: normalizeKeys(
        settings.subscription_legacy_secret_keys
      ),
      sub_revoked_server_text: toList(listFieldTexts.sub_revoked_server_text),
      sub_expired_server_text: toList(listFieldTexts.sub_expired_server_text),
      sub_device_limit_server_text: toList(
        listFieldTexts.sub_device_limit_server_text
      ),
      sub_unsupported_client_server_text: toList(
        listFieldTexts.sub_unsupported_client_server_text
      ),
      sub_bs_limit_server_text: toList(listFieldTexts.sub_bs_limit_server_text),
    };
    fetch("/settings/panel", { method: "PUT", body })
      .then((data: PanelSettings) => {
        const saved = mergeSettings(data, data.primary_jwt_secret || _primary);
        setSettings(saved);
        setInitial(saved);
        setListFieldTexts(toListFieldTexts(saved));
        toast({
          title: t("panelSettings.saved"),
          status: "success",
          isClosable: true,
          position: "top",
        });
        // NPVPN-2235: окно не закрываем — админ остаётся на той же вкладке и том же
        // превью (например, «Подписка отозвана»). Раньше после сохранения окно
        // закрывалось и при следующем открытии сбрасывалось на первую вкладку
      })
      .catch((err) => showValidationErrorToast(err))
      .finally(() => setSaving(false));
  };

  const dirtyDot = (
    <Box
      as="span"
      display="inline-block"
      w={2}
      h={2}
      ml={2}
      borderRadius="full"
      bg="orange.400"
      aria-label={t("panelSettings.unsavedChanges")}
    />
  );

  return (
    <>
      <Modal
        isOpen={isEditingPanelSettings}
        onClose={requestClose}
        // одна ширина на всех вкладках — окно не прыгает при переключении;
        // широкая из-за предпросмотра HAPP на «Сообщениях». На мобилке — на весь
        // экран, как окно настроек хоста
        size={{ base: "full", md: "6xl" }}
        scrollBehavior="inside"
      >
        <ModalOverlay />
        <ModalContent>
          {/* на телефоне поля уже, чтобы все четыре вкладки помещались */}
          <ModalHeader px={{ base: 4, md: 6 }}>
            {t("panelSettings.title")}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody px={{ base: 4, md: 6 }} sx={thinScrollbarSx}>
            <Tabs
              variant="enclosed"
              colorScheme="primary"
              index={tabIndex}
              onChange={setTabIndex}
            >
              {/* вкладки закреплены под заголовком: на длинных «Сообщениях» не
                  нужно листать вверх, чтобы переключиться. Фон — как у окна */}
              <TabList
                overflowX="auto"
                overflowY="hidden"
                whiteSpace="nowrap"
                position="sticky"
                // у тела окна отступ сверху 0.5rem: без сдвига в щель над
                // вкладками просвечивал уезжающий контент
                top="-0.5rem"
                mt="-0.5rem"
                pt="0.5rem"
                zIndex={2}
                bg="white"
                _dark={{ bg: "gray.700" }}
                // на телефоне все четыре вкладки помещаются без прокрутки
                sx={{
                  "& > button": {
                    px: { base: 1.5, md: 4 },
                    fontSize: { base: "13px", md: "md" },
                  },
                }}
              >
                <Tab>
                  {t("panelSettings.tabSubscription")}
                  {subscriptionDirty && dirtyDot}
                </Tab>
                <Tab>
                  {t("panelSettings.tabMessages")}
                  {messagesDirty && dirtyDot}
                </Tab>
                <Tab>{t("panelSettings.tabV2rayJson")}</Tab>
                <Tab>
                  {t("panelSettings.tabJwtKey")}
                  {jwtDirty && dirtyDot}
                </Tab>
              </TabList>
              <TabPanels>
                <TabPanel px={0}>
                  <VStack spacing={4} align="stretch">
                    <FormControl>
                      <FormLabel>{t("panelSettings.subRoutingHapp")}</FormLabel>
                      <Input
                        value={settings.sub_routing_happ}
                        placeholder="happ://"
                        onChange={(e) =>
                          updateSettings({ sub_routing_happ: e.target.value })
                        }
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>
                        {t("panelSettings.subRoutingV2raytun")}
                      </FormLabel>
                      <Input
                        value={settings.sub_routing_v2raytun}
                        placeholder="v2ray://"
                        onChange={(e) =>
                          updateSettings({
                            sub_routing_v2raytun: e.target.value,
                          })
                        }
                      />
                    </FormControl>
                    <FormControl>
                      <FormLabel>
                        {t("panelSettings.subCustomHeaders")}
                      </FormLabel>
                      <AutoResizeTextarea
                        value={settings.sub_custom_headers}
                        placeholder={"routing-enable: 0"}
                        onChange={(e) =>
                          updateSettings({ sub_custom_headers: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {t("panelSettings.subCustomHeadersHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl>
                      <FormLabel>
                        {t("panelSettings.bsMonthlyLimitGb")}
                      </FormLabel>
                      <Input
                        type="number"
                        value={
                          settings.bs_monthly_limit
                            ? String(settings.bs_monthly_limit / GB_IN_BYTES)
                            : ""
                        }
                        placeholder="0"
                        onChange={(e) => {
                          const gb = parseFloat(e.target.value);
                          updateSettings({
                            bs_monthly_limit:
                              e.target.value === "" || isNaN(gb)
                                ? 0
                                : Math.round(gb * GB_IN_BYTES),
                          });
                        }}
                      />
                      <FormHelperText>
                        {t("panelSettings.bsMonthlyLimitGbHint")}
                      </FormHelperText>
                    </FormControl>
                  </VStack>
                </TabPanel>
                <TabPanel px={0}>
                  <Flex
                    direction={{ base: "column", xl: "row" }}
                    align="flex-start"
                    gap={6}
                  >
                    <VStack spacing={4} align="stretch" flex="1" minW={0}>
                      <Box maxW={{ md: "320px" }}>
                        <HappScenarioSelect
                          value={previewScenario}
                          onChange={setPreviewScenario}
                        />
                      </Box>
                      <Box
                        border="1px solid"
                        borderColor="inherit"
                        borderRadius="md"
                        p={4}
                      >
                        <VStack spacing={4} align="stretch">
                          <Text
                            fontSize="xs"
                            fontWeight="semibold"
                            color="gray.500"
                            textTransform="uppercase"
                            letterSpacing="wide"
                          >
                            {t("botSettings.announceMessages")}
                          </Text>
                          <FormControl
                            display={fieldDisplay("sub_client_note")}
                          >
                            <FormLabel>
                              {t("botSettings.subClientNote")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={settings.sub_client_note}
                              minH="90px"
                              onChange={(e) =>
                                updateSettings({
                                  sub_client_note: e.target.value,
                                })
                              }
                            />
                          </FormControl>
                          <FormControl
                            display={fieldDisplay("sub_revoked_announce_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subRevokedAnnounceText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={settings.sub_revoked_announce_text}
                              minH="90px"
                              onChange={(e) =>
                                updateSettings({
                                  sub_revoked_announce_text: e.target.value,
                                })
                              }
                            />
                          </FormControl>
                          <FormControl
                            display={fieldDisplay("sub_expired_announce_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subExpiredAnnounceText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={settings.sub_expired_announce_text}
                              minH="90px"
                              onChange={(e) =>
                                updateSettings({
                                  sub_expired_announce_text: e.target.value,
                                })
                              }
                            />
                          </FormControl>
                          <FormControl
                            display={fieldDisplay(
                              "sub_unsupported_client_announce_text"
                            )}
                          >
                            <FormLabel>
                              {t(
                                "botSettings.subUnsupportedClientAnnounceText"
                              )}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={
                                settings.sub_unsupported_client_announce_text
                              }
                              minH="90px"
                              onChange={(e) =>
                                updateSettings({
                                  sub_unsupported_client_announce_text:
                                    e.target.value,
                                })
                              }
                            />
                          </FormControl>
                          <FormControl
                            display={fieldDisplay(
                              "sub_device_limit_announce_text"
                            )}
                          >
                            <FormLabel>
                              {t("botSettings.subDeviceLimitAnnounceText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={settings.sub_device_limit_announce_text}
                              minH="90px"
                              onChange={(e) =>
                                updateSettings({
                                  sub_device_limit_announce_text:
                                    e.target.value,
                                })
                              }
                            />
                          </FormControl>
                          <FormControl
                            display={fieldDisplay("sub_bs_limit_announce_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subBsLimitAnnounceText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={settings.sub_bs_limit_announce_text}
                              onChange={(e) =>
                                updateSettings({
                                  sub_bs_limit_announce_text: e.target.value,
                                })
                              }
                            />
                          </FormControl>
                        </VStack>
                      </Box>
                      <Box
                        display={
                          previewScenario === "normal" ? "none" : undefined
                        }
                        border="1px solid"
                        borderColor="inherit"
                        borderRadius="md"
                        p={4}
                      >
                        <VStack spacing={4} align="stretch">
                          <Text
                            fontSize="xs"
                            fontWeight="semibold"
                            color="gray.500"
                            textTransform="uppercase"
                            letterSpacing="wide"
                          >
                            {t("botSettings.serverResponses")}
                          </Text>
                          <FormControl
                            display={fieldDisplay("sub_revoked_server_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subRevokedServerText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={listFieldTexts.sub_revoked_server_text}
                              onChange={(e) =>
                                updateListField(
                                  "sub_revoked_server_text",
                                  e.target.value
                                )
                              }
                            />
                            <FormHelperText>
                              {t("botSettings.serverTextHint")}
                            </FormHelperText>
                          </FormControl>
                          <FormControl
                            display={fieldDisplay("sub_expired_server_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subExpiredServerText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={listFieldTexts.sub_expired_server_text}
                              onChange={(e) =>
                                updateListField(
                                  "sub_expired_server_text",
                                  e.target.value
                                )
                              }
                            />
                            <FormHelperText>
                              {t("botSettings.serverTextHint")}
                            </FormHelperText>
                          </FormControl>
                          <FormControl
                            display={fieldDisplay(
                              "sub_device_limit_server_text"
                            )}
                          >
                            <FormLabel>
                              {t("botSettings.subDeviceLimitServerText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={
                                listFieldTexts.sub_device_limit_server_text
                              }
                              onChange={(e) =>
                                updateListField(
                                  "sub_device_limit_server_text",
                                  e.target.value
                                )
                              }
                            />
                            <FormHelperText>
                              {t("botSettings.serverTextHint")}
                            </FormHelperText>
                          </FormControl>
                          <FormControl
                            display={fieldDisplay(
                              "sub_unsupported_client_server_text"
                            )}
                          >
                            <FormLabel>
                              {t("botSettings.subUnsupportedClientServerText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={
                                listFieldTexts.sub_unsupported_client_server_text
                              }
                              onChange={(e) =>
                                updateListField(
                                  "sub_unsupported_client_server_text",
                                  e.target.value
                                )
                              }
                            />
                            <FormHelperText>
                              {t("botSettings.serverTextHint")}
                            </FormHelperText>
                          </FormControl>
                          <FormControl
                            display={fieldDisplay("sub_bs_limit_server_text")}
                          >
                            <FormLabel>
                              {t("botSettings.subBsLimitServerText")}
                            </FormLabel>
                            <AutoResizeTextarea
                              value={listFieldTexts.sub_bs_limit_server_text}
                              onChange={(e) =>
                                updateListField(
                                  "sub_bs_limit_server_text",
                                  e.target.value
                                )
                              }
                            />
                            <FormHelperText>
                              {t("botSettings.serverTextHint")}
                            </FormHelperText>
                          </FormControl>
                        </VStack>
                      </Box>
                    </VStack>
                    {/* на широком экране предпросмотр справа и остаётся на виду,
                        пока листаешь тексты слева; на узком он под полями */}
                    <Box
                      display={{ base: "none", xl: "block" }}
                      flex={{ base: "1", xl: "0 0 430px" }}
                      w="full"
                      position={{ xl: "sticky" }}
                      // ниже закреплённых вкладок, чтобы не заезжать под них
                      top={{ xl: "56px" }}
                    >
                      <HappSubscriptionPreview
                        settings={settings}
                        scenario={previewScenario}
                      />
                    </Box>
                  </Flex>
                  {/* узкий экран: кнопка всегда видна внизу, пока листаешь тексты */}
                  <Flex
                    display={{ base: "flex", xl: "none" }}
                    position="sticky"
                    bottom={0}
                    justify="flex-end"
                    pt={3}
                    pointerEvents="none"
                  >
                    <Button
                      pointerEvents="auto"
                      size="sm"
                      colorScheme="primary"
                      shadow="md"
                      leftIcon={<EyeIcon width="16px" />}
                      onClick={previewOverlay.onOpen}
                    >
                      {t("panelSettings.happPreview")}
                    </Button>
                  </Flex>
                </TabPanel>
                <TabPanel px={0}>
                  <XrayTemplatesPanel />
                </TabPanel>
                <TabPanel px={0}>
                  <VStack spacing={4} align="stretch">
                    <FormControl>
                      <FormLabel>
                        {t("panelSettings.primaryJwtSecret")}
                      </FormLabel>
                      <Input
                        fontFamily="mono"
                        value={settings.primary_jwt_secret || ""}
                        isReadOnly
                        isDisabled
                      />
                      <FormHelperText>
                        {t("panelSettings.primaryJwtSecretHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl>
                      <FormLabel>{t("panelSettings.legacyJwtKeys")}</FormLabel>
                      <FormHelperText mb={3}>
                        {t("panelSettings.legacyJwtKeysHint")}
                      </FormHelperText>
                      <VStack spacing={2} align="stretch">
                        {settings.subscription_legacy_secret_keys.map(
                          (key, index) => (
                            <HStack key={index} align="center">
                              <Input
                                fontFamily="mono"
                                value={key}
                                onChange={(e) =>
                                  updateLegacyKey(index, e.target.value)
                                }
                              />
                              <Tooltip
                                label={t("delete")}
                                fontSize="xs"
                                hasArrow
                              >
                                <IconButton
                                  aria-label={t("delete")}
                                  icon={<DeleteIcon />}
                                  size="sm"
                                  variant="ghost"
                                  colorScheme="red"
                                  onClick={() => removeLegacyKey(index)}
                                />
                              </Tooltip>
                            </HStack>
                          )
                        )}
                        <Button
                          alignSelf="flex-start"
                          variant="outline"
                          onClick={addLegacyKey}
                        >
                          {t("panelSettings.addJwtKey")}
                        </Button>
                      </VStack>
                    </FormControl>
                  </VStack>
                </TabPanel>
              </TabPanels>
            </Tabs>
          </ModalBody>
          {tabIndex !== V2RAY_TAB_INDEX && (
            <ModalFooter px={{ base: 4, md: 6 }} justifyContent="space-between">
              <Button
                variant="ghost"
                colorScheme="red"
                size="sm"
                onClick={requestResetToDefaults}
                isLoading={loading}
              >
                {t("panelSettings.resetDefaults")}
              </Button>
              <HStack spacing={3}>
                {isDirty && (
                  <Text fontSize="sm" color="orange.400">
                    {t("panelSettings.unsavedChanges")}
                  </Text>
                )}
                <Button
                  colorScheme="primary"
                  onClick={save}
                  isLoading={saving}
                  isDisabled={loading || !isDirty}
                >
                  {t("core.save")}
                </Button>
              </HStack>
            </ModalFooter>
          )}
        </ModalContent>
      </Modal>

      <Modal
        // окно расширили до десктопа — превью уже стоит справа, оверлей не нужен
        isOpen={previewOverlay.isOpen && !isWide}
        onClose={previewOverlay.onClose}
        size="full"
        scrollBehavior="inside"
      >
        <ModalOverlay />
        <ModalContent>
          <ModalCloseButton />
          <ModalBody pt={3}>
            <HappSubscriptionPreview
              settings={settings}
              scenario={previewScenario}
              onScenarioChange={setPreviewScenario}
            />
          </ModalBody>
        </ModalContent>
      </Modal>

      <AlertDialog
        isCentered
        isOpen={pendingDefaults !== null}
        leastDestructiveRef={cancelResetRef}
        onClose={() => setPendingDefaults(null)}
        size="xl"
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader>
              {t("panelSettings.resetConfirmTitle")}
            </AlertDialogHeader>
            <AlertDialogBody>
              <VStack align="stretch" spacing={3}>
                <Alert status="info" variant="subtle" borderRadius="md">
                  <AlertIcon />
                  <AlertDescription fontSize="sm">
                    {t("panelSettings.resetConfirmHint")}
                  </AlertDescription>
                </Alert>
                <Text
                  fontSize="xs"
                  fontWeight="semibold"
                  textTransform="uppercase"
                  opacity={0.7}
                >
                  {t("panelSettings.resetWhatChanges")}
                </Text>
                {RESET_DIFF_TABS.map(({ tab, labelKey }) => {
                  const rows = resetDiff.filter((row) => row.tab === tab);
                  if (rows.length === 0) return null;
                  return (
                    <VStack key={tab} align="stretch" spacing={2}>
                      <Text fontSize="sm" fontWeight="semibold">
                        {t(labelKey)}
                      </Text>
                      <Box
                        borderWidth="1px"
                        borderRadius="md"
                        overflow="hidden"
                      >
                        {/* fixed-раскладка — чтобы колонки таблиц разных вкладок совпадали */}
                        <Table size="sm" sx={{ tableLayout: "fixed" }}>
                          <Thead>
                            <Tr>
                              <Th w="40%">{t("panelSettings.resetField")}</Th>
                              <Th w="30%">{t("panelSettings.resetCurrent")}</Th>
                              <Th w="30%">{t("panelSettings.resetNew")}</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {rows.map((row) => (
                              <Tr key={row.label}>
                                <Td fontSize="sm">{row.label}</Td>
                                <Td
                                  fontSize="sm"
                                  fontFamily="mono"
                                  wordBreak="break-all"
                                >
                                  {renderDiffValues(row.from)}
                                </Td>
                                <Td
                                  fontSize="sm"
                                  fontFamily="mono"
                                  wordBreak="break-all"
                                  fontWeight="semibold"
                                >
                                  {renderDiffValues(row.to)}
                                </Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      </Box>
                    </VStack>
                  );
                })}
              </VStack>
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button
                ref={cancelResetRef}
                onClick={() => setPendingDefaults(null)}
              >
                {t("cancel")}
              </Button>
              <Button colorScheme="red" ml={3} onClick={confirmResetToDefaults}>
                {t("panelSettings.resetConfirm")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>

      <AlertDialog
        isCentered
        isOpen={discardConfirm.isOpen}
        leastDestructiveRef={cancelDiscardRef}
        onClose={discardConfirm.onClose}
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader>
              {t("panelSettings.discardTitle")}
            </AlertDialogHeader>
            <AlertDialogBody>
              <Text fontSize="sm">{t("panelSettings.discardHint")}</Text>
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelDiscardRef} onClick={discardConfirm.onClose}>
                {t("cancel")}
              </Button>
              <Button colorScheme="red" ml={3} onClick={discardAndClose}>
                {t("panelSettings.discard")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  );
};

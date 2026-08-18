import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  Input,
  Text,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Switch,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Textarea,
  useToast,
  VStack,
  HStack,
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverBody,
  Text as ChakraText,
  useOutsideClick,
  InputGroup,
  InputLeftElement,
  SimpleGrid,
  Stack,
} from "@chakra-ui/react";
import { FC, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDashboard } from "contexts/DashboardContext";
import { fetch } from "service/http";
import { Bot, BotSettings } from "types/Bot";
import {
  ChevronDownIcon,
  MagnifyingGlassIcon,
} from "@heroicons/react/24/outline";

const toText = (values: string[] = []) => values.join("\n");

const toList = (value: string) =>
  value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);

const emptySettings: BotSettings = {
  sub_update_interval: "",
  sub_support_url: "",
  sub_profile_title: "",
  sub_client_note: "",
  sub_profile_url: "",
  sub_subscription_domain: "",
  bot_url: "",
  web_url: "",
  sub_revoked_announce_text: "",
  sub_expired_announce_text: "",
  sub_device_limit_announce_text: "",
  sub_device_limit_hard_mode: false,
  sub_unsupported_client_announce_text: "",
  sub_revoked_server_text: [],
  sub_expired_server_text: [],
  sub_device_limit_server_text: [],
  sub_unsupported_client_server_text: [],
  sub_bs_limit_server_text: [],
  sub_bs_limit_announce_text: "",
  bs_extra_reset_pool_on_prolong: false,
  show_ads: true,
};

type ServerTextField =
  | "sub_revoked_server_text"
  | "sub_expired_server_text"
  | "sub_device_limit_server_text"
  | "sub_unsupported_client_server_text"
  | "sub_bs_limit_server_text";

type ListFieldTexts = Record<ServerTextField, string>;

const toListFieldTexts = (settings: BotSettings): ListFieldTexts => ({
  sub_revoked_server_text: toText(settings.sub_revoked_server_text),
  sub_expired_server_text: toText(settings.sub_expired_server_text),
  sub_device_limit_server_text: toText(settings.sub_device_limit_server_text),
  sub_unsupported_client_server_text: toText(
    settings.sub_unsupported_client_server_text
  ),
  sub_bs_limit_server_text: toText(settings.sub_bs_limit_server_text),
});

export const BotSettingsDialog: FC = () => {
  const { isEditingBotSettings, onEditingBotSettings } = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const [bots, setBots] = useState<Bot[]>([]);
  const [selectedBot, setSelectedBot] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [syncingAdmin, setSyncingAdmin] = useState(false);
  const [defaultSettings, setDefaultSettings] =
    useState<BotSettings>(emptySettings);
  const [botUsername, setBotUsername] = useState("");
  const [botTitle, setBotTitle] = useState("");
  const [settings, setSettings] = useState<BotSettings>(emptySettings);
  const [serverSettings, setServerSettings] =
    useState<BotSettings>(emptySettings);
  const [hasDraft, setHasDraft] = useState(false);
  const [botSearch, setBotSearch] = useState("");
  const [isBotListOpen, setIsBotListOpen] = useState(false);
  const [listFieldTexts, setListFieldTexts] = useState<ListFieldTexts>(
    toListFieldTexts(emptySettings)
  );
  // const [didAutoSelect, setDidAutoSelect] = useState(false);
  const NEW_BOT_DRAFT_KEY = "botSettings_draft_new";

  const getDraftKey = (username: string) =>
    username ? `botSettings_draft_${username}` : NEW_BOT_DRAFT_KEY;

  const saveDraftTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const saveDraft = (
    newSettings: BotSettings,
    newUsername: string,
    newTitle: string
  ) => {
    const key = getDraftKey(selectedBot);
    if (saveDraftTimeout.current) clearTimeout(saveDraftTimeout.current);
    saveDraftTimeout.current = setTimeout(() => {
      localStorage.setItem(
        key,
        JSON.stringify({
          settings: newSettings,
          botUsername: newUsername,
          botTitle: newTitle,
          savedAt: Date.now(),
        })
      );
    }, 400);
  };

  const updateSettings = (patch: Partial<BotSettings>) => {
    const s = { ...settings, ...patch };
    setSettings(s);
    saveDraft(s, botUsername, botTitle);
  };

  const replaceSettings = (nextSettings: BotSettings) => {
    setSettings(nextSettings);
    setListFieldTexts(toListFieldTexts(nextSettings));
  };

  const updateListField = (field: ServerTextField, value: string) => {
    setListFieldTexts((current) => ({ ...current, [field]: value }));
    updateSettings({ [field]: toList(value) });
  };

  const fetchBots = () => {
    return fetch<Bot[]>("/bots")
      .then((items) => {
        setBots(items);
        return items;
      })
      .catch(() => {
        setBots([]);
        return [];
      });
  };

  useEffect(() => {
    return () => {
      if (saveDraftTimeout.current) clearTimeout(saveDraftTimeout.current);
    };
  }, []);

  useEffect(() => {
    if (!isEditingBotSettings) return;
    setLoading(true);
    setSelectedBot("");
    setBotUsername("");
    setBotTitle("");
    setBotSearch("");
    replaceSettings(emptySettings);
    Promise.all([
      fetchBots(),
      fetch<BotSettings>("/bots/default-settings").then(setDefaultSettings),
    ])
      .then(([bots]) => {
        if (bots.length === 1) {
          setSelectedBot(bots[0].username);
        }
      })
      .finally(() => setLoading(false));
  }, [isEditingBotSettings]);

  useEffect(() => {
    if (!isEditingBotSettings) return;

    if (saveDraftTimeout.current) clearTimeout(saveDraftTimeout.current);

    if (!selectedBot) {
      setBotUsername("");
      setBotTitle("");
      replaceSettings(emptySettings);
      setServerSettings(emptySettings);
      const newDraft = localStorage.getItem(NEW_BOT_DRAFT_KEY);
      setHasDraft(!!newDraft);
      return;
    }
    const selected = bots.find((bot) => bot.username === selectedBot);
    setBotUsername(selected?.username || "");
    setBotTitle(selected?.title || "");
    setLoading(true);

    let cancelled = false;

    fetch<BotSettings>(`/bots/${selectedBot}/settings`)
      .then((serverSettings) => {
        if (cancelled) return;
        replaceSettings(serverSettings);
        setServerSettings(serverSettings);

        const draftKey = getDraftKey(selectedBot);
        const draft = localStorage.getItem(draftKey);

        if (draft) {
          setHasDraft(true);
        } else {
          setHasDraft(false);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isEditingBotSettings, selectedBot, bots]);

  const restoreDraft = () => {
    const key = getDraftKey(selectedBot);
    const draft = localStorage.getItem(key);
    if (!draft) return;
    const parsed = JSON.parse(draft);
    const managed = !!(serverSettings.managed || selectedBotModel?.managed);
    replaceSettings(
      managed
        ? {
            ...parsed.settings,
            bot_url: serverSettings.bot_url,
            web_url: serverSettings.web_url,
            sub_support_url: serverSettings.sub_support_url,
            sub_subscription_domain: serverSettings.sub_subscription_domain,
            managed: serverSettings.managed,
          }
        : parsed.settings
    );
    setBotUsername(managed ? selectedBotModel?.username || "" : parsed.botUsername);
    setBotTitle(managed ? selectedBotModel?.title || "" : parsed.botTitle);
    localStorage.removeItem(key);
    setHasDraft(false);
  };

  const discardDraft = () => {
    localStorage.removeItem(getDraftKey(selectedBot));
    setHasDraft(false);
  };

  const close = () => onEditingBotSettings(false);

  const selectedBotModel = useMemo(
    () => bots.find((bot) => bot.username === selectedBot),
    [bots, selectedBot]
  );

  const managedState = settings.managed || selectedBotModel?.managed || null;
  const isManaged = !!managedState;
  const adminSyncEnabled = selectedBotModel?.admin_sync_enabled ?? true;

  const setAdminSync = (enabled: boolean) => {
    if (!selectedBot) return;
    setSyncingAdmin(true);
    fetch<Bot | { admin_sync_enabled: boolean }>(
      `/bots/${selectedBot}/admin-sync`,
      {
        method: "PATCH",
        body: { enabled },
      }
    )
      .then((updated) => {
        if (
          !updated.admin_sync_enabled ||
          ("managed" in updated && !updated.managed)
        ) {
          setSettings((current) => ({ ...current, managed: null }));
          setServerSettings((current) => ({ ...current, managed: null }));
        }
        setBots((current) =>
          current.map((bot) =>
            bot.username === selectedBot
              ? {
                  ...bot,
                  ...("id" in updated ? updated : {}),
                  admin_sync_enabled: updated.admin_sync_enabled,
                }
              : bot
          )
        );
        toast({
          title: t(
            updated.admin_sync_enabled
              ? "botSettings.adminSyncEnabled"
              : "botSettings.adminSyncDisabled"
          ),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .catch(() => {
        toast({
          title: t("botSettings.adminSyncFailed"),
          status: "error",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setSyncingAdmin(false));
  };

  const defaultListFieldTexts = useMemo(
    () => toListFieldTexts(defaultSettings),
    [defaultSettings]
  );

  const mergeWithDefaults = (current: BotSettings): BotSettings => {
    return {
      sub_update_interval:
        current.sub_update_interval.trim() ||
        defaultSettings.sub_update_interval,
      sub_support_url:
        current.sub_support_url.trim() || defaultSettings.sub_support_url,
      sub_profile_title:
        current.sub_profile_title.trim() || defaultSettings.sub_profile_title,
      sub_client_note:
        current.sub_client_note.trim() || defaultSettings.sub_client_note,
      sub_profile_url:
        current.sub_profile_url.trim() || defaultSettings.sub_profile_url,
      sub_subscription_domain:
        (current.sub_subscription_domain || "").trim() ||
        defaultSettings.sub_subscription_domain,
      bot_url: current.bot_url.trim() || defaultSettings.bot_url,
      web_url: current.web_url.trim() || defaultSettings.web_url,
      sub_revoked_announce_text:
        current.sub_revoked_announce_text.trim() ||
        defaultSettings.sub_revoked_announce_text,
      sub_expired_announce_text:
        current.sub_expired_announce_text.trim() ||
        defaultSettings.sub_expired_announce_text,
      sub_device_limit_announce_text:
        current.sub_device_limit_announce_text.trim() ||
        defaultSettings.sub_device_limit_announce_text,
      sub_device_limit_hard_mode: current.sub_device_limit_hard_mode,
      sub_unsupported_client_announce_text:
        current.sub_unsupported_client_announce_text.trim() ||
        defaultSettings.sub_unsupported_client_announce_text,
      sub_revoked_server_text:
        current.sub_revoked_server_text.length > 0
          ? current.sub_revoked_server_text
          : defaultSettings.sub_revoked_server_text,
      sub_expired_server_text:
        current.sub_expired_server_text.length > 0
          ? current.sub_expired_server_text
          : defaultSettings.sub_expired_server_text,
      sub_device_limit_server_text:
        current.sub_device_limit_server_text.length > 0
          ? current.sub_device_limit_server_text
          : defaultSettings.sub_device_limit_server_text,
      sub_unsupported_client_server_text:
        current.sub_unsupported_client_server_text.length > 0
          ? current.sub_unsupported_client_server_text
          : defaultSettings.sub_unsupported_client_server_text,
      sub_bs_limit_server_text:
        current.sub_bs_limit_server_text.length > 0
          ? current.sub_bs_limit_server_text
          : defaultSettings.sub_bs_limit_server_text,
      sub_bs_limit_announce_text:
        current.sub_bs_limit_announce_text.trim() ||
        defaultSettings.sub_bs_limit_announce_text,
      bs_extra_reset_pool_on_prolong: current.bs_extra_reset_pool_on_prolong,
      show_ads: current.show_ads,
    };
  };

  const save = () => {
    if (!selectedBot) return;
    const normalizedUsername = botUsername.trim().replace(/^@/, "");
    if (!normalizedUsername) return;
    const normalizedTitle = botTitle.trim();
    const isIdentityChanged =
      !isManaged &&
      (normalizedUsername !== selectedBot ||
        normalizedTitle !== (selectedBotModel?.title || ""));
    const { managed: _managed, updated_at: _updatedAt, ...editableSettings } =
      settings;
    const settingsPayload = {
      ...editableSettings,
      ...(isManaged
        ? {
            bot_url: serverSettings.bot_url,
            web_url: serverSettings.web_url,
            sub_support_url: serverSettings.sub_support_url,
            sub_subscription_domain: serverSettings.sub_subscription_domain,
          }
        : {}),
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

    setSaving(true);
    let targetUsername = selectedBot;
    const identityPromise = isIdentityChanged
      ? fetch<Bot>(`/bots/${selectedBot}`, {
          method: "PATCH",
          body: {
            username: normalizedUsername,
            title: normalizedTitle || null,
          },
        }).then((updatedBot) => {
          targetUsername = updatedBot.username;
          setBotUsername(updatedBot.username);
          setBotTitle(updatedBot.title || "");
        })
      : Promise.resolve();

    identityPromise
      .then(() =>
        fetch<BotSettings>(`/bots/${targetUsername}/settings`, {
          method: "PUT",
          body: settingsPayload,
        })
      )
      .then((updated) => {
        replaceSettings(updated);
        return fetchBots().then(() => {
          setSelectedBot(targetUsername);
        });
      })
      .then(() => {
        localStorage.removeItem(getDraftKey(targetUsername));
        setHasDraft(false);
        toast({
          title: t("botSettings.saved"),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
        close();
      })
      .catch(() => {
        toast({
          title: t("core.generalErrorMessage"),
          status: "error",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setSaving(false));
  };

  const createBot = () => {
    if (!botUsername.trim()) return;
    setCreating(true);
    fetch<Bot>("/bots", {
      method: "POST",
      body: {
        username: botUsername.trim(),
        title: botTitle.trim() || null,
      },
    })
      .then((bot) => {
        return fetch<BotSettings>(`/bots/${bot.username}/settings`, {
          method: "PUT",
          body: mergeWithDefaults(settings),
        }).then(() => bot);
      })
      .then((bot) => {
        localStorage.removeItem(NEW_BOT_DRAFT_KEY);
        setHasDraft(false);
        return fetchBots().then(() => {
          setSelectedBot(bot.username);
        });
      })
      .then(() => {
        toast({
          title: t("botSettings.created"),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setCreating(false));
  };

  const deleteBot = () => {
    if (!selectedBot) return;
    if (
      !window.confirm(
        t("botSettings.deleteConfirm", { username: `@${selectedBot}` })
      )
    ) {
      return;
    }

    setDeleting(true);
    const deletedKey = getDraftKey(selectedBot);
    fetch(`/bots/${selectedBot}`, { method: "DELETE" })
      .then(() => {
        localStorage.removeItem(deletedKey);
        setHasDraft(false);
        return fetchBots();
      })
      .then((bots) => {
        if (bots.length === 1) {
          setSelectedBot(bots[0].username);
        } else {
          setSelectedBot("");
          setBotUsername("");
          setBotTitle("");
          setBotSearch("");
        }

        toast({
          title: t("botSettings.deleted"),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setDeleting(false));
  };

  return (
    <Modal
      isOpen={isEditingBotSettings}
      onClose={close}
      size={{ base: "full", md: "4xl" }}
      scrollBehavior="inside"
    >
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent maxH="90vh" display="flex" flexDirection="column">
        <ModalHeader pt={6} pb={4} pr={16}>
          <HStack justify="space-between" align="center" w="full">
            <Box>
              <Text fontSize="lg" fontWeight="semibold">
                {t("botSettings.title")}
              </Text>
            </Box>
            <Popover
              placement="bottom-start"
              isOpen={isBotListOpen}
              onClose={() => setIsBotListOpen(false)}
            >
              <PopoverTrigger>
                <Button
                  size="sm"
                  w={{ base: "full", md: "270px" }}
                  justifyContent="space-between"
                  onClick={() => {
                    setBotSearch("");
                    setIsBotListOpen(true);
                  }}
                >
                  <Text>
                    {selectedBot
                      ? `@${selectedBot}`
                      : t("botSettings.selectBot")}
                  </Text>

                  <ChevronDownIcon
                    width={14}
                    height={14}
                    color="currentColor"
                    style={{
                      opacity: 0.6,
                      transform: isBotListOpen
                        ? "rotate(180deg)"
                        : "rotate(0deg)",
                      transition: "transform 0.2s",
                    }}
                  />
                </Button>
              </PopoverTrigger>

              <PopoverContent
                w="280px"
                maxH="320px"
                overflow="hidden"
                fontSize="sm"
              >
                <PopoverBody p={2}>
                  <InputGroup size="sm" mb={2}>
                    <InputLeftElement pointerEvents="none">
                      <MagnifyingGlassIcon color="gray.400" width="16px" />
                    </InputLeftElement>
                    <Input
                      size="sm"
                      fontSize="sm"
                      height="32px"
                      px={2}
                      placeholder={t("botSettings.botSearchPlaceholder")}
                      value={botSearch}
                      autoFocus
                      onChange={(e) => setBotSearch(e.target.value)}
                      mb={2}
                    />
                  </InputGroup>

                  <VStack
                    align="stretch"
                    maxH="240px"
                    overflowY="auto"
                    spacing={1}
                  >
                    <Box
                      px={2}
                      py={1}
                      cursor="pointer"
                      _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                      onClick={() => {
                        setSelectedBot("");
                        setBotSearch("");
                        setIsBotListOpen(false);
                      }}
                    >
                      {t("botSettings.emptySelection")}
                    </Box>

                    {bots
                      .filter((bot) => {
                        const q = botSearch.toLowerCase().replace(/^@/, "");
                        if (!q) return true;

                        return (
                          bot.username.toLowerCase().includes(q) ||
                          (bot.title || "").toLowerCase().includes(q)
                        );
                      })
                      .map((bot) => (
                        <Box
                          key={bot.id}
                          px={2}
                          py={1}
                          cursor="pointer"
                          bg={
                            selectedBot === bot.username
                              ? "primary.50"
                              : undefined
                          }
                          _dark={{
                            bg:
                              selectedBot === bot.username
                                ? "primary.900"
                                : undefined,
                          }}
                          _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                          onClick={() => {
                            setSelectedBot(bot.username);
                            setBotSearch("");
                            setIsBotListOpen(false);
                          }}
                        >
                          <Text>@{bot.username}</Text>
                          {bot.title && (
                            <Text as="span" ml={2} opacity={0.6}>
                              — {bot.title}
                            </Text>
                          )}
                        </Box>
                      ))}
                  </VStack>
                </PopoverBody>
              </PopoverContent>
            </Popover>
          </HStack>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody
          flex="1"
          minH={0}
          style={{
            scrollbarGutter: "stable",
          }}
        >
          <Tabs variant="enclosed" colorScheme="primary">
            <TabList overflowX="auto" overflowY="hidden" whiteSpace="nowrap">
              <Tab>{t("botSettings.tabBotInfo")}</Tab>
              <Tab>{t("botSettings.tabSubscription")}</Tab>
              <Tab>{t("botSettings.tabMessages")}</Tab>
            </TabList>
            {hasDraft && (
              <HStack
                mt={2}
                p={3}
                borderRadius="md"
                bg="yellow.50"
                _dark={{ bg: "yellow.900" }}
                border="1px solid"
                borderColor="yellow.200"
                _dark-border={{ borderColor: "yellow.700" }}
                justify="space-between"
              >
                <ChakraText
                  fontSize="sm"
                  color="yellow.800"
                  _dark={{ color: "yellow.200" }}
                >
                  {t("botSettings.draftFound")}
                </ChakraText>
                <HStack>
                  <Button size="xs" colorScheme="yellow" onClick={restoreDraft}>
                    {t("botSettings.draftRestore")}
                  </Button>
                  <Button size="xs" variant="ghost" onClick={discardDraft}>
                    {t("botSettings.draftDiscard")}
                  </Button>
                </HStack>
              </HStack>
            )}
            <VStack mt={3} spacing={3} align="stretch">
              <FormControl
                display="flex"
                alignItems="center"
                justifyContent="space-between"
                borderWidth="1px"
                borderRadius="md"
                px={4}
                py={3}
              >
                <Box pr={4}>
                  <FormLabel mb={0}>
                    {t("botSettings.adminSync")}
                  </FormLabel>
                  <FormHelperText mt={1}>
                    {selectedBot
                      ? t("botSettings.adminSyncHint")
                      : t("botSettings.adminSyncNewBotHint")}
                  </FormHelperText>
                </Box>
                <Switch
                  colorScheme="primary"
                  isChecked={selectedBot ? adminSyncEnabled : true}
                  isDisabled={!selectedBot || syncingAdmin}
                  onChange={(event) => setAdminSync(event.target.checked)}
                />
              </FormControl>
              {isManaged && (
                <Alert
                  status="info"
                  variant="left-accent"
                  borderRadius="md"
                  alignItems="flex-start"
                >
                  <AlertIcon mt={0.5} />
                  <AlertDescription fontSize="sm">
                    {t("botSettings.managedBanner", {
                      source: managedState?.source,
                      version: managedState?.version,
                    })}
                  </AlertDescription>
                </Alert>
              )}
            </VStack>
            <TabPanels minH="400px" pt={2}>
              {/* Вкладка 1: Bot Info */}
              <TabPanel px={0}>
                <VStack spacing={4} align="stretch">
                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>{t("botSettings.newBotUsername")}</FormLabel>
                      <Input
                        value={botUsername}
                        onChange={(e) => {
                          setBotUsername(e.target.value);
                          saveDraft(settings, e.target.value, botTitle);
                        }}
                        placeholder="@my_vpn_bot"
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.newBotUsernameHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>{t("botSettings.newBotTitle")}</FormLabel>
                      <Input
                        value={botTitle}
                        onChange={(e) => {
                          setBotTitle(e.target.value);
                          saveDraft(settings, botUsername, e.target.value);
                        }}
                        placeholder="My VPN Bot"
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.newBotTitleHint")}
                      </FormHelperText>
                    </FormControl>
                  </SimpleGrid>

                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>{t("botSettings.botUrl")}</FormLabel>
                      <Input
                        value={settings.bot_url}
                        placeholder="https://t.me/my_vpn_bot"
                        onChange={(e) =>
                          updateSettings({ bot_url: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.botUrlHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>{t("botSettings.webUrl")}</FormLabel>
                      <Input
                        value={settings.web_url}
                        placeholder="https://cabinet.example.com"
                        onChange={(e) =>
                          updateSettings({ web_url: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.webUrlHint")}
                      </FormHelperText>
                    </FormControl>
                  </SimpleGrid>

                  <FormControl>
                    <FormLabel>{t("botSettings.showAds")}</FormLabel>
                    <Switch
                      colorScheme="primary"
                      isChecked={settings.show_ads}
                      onChange={(e) =>
                        updateSettings({ show_ads: e.target.checked })
                      }
                    />
                    <FormHelperText>
                      {t("botSettings.showAdsHint")}
                    </FormHelperText>
                  </FormControl>
                </VStack>
              </TabPanel>

              {/* Вкладка 2: Subscription Settings */}
              <TabPanel px={0}>
                <VStack spacing={4} align="stretch">
                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>{t("botSettings.subSupportUrl")}</FormLabel>
                      <Input
                        value={settings.sub_support_url}
                        placeholder="https://t.me/support"
                        onChange={(e) =>
                          updateSettings({ sub_support_url: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.subSupportUrlHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl>
                      <FormLabel>{t("botSettings.subProfileTitle")}</FormLabel>
                      <Input
                        value={settings.sub_profile_title}
                        placeholder="My VPN"
                        onChange={(e) =>
                          updateSettings({ sub_profile_title: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {t("botSettings.subProfileTitleHint")}
                      </FormHelperText>
                    </FormControl>
                  </SimpleGrid>

                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl>
                      <FormLabel>{t("botSettings.subProfileUrl")}</FormLabel>
                      <Input
                        value={settings.sub_profile_url}
                        placeholder="https://example.com/profile"
                        onChange={(e) =>
                          updateSettings({ sub_profile_url: e.target.value })
                        }
                      />
                      <FormHelperText>
                        {t("botSettings.subProfileUrlHint")}
                      </FormHelperText>
                    </FormControl>
                    <FormControl isDisabled={isManaged}>
                      <FormLabel>
                        {t("botSettings.subSubscriptionDomain")}
                      </FormLabel>
                      <Input
                        value={settings.sub_subscription_domain || ""}
                        placeholder="example.net"
                        onChange={(e) =>
                          updateSettings({
                            sub_subscription_domain: e.target.value,
                          })
                        }
                      />
                      <FormHelperText>
                        {isManaged
                          ? t("botSettings.managedFieldHint")
                          : t("botSettings.subSubscriptionDomainHint")}
                      </FormHelperText>
                    </FormControl>
                  </SimpleGrid>

                  <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                    <FormControl>
                      <FormLabel>
                        {t("botSettings.subUpdateInterval")}
                      </FormLabel>
                      <Input
                        value={settings.sub_update_interval}
                        onChange={(e) =>
                          updateSettings({
                            sub_update_interval: e.target.value,
                          })
                        }
                      />
                      <FormHelperText>
                        {t("botSettings.subUpdateIntervalHint")}
                      </FormHelperText>
                    </FormControl>
                  </SimpleGrid>

                  <FormControl>
                    <FormLabel>{t("botSettings.subClientNote")}</FormLabel>
                    <Textarea
                      value={settings.sub_client_note}
                      placeholder={defaultSettings.sub_client_note}
                      onChange={(e) =>
                        updateSettings({ sub_client_note: e.target.value })
                      }
                    />
                  </FormControl>
                  <Box
                    border="1px solid"
                    borderColor="inherit"
                    borderRadius="md"
                    p={4}
                  >
                    <FormControl>
                      <FormLabel>
                        {t("botSettings.bsExtraResetPoolOnProlong")}
                      </FormLabel>
                      <Switch
                        colorScheme="primary"
                        isChecked={settings.bs_extra_reset_pool_on_prolong}
                        onChange={(e) =>
                          updateSettings({
                            bs_extra_reset_pool_on_prolong: e.target.checked,
                          })
                        }
                      />
                      <FormHelperText>
                        {t("botSettings.bsExtraResetPoolOnProlongHint")}
                      </FormHelperText>
                    </FormControl>
                  </Box>
                </VStack>
              </TabPanel>

              {/* Вкладка 3: Messages */}
              <TabPanel px={0}>
                <VStack spacing={4} align="stretch">
                  <Box
                    border="1px solid"
                    borderColor="inherit"
                    borderRadius="md"
                    p={4}
                  >
                    <VStack spacing={4} align="stretch">
                      <ChakraText
                        fontSize="xs"
                        fontWeight="semibold"
                        color="gray.500"
                        textTransform="uppercase"
                        letterSpacing="wide"
                      >
                        {t("botSettings.announceMessages")}
                      </ChakraText>

                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subRevokedAnnounceText")}
                          </FormLabel>
                          <Textarea
                            value={settings.sub_revoked_announce_text}
                            placeholder={
                              defaultSettings.sub_revoked_announce_text
                            }
                            onChange={(e) =>
                              updateSettings({
                                sub_revoked_announce_text: e.target.value,
                              })
                            }
                            _placeholder={{ fontSize: "12px" }}
                            minH="90px"
                          />
                        </FormControl>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subExpiredAnnounceText")}
                          </FormLabel>
                          <Textarea
                            value={settings.sub_expired_announce_text}
                            placeholder={
                              defaultSettings.sub_expired_announce_text
                            }
                            onChange={(e) =>
                              updateSettings({
                                sub_expired_announce_text: e.target.value,
                              })
                            }
                            _placeholder={{ fontSize: "12px" }}
                            minH="90px"
                          />
                        </FormControl>
                      </SimpleGrid>

                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subUnsupportedClientAnnounceText")}
                          </FormLabel>
                          <Textarea
                            value={
                              settings.sub_unsupported_client_announce_text
                            }
                            placeholder={
                              defaultSettings.sub_unsupported_client_announce_text
                            }
                            onChange={(e) =>
                              updateSettings({
                                sub_unsupported_client_announce_text:
                                  e.target.value,
                              })
                            }
                            _placeholder={{ fontSize: "12px" }}
                            minH="90px"
                          />
                        </FormControl>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subDeviceLimitAnnounceText")}
                          </FormLabel>
                          <Textarea
                            value={settings.sub_device_limit_announce_text}
                            placeholder={
                              defaultSettings.sub_device_limit_announce_text
                            }
                            onChange={(e) =>
                              updateSettings({
                                sub_device_limit_announce_text: e.target.value,
                              })
                            }
                            _placeholder={{ fontSize: "12px" }}
                            minH="90px"
                          />
                        </FormControl>
                      </SimpleGrid>

                      <FormControl>
                        <FormLabel>
                          {t("botSettings.subBsLimitAnnounceText")}
                        </FormLabel>
                        <Textarea
                          value={settings.sub_bs_limit_announce_text}
                          placeholder={
                            defaultSettings.sub_bs_limit_announce_text
                          }
                          onChange={(e) =>
                            updateSettings({
                              sub_bs_limit_announce_text: e.target.value,
                            })
                          }
                          _placeholder={{ fontSize: "12px" }}
                        />
                      </FormControl>
                    </VStack>
                  </Box>

                  <Box
                    border="1px solid"
                    borderColor="inherit"
                    borderRadius="md"
                    p={4}
                  >
                    <FormControl>
                      <FormLabel>
                        {t("botSettings.subDeviceLimitHardMode")}
                      </FormLabel>
                      <Switch
                        colorScheme="primary"
                        isChecked={settings.sub_device_limit_hard_mode}
                        onChange={(e) =>
                          updateSettings({
                            sub_device_limit_hard_mode: e.target.checked,
                          })
                        }
                        _placeholder={{ fontSize: "12px" }}
                      />
                      <FormHelperText>
                        {t("botSettings.subDeviceLimitHardModeHint")}
                      </FormHelperText>
                    </FormControl>
                  </Box>

                  {/* Server Responses */}
                  <Box
                    border="1px solid"
                    borderColor="inherit"
                    borderRadius="md"
                    p={4}
                  >
                    <VStack spacing={4} align="stretch">
                      <ChakraText
                        fontSize="xs"
                        fontWeight="semibold"
                        color="gray.500"
                        textTransform="uppercase"
                        letterSpacing="wide"
                      >
                        {t("botSettings.serverResponses")}
                      </ChakraText>

                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subRevokedServerText")}
                          </FormLabel>
                          <Textarea
                            value={listFieldTexts.sub_revoked_server_text}
                            placeholder={
                              defaultListFieldTexts.sub_revoked_server_text
                            }
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
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subExpiredServerText")}
                          </FormLabel>
                          <Textarea
                            value={listFieldTexts.sub_expired_server_text}
                            placeholder={
                              defaultListFieldTexts.sub_expired_server_text
                            }
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
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subBsLimitServerText")}
                          </FormLabel>
                          <Textarea
                            value={listFieldTexts.sub_bs_limit_server_text}
                            placeholder={
                              defaultListFieldTexts.sub_bs_limit_server_text
                            }
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
                      </SimpleGrid>
                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subDeviceLimitServerText")}
                          </FormLabel>
                          <Textarea
                            value={listFieldTexts.sub_device_limit_server_text}
                            placeholder={
                              defaultListFieldTexts.sub_device_limit_server_text
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
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subUnsupportedClientServerText")}
                          </FormLabel>
                          <Textarea
                            value={
                              listFieldTexts.sub_unsupported_client_server_text
                            }
                            placeholder={
                              defaultListFieldTexts.sub_unsupported_client_server_text
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
                      </SimpleGrid>
                    </VStack>
                  </Box>
                </VStack>
              </TabPanel>
            </TabPanels>
          </Tabs>
        </ModalBody>

        <ModalFooter>
          <Stack
            direction={{ base: "column", md: "row" }}
            justify="space-between"
            align={{ base: "stretch", md: "center" }}
            w="full"
            spacing={4}
          >
            <HStack spacing={2} w={{ base: "full", md: "auto" }}>
              <Button
                flex={1}
                variant="outline"
                colorScheme="green"
                onClick={createBot}
                isLoading={creating}
                isDisabled={!!selectedBot || !botUsername.trim()}
              >
                {t("botSettings.createBot")}
              </Button>

              <Button
                flex={1}
                variant="outline"
                colorScheme="red"
                onClick={deleteBot}
                isLoading={deleting}
                isDisabled={!selectedBot}
              >
                {t("botSettings.deleteBot")}
              </Button>
            </HStack>

            <HStack spacing={2} w={{ base: "full", md: "auto" }}>
              <Button flex={1} variant="ghost" onClick={close}>
                {t("cancel")}
              </Button>

              <Button
                flex={1}
                colorScheme="primary"
                onClick={save}
                isLoading={saving}
                isDisabled={loading || !selectedBot || !botUsername.trim()}
              >
                {t("core.save")}
              </Button>
            </HStack>
          </Stack>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};

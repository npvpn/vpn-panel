import {
  Alert,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  IconButton,
  Input,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Text,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Switch,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tooltip,
  useToast,
  VStack,
  HStack,
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverBody,
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
  EllipsisHorizontalIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  TrashIcon,
} from "@heroicons/react/24/outline";

const emptySettings: BotSettings = {
  sub_support_url: "",
  sub_profile_title: "",
  sub_profile_url: "",
  sub_subscription_domain: "",
  bot_url: "",
  web_url: "",
  bs_extra_reset_pool_on_prolong: false,
  show_ads: true,
};

type ServiceView =
  | { mode: "create"; returnTo: string }
  | { mode: "edit"; username: string };

const serviceView = (username?: string | null): ServiceView =>
  username ? { mode: "edit", username } : { mode: "create", returnTo: "" };

const NEW_BOT_DRAFT_KEY = "botSettings_draft_new";
const getDraftKey = (username: string) =>
  username ? `botSettings_draft_${username}` : NEW_BOT_DRAFT_KEY;

const ServiceSettingSwitch: FC<{
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}> = ({ label, description, checked, disabled, onChange }) => (
  <FormControl
    display="flex"
    alignItems="center"
    gap={4}
    borderWidth="1px"
    borderRadius="md"
    px={4}
    py={3}
    isDisabled={disabled}
  >
    <Box flex="1" minW={0}>
      <FormLabel mb={0}>{label}</FormLabel>
      <FormHelperText mt={1}>{description}</FormHelperText>
    </Box>
    <Switch
      flexShrink={0}
      colorScheme="primary"
      isChecked={checked}
      onChange={(event) => onChange(event.target.checked)}
    />
  </FormControl>
);

export const BotSettingsDialog: FC = () => {
  const { isEditingBotSettings, botSettingsUsername, onEditingBotSettings } =
    useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const [bots, setBots] = useState<Bot[]>([]);
  const [view, setView] = useState<ServiceView>(() => serviceView());
  const selectedBot = view.mode === "edit" ? view.username : "";
  const isCreatingBot = view.mode === "create";
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isBotSettingsLoading, setIsBotSettingsLoading] = useState(false);
  const [botSettingsLoaded, setBotSettingsLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [botToDelete, setBotToDelete] = useState<Bot | null>(null);
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
  const [activeTabIndex, setActiveTabIndex] = useState(0);
  const [isBotListOpen, setIsBotListOpen] = useState(false);
  const [isFirstServiceConfirmOpen, setIsFirstServiceConfirmOpen] =
    useState(false);
  const botSearchRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const cancelFirstServiceRef = useRef<HTMLButtonElement>(null);
  const cancelDeleteRef = useRef<HTMLButtonElement>(null);
  const botsRequestId = useRef(0);
  const isMutating = saving || creating || deleting || syncingAdmin;
  const selectedBotModel = useMemo(
    () => bots.find((bot) => bot.username === selectedBot),
    [bots, selectedBot]
  );
  const selectedBotTitle = selectedBotModel?.title || "";
  const searchQuery = botSearch.trim().toLowerCase().replace(/^@/, "");
  const matchingBots = bots.filter(
    (bot) =>
      bot.username.toLowerCase().includes(searchQuery) ||
      (bot.title || "").toLowerCase().includes(searchQuery)
  );

  const saveDraft = (
    newSettings: BotSettings,
    newUsername: string,
    newTitle: string
  ) => {
    localStorage.setItem(
      getDraftKey(selectedBot),
      JSON.stringify({
        settings: newSettings,
        botUsername: newUsername,
        botTitle: newTitle,
        savedAt: Date.now(),
      })
    );
    setHasDraft(false);
  };

  const updateSettings = (patch: Partial<BotSettings>) => {
    const s = { ...settings, ...patch };
    setSettings(s);
    saveDraft(s, botUsername, botTitle);
  };

  const replaceSettings = (nextSettings: BotSettings) => {
    setSettings(nextSettings);
  };

  const fetchBots = () => {
    const requestId = botsRequestId.current;
    return fetch<Bot[]>("/bots")
      .then((items) => {
        if (requestId !== botsRequestId.current) return null;
        setBots(items);
        return items;
      })
      .catch(() => {
        if (requestId !== botsRequestId.current) return null;
        setBots([]);
        return null;
      });
  };

  useEffect(() => {
    const requestId = ++botsRequestId.current;
    if (!isEditingBotSettings) {
      setIsInitialLoading(true);
      return () => {
        ++botsRequestId.current;
      };
    }
    setIsInitialLoading(true);
    setView(serviceView(botSettingsUsername));
    setBotUsername("");
    setBotTitle("");
    setBotSearch("");
    setActiveTabIndex(0);
    replaceSettings(emptySettings);
    Promise.allSettled([
      fetchBots().then((loadedBots) => {
        if (requestId !== botsRequestId.current) return;
        if (!loadedBots) {
          toast({
            title: t("core.generalErrorMessage"),
            status: "error",
            duration: 2500,
            isClosable: true,
            position: "top",
          });
          return;
        }
      }),
      fetch<BotSettings>("/bots/default-settings")
        .then((items) => {
          if (requestId === botsRequestId.current) setDefaultSettings(items);
        })
        .catch(() => undefined),
    ]).finally(() => {
      if (requestId === botsRequestId.current) setIsInitialLoading(false);
    });
    return () => {
      ++botsRequestId.current;
    };
  }, [isEditingBotSettings, botSettingsUsername]);

  useEffect(() => {
    if (!isEditingBotSettings || isInitialLoading) return;

    if (!selectedBot) {
      setBotUsername("");
      setBotTitle("");
      replaceSettings(emptySettings);
      setServerSettings(emptySettings);
      setBotSettingsLoaded(false);
      setIsBotSettingsLoading(false);
      setHasDraft(!!localStorage.getItem(NEW_BOT_DRAFT_KEY));
      return;
    }
    setBotUsername(selectedBot);
    setBotTitle(selectedBotTitle);
    setIsBotSettingsLoading(true);
    setBotSettingsLoaded(false);
    setHasDraft(false);

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
        setBotSettingsLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setBotSettingsLoaded(false);
      })
      .finally(() => {
        if (!cancelled) setIsBotSettingsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isEditingBotSettings, isInitialLoading, selectedBot, selectedBotTitle]);

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
    setBotUsername(
      managed ? selectedBotModel?.username || "" : parsed.botUsername
    );
    setBotTitle(managed ? selectedBotModel?.title || "" : parsed.botTitle);
    setHasDraft(false);
  };

  const discardDraft = () => {
    localStorage.removeItem(getDraftKey(selectedBot));
    setHasDraft(false);
  };

  const close = () => {
    setIsFirstServiceConfirmOpen(false);
    setBotToDelete(null);
    setIsBotListOpen(false);
    onEditingBotSettings(false);
  };

  const changeView = (nextView: ServiceView) => {
    setBotSettingsLoaded(false);
    setIsBotSettingsLoading(nextView.mode === "edit");
    setHasDraft(false);
    setActiveTabIndex(0);
    setIsBotListOpen(false);
    setView(nextView);
  };

  const startCreating = () => {
    changeView({ mode: "create", returnTo: selectedBot });
  };

  const cancelEditing = () => {
    if (view.mode === "create" && view.returnTo) {
      changeView(serviceView(view.returnTo));
    } else {
      close();
    }
  };

  const managedState = selectedBot
    ? settings.managed || selectedBotModel?.managed || null
    : null;
  const isManaged = !!managedState;
  const fieldHint = (hintKey: string) =>
    isManaged ? t("botSettings.managedFieldHint") : t(hintKey);
  const adminSyncEnabled = selectedBotModel?.admin_sync_enabled ?? true;

  const setAdminSync = (enabled: boolean) => {
    if (!selectedBot || !botSettingsLoaded) return;
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

  const mergeWithDefaults = (current: BotSettings): BotSettings => {
    return {
      sub_support_url:
        current.sub_support_url.trim() || defaultSettings.sub_support_url,
      sub_profile_title:
        current.sub_profile_title.trim() || defaultSettings.sub_profile_title,
      sub_profile_url:
        current.sub_profile_url.trim() || defaultSettings.sub_profile_url,
      sub_subscription_domain:
        (current.sub_subscription_domain || "").trim() ||
        defaultSettings.sub_subscription_domain,
      bot_url: current.bot_url.trim() || defaultSettings.bot_url,
      web_url: current.web_url.trim() || defaultSettings.web_url,
      bs_extra_reset_pool_on_prolong: current.bs_extra_reset_pool_on_prolong,
      show_ads: current.show_ads,
    };
  };

  const save = () => {
    if (!selectedBot || !botSettingsLoaded) return;
    const normalizedUsername = botUsername.trim().replace(/^@/, "");
    if (!normalizedUsername) return;
    const normalizedTitle = botTitle.trim();
    const isIdentityChanged =
      !isManaged &&
      (normalizedUsername !== selectedBot ||
        normalizedTitle !== (selectedBotModel?.title || ""));
    const {
      managed: _managed,
      updated_at: _updatedAt,
      ...editableSettings
    } = settings;
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
          setView(serviceView(targetUsername));
        });
      })
      .then(() => {
        localStorage.removeItem(getDraftKey(targetUsername));
        if (targetUsername !== selectedBot) {
          localStorage.removeItem(getDraftKey(selectedBot));
        }
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
    if (!isCreatingBot || isInitialLoading || creating || !botUsername.trim())
      return;
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
          changeView(serviceView(bot.username));
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
      .catch(() => {
        toast({
          title: t("core.generalErrorMessage"),
          status: "error",
          isClosable: true,
        });
      })
      .finally(() => setCreating(false));
  };

  const requestCreateBot = () => {
    if (!isCreatingBot || isInitialLoading || creating || !botUsername.trim())
      return;
    if (bots.length === 0) {
      setIsFirstServiceConfirmOpen(true);
      return;
    }
    createBot();
  };

  const deleteBot = () => {
    if (!botToDelete || deleting) return;

    setDeleting(true);
    const deletedKey = getDraftKey(botToDelete.username);
    fetch(`/bots/${encodeURIComponent(botToDelete.username)}`, {
      method: "DELETE",
    })
      .then(() => {
        setBotToDelete(null);
        localStorage.removeItem(deletedKey);
        setHasDraft(false);
        return fetchBots();
      })
      .then((loadedBots) => {
        changeView(serviceView());
        if (!loadedBots) return;

        toast({
          title: t("botSettings.deleted"),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .catch(() => {
        toast({
          title: t("botSettings.deleteError"),
          status: "error",
          isClosable: true,
        });
      })
      .finally(() => setDeleting(false));
  };

  return (
    <Modal
      isOpen={isEditingBotSettings}
      onClose={close}
      initialFocusRef={closeButtonRef}
      closeOnEsc={!isMutating}
      closeOnOverlayClick={!isMutating}
      size={{ base: "full", md: "4xl" }}
      scrollBehavior="inside"
    >
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent
        minH={{ base: "100dvh", md: 0 }}
        maxH={{ base: "100dvh", md: "90vh" }}
        display="flex"
        flexDirection="column"
      >
        <ModalHeader px={6} pr={{ base: 6, md: 16 }} pt={5} pb={4}>
          <Stack
            direction={{ base: "column", md: "row" }}
            align={{ base: "stretch", md: "center" }}
            justify="space-between"
            spacing={3}
          >
            <Text fontSize="lg" fontWeight="semibold" pr={{ base: 12, md: 0 }}>
              {t(
                isCreatingBot ? "botSettings.createTitle" : "botSettings.title"
              )}
            </Text>
            <HStack w={{ base: "full", md: "auto" }} minW={0} spacing={2}>
              <Popover
                placement="bottom-start"
                isOpen={isBotListOpen}
                initialFocusRef={botSearchRef}
                onClose={() => setIsBotListOpen(false)}
              >
                <PopoverTrigger>
                  <Button
                    h="44px"
                    flex={{ base: 1, md: "0 1 auto" }}
                    w={{ md: "270px" }}
                    minW={0}
                    fontSize="sm"
                    gap={2}
                    justifyContent="space-between"
                    isDisabled={isInitialLoading || !bots.length || isMutating}
                    onClick={() => {
                      setBotSearch("");
                      setIsBotListOpen(true);
                    }}
                  >
                    <Text
                      isTruncated
                      title={selectedBot ? `@${selectedBot}` : undefined}
                    >
                      {selectedBot
                        ? `@${selectedBot}`
                        : t("botSettings.newService")}
                    </Text>

                    <ChevronDownIcon
                      width={14}
                      height={14}
                      color="currentColor"
                      style={{
                        flexShrink: 0,
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
                  w="min(280px, calc(100vw - 32px))"
                  maxH="280px"
                  overflow="hidden"
                  fontSize="sm"
                >
                  <PopoverBody
                    p={2}
                    display="flex"
                    flexDirection="column"
                    minH={0}
                  >
                    <InputGroup size="sm" mb={2}>
                      <InputLeftElement pointerEvents="none">
                        <MagnifyingGlassIcon color="gray.400" width="16px" />
                      </InputLeftElement>
                      <Input
                        ref={botSearchRef}
                        size="sm"
                        fontSize="sm"
                        height="32px"
                        px={2}
                        placeholder={t("botSettings.botSearchPlaceholder")}
                        aria-label={t("botSettings.botSearchPlaceholder")}
                        value={botSearch}
                        onChange={(e) => setBotSearch(e.target.value)}
                      />
                    </InputGroup>

                    <VStack
                      align="stretch"
                      minH={0}
                      maxH="224px"
                      overflowY="auto"
                      spacing={1}
                    >
                      {!matchingBots.length && (
                        <Text px={2} py={1} fontWeight="normal">
                          {t("botSettings.noBotsFound")}
                        </Text>
                      )}
                      {matchingBots.map((bot) => (
                        <Button
                          key={bot.id}
                          variant="ghost"
                          justifyContent="flex-start"
                          minH="44px"
                          flexShrink={0}
                          fontSize="sm"
                          fontWeight="normal"
                          aria-pressed={selectedBot === bot.username}
                          px={2}
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
                          _hover={{
                            bg: "gray.100",
                            _dark: { bg: "gray.700" },
                          }}
                          onClick={() => {
                            if (selectedBot === bot.username) {
                              setIsBotListOpen(false);
                            } else {
                              changeView(serviceView(bot.username));
                            }
                          }}
                        >
                          <Text
                            minW={0}
                            isTruncated
                            title={bot.title || bot.username}
                          >
                            @{bot.username}
                            {bot.title && ` — ${bot.title}`}
                          </Text>
                        </Button>
                      ))}
                    </VStack>
                  </PopoverBody>
                </PopoverContent>
              </Popover>
              <Tooltip
                label={t("botSettings.createBot")}
                hasArrow
                shouldWrapChildren
              >
                <IconButton
                  aria-label={t("botSettings.createBot")}
                  icon={<PlusIcon width={20} height={20} />}
                  boxSize="44px"
                  borderRadius="md"
                  variant="ghost"
                  colorScheme="green"
                  color="green.700"
                  bg="green.50"
                  _hover={{ bg: "green.100" }}
                  _active={{ bg: "green.200" }}
                  _disabled={{ opacity: 0.55, cursor: "not-allowed" }}
                  _dark={{
                    color: "green.300",
                    bg: "green.900",
                    _hover: { bg: "green.800" },
                    _active: { bg: "green.700" },
                  }}
                  isDisabled={isCreatingBot || isInitialLoading || isMutating}
                  onClick={startCreating}
                />
              </Tooltip>
              {selectedBotModel && (
                <Menu placement="bottom-end" autoSelect={false}>
                  <MenuButton
                    as={IconButton}
                    aria-label={t("botSettings.serviceActions")}
                    icon={<EllipsisHorizontalIcon width={20} height={20} />}
                    boxSize="44px"
                    borderRadius="md"
                    flexShrink={0}
                    isDisabled={isMutating}
                  />
                  <MenuList minW="max-content" py={1}>
                    <MenuItem
                      px={3}
                      py={1.5}
                      fontSize="sm"
                      fontWeight="normal"
                      color="red.600"
                      bg="transparent"
                      border="0"
                      boxShadow="none"
                      _hover={{ bg: "gray.100" }}
                      _focus={{ bg: "transparent", boxShadow: "none" }}
                      _focusVisible={{ bg: "gray.100" }}
                      _dark={{
                        color: "red.300",
                        _hover: { bg: "whiteAlpha.100" },
                        _focusVisible: { bg: "whiteAlpha.100" },
                      }}
                      icon={<TrashIcon width={16} height={16} />}
                      onClick={() => setBotToDelete(selectedBotModel)}
                    >
                      {t("botSettings.deleteBot")}
                    </MenuItem>
                  </MenuList>
                </Menu>
              )}
            </HStack>
          </Stack>
        </ModalHeader>
        <ModalCloseButton
          ref={closeButtonRef}
          boxSize="44px"
          isDisabled={isMutating}
        />
        <ModalBody
          flex="1"
          minH={0}
          overflowX="hidden"
          style={{
            scrollbarGutter: "stable",
          }}
          sx={{
            ".chakra-form__helper-text": {
              color: "gray.600",
              _dark: { color: "gray.300" },
            },
          }}
        >
          {isInitialLoading || isBotSettingsLoading ? (
            <VStack justify="center" minH="240px" role="status">
              <Spinner />
            </VStack>
          ) : selectedBot && !botSettingsLoaded ? (
            <Alert status="error" borderRadius="md">
              <AlertIcon />
              <AlertDescription>
                {t("core.generalErrorMessage")}
              </AlertDescription>
            </Alert>
          ) : (
            <Box as="fieldset" disabled={isMutating} minW={0}>
              <Tabs
                variant="enclosed"
                colorScheme="primary"
                index={activeTabIndex}
                onChange={setActiveTabIndex}
                isLazy
                lazyBehavior="keepMounted"
              >
                <TabList
                  overflowX="auto"
                  overflowY="hidden"
                  whiteSpace="nowrap"
                >
                  <Tab>{t("botSettings.tabBotInfo")}</Tab>
                  <Tab>{t("botSettings.tabSubscription")}</Tab>
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
                    flexWrap="wrap"
                  >
                    <Text
                      fontSize="sm"
                      color="yellow.800"
                      _dark={{ color: "yellow.200" }}
                    >
                      {t("botSettings.draftFound")}
                    </Text>
                    <HStack>
                      <Button
                        size="xs"
                        colorScheme="yellow"
                        onClick={restoreDraft}
                      >
                        {t("botSettings.draftRestore")}
                      </Button>
                      <Button size="xs" variant="ghost" onClick={discardDraft}>
                        {t("botSettings.draftDiscard")}
                      </Button>
                    </HStack>
                  </HStack>
                )}
                <VStack mt={3} spacing={3} align="stretch">
                  <ServiceSettingSwitch
                    label={t("botSettings.adminSync")}
                    description={t(
                      selectedBot
                        ? "botSettings.adminSyncHint"
                        : "botSettings.adminSyncNewBotHint"
                    )}
                    checked={selectedBot ? adminSyncEnabled : true}
                    disabled={!selectedBot || syncingAdmin}
                    onChange={setAdminSync}
                  />
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
                <TabPanels pt={2}>
                  {/* Вкладка 1: Bot Info */}
                  <TabPanel px={0}>
                    <VStack spacing={4} align="stretch">
                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl isDisabled={isManaged}>
                          <FormLabel>
                            {t("botSettings.newBotUsername")}
                          </FormLabel>
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

                      <ServiceSettingSwitch
                        label={t("botSettings.showAds")}
                        description={fieldHint("botSettings.showAdsHint")}
                        checked={settings.show_ads}
                        disabled={isManaged}
                        onChange={(showAds) =>
                          updateSettings({ show_ads: showAds })
                        }
                      />
                    </VStack>
                  </TabPanel>

                  {/* Вкладка 2: Subscription Settings */}
                  <TabPanel px={0}>
                    <VStack spacing={4} align="stretch">
                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl isDisabled={isManaged}>
                          <FormLabel>
                            {t("botSettings.subSupportUrl")}
                          </FormLabel>
                          <Input
                            value={settings.sub_support_url}
                            placeholder="https://t.me/support"
                            onChange={(e) =>
                              updateSettings({
                                sub_support_url: e.target.value,
                              })
                            }
                          />
                          <FormHelperText>
                            {isManaged
                              ? t("botSettings.managedFieldHint")
                              : t("botSettings.subSupportUrlHint")}
                          </FormHelperText>
                        </FormControl>
                        <FormControl>
                          <FormLabel>
                            {t("botSettings.subProfileTitle")}
                          </FormLabel>
                          <Input
                            value={settings.sub_profile_title}
                            placeholder="My VPN"
                            onChange={(e) =>
                              updateSettings({
                                sub_profile_title: e.target.value,
                              })
                            }
                          />
                          <FormHelperText>
                            {t("botSettings.subProfileTitleHint")}
                          </FormHelperText>
                        </FormControl>
                      </SimpleGrid>

                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                        <FormControl isDisabled={isManaged}>
                          <FormLabel>
                            {t("botSettings.subProfileUrl")}
                          </FormLabel>
                          <Input
                            value={settings.sub_profile_url}
                            placeholder="https://example.com/profile"
                            onChange={(e) =>
                              updateSettings({
                                sub_profile_url: e.target.value,
                              })
                            }
                          />
                          <FormHelperText>
                            {fieldHint("botSettings.subProfileUrlHint")}
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

                      <Box
                        border="1px solid"
                        borderColor="inherit"
                        borderRadius="md"
                        p={4}
                      >
                        <FormControl isDisabled={isManaged}>
                          <FormLabel>
                            {t("botSettings.bsExtraResetPoolOnProlong")}
                          </FormLabel>
                          <Switch
                            colorScheme="primary"
                            isChecked={settings.bs_extra_reset_pool_on_prolong}
                            onChange={(e) =>
                              updateSettings({
                                bs_extra_reset_pool_on_prolong:
                                  e.target.checked,
                              })
                            }
                          />
                          <FormHelperText>
                            {fieldHint(
                              "botSettings.bsExtraResetPoolOnProlongHint"
                            )}
                          </FormHelperText>
                        </FormControl>
                      </Box>
                    </VStack>
                  </TabPanel>
                </TabPanels>
              </Tabs>
            </Box>
          )}
        </ModalBody>

        <ModalFooter flexShrink={0} borderTopWidth="1px" bg="inherit">
          <HStack spacing={2} w={{ base: "full", md: "auto" }}>
            <Button
              flexGrow={{ base: 1, md: 0 }}
              w="auto"
              px={5}
              whiteSpace="nowrap"
              minH="44px"
              variant="ghost"
              onClick={cancelEditing}
              isDisabled={isMutating}
            >
              {t("cancel")}
            </Button>

            <Button
              flexGrow={{ base: 1, md: 0 }}
              w="auto"
              px={5}
              whiteSpace="nowrap"
              minH="44px"
              colorScheme="primary"
              _disabled={{
                opacity: 1,
                cursor: "not-allowed",
                color: "gray.600",
                bg: "gray.100",
                _dark: { color: "gray.300", bg: "gray.700" },
              }}
              onClick={isCreatingBot ? requestCreateBot : save}
              isLoading={isCreatingBot ? creating : saving}
              isDisabled={
                isMutating ||
                isInitialLoading ||
                (!isCreatingBot && !botSettingsLoaded) ||
                !botUsername.trim()
              }
            >
              {t(isCreatingBot ? "botSettings.submitCreate" : "core.save")}
            </Button>
          </HStack>
        </ModalFooter>
      </ModalContent>
      <AlertDialog
        isOpen={isFirstServiceConfirmOpen}
        leastDestructiveRef={cancelFirstServiceRef}
        onClose={() => setIsFirstServiceConfirmOpen(false)}
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader>
              {t("botSettings.firstServiceConfirmTitle")}
            </AlertDialogHeader>
            <AlertDialogBody>
              {t("botSettings.firstServiceConfirmBody")}
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button
                ref={cancelFirstServiceRef}
                onClick={() => setIsFirstServiceConfirmOpen(false)}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="primary"
                ml={3}
                onClick={() => {
                  setIsFirstServiceConfirmOpen(false);
                  createBot();
                }}
              >
                {t("botSettings.submitCreate")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
      <AlertDialog
        isOpen={!!botToDelete}
        leastDestructiveRef={cancelDeleteRef}
        onClose={() => setBotToDelete(null)}
        closeOnEsc={!deleting}
        closeOnOverlayClick={!deleting}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader>{t("botSettings.deleteBot")}</AlertDialogHeader>
            <AlertDialogBody>
              {botToDelete &&
                t("botSettings.deleteConfirm", {
                  username: botToDelete.title
                    ? `${botToDelete.title} (@${botToDelete.username})`
                    : `@${botToDelete.username}`,
                })}
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button
                ref={cancelDeleteRef}
                onClick={() => setBotToDelete(null)}
                isDisabled={deleting}
              >
                {t("cancel")}
              </Button>
              <Button
                colorScheme="red"
                ml={3}
                onClick={deleteBot}
                isLoading={deleting}
              >
                {t("delete")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Modal>
  );
};

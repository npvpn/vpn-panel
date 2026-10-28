import {
  Box,
  FormControl,
  Text,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverTrigger,
  Portal,
  SimpleGrid,
  HStack,
  VStack,
  Badge,
  Button,
  Checkbox,
  FormLabel,
  Input,
  InputGroup,
  InputLeftElement,
  InputRightElement,
  IconButton,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
} from "@chakra-ui/react";
import {
  ChevronDownIcon,
  MagnifyingGlassIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import { NodeType } from "contexts/NodesContext";
import { ChangeEvent, memo, useEffect, useState } from "react";
import {
  Control,
  Controller,
  UseFormRegister,
  get,
  useFormContext,
  useFormState,
  useWatch,
} from "react-hook-form";
import { XrayTemplateDocument, listTemplates } from "service/xrayTemplates";
import { Bot } from "types/Bot";
import { InfoIcon, PencilIcon, Error, Select } from "./constants";
import { Trans } from "react-i18next";
import { HostInjectionOptions } from "./HostInjectionOptions";
import { templateInjection } from "./hostInjection";
import { HostBalancingOptions } from "./HostBalancingOptions";
import { RHFInput } from "./RHFInput";
import { RHFCheckbox } from "./RHFCheckbox";
import { RHFSelect } from "./RHFSelect";
import { XhttpExtraModal } from "./XhttpExtraModal";
import { HostInfoPopover } from "./HostInfoPopover";
import { selectAllBots, withoutUnboundRentals } from "./botBindings";
import { thinScrollbarSx } from "utils/thinScrollbar";

// NPVPN-2302: вкладки окна и поля хоста на каждой — по ним вкладка с ошибкой
// получает точку. Remark и Address — на «Подключении»
const HOST_TABS: { labelKey: string; fields: string[] }[] = [
  {
    labelKey: "hostsDialog.tabs.connection",
    fields: [
      "port",
      "sni",
      "host",
      "path",
      "security",
      "alpn",
      "fingerprint",
      "use_sni_as_host",
      "allowinsecure",
      "remark",
      "address",
    ],
  },
  {
    labelKey: "hostsDialog.tabs.transport",
    fields: [
      "fragment_setting",
      "noise_setting",
      "xhttp_extra",
      "mux_enable",
      "random_user_agent",
    ],
  },
  {
    labelKey: "hostsDialog.tabs.access",
    fields: [
      "bot_usernames",
      "rented_bot_usernames",
      "node_ids",
      "address_subset_enabled",
      "address_subset_size",
      "address_rotation_days",
    ],
  },
  {
    labelKey: "hostsDialog.tabs.composition",
    fields: [
      "client_config_id",
      "template_injection",
      "host_injection",
      "group_tag",
      "is_hidden",
      "balancing",
      "balancer_nodes_source",
      "balancer_node_ids",
    ],
  },
];

export type HostAdvancedOptionsProps = {
  hostKey: string;
  index: number;
  inbound: any;
  register: UseFormRegister<any>;
  control: Control<any>;
  accordionErrors: any;
  t: any;
  bots: Bot[];
  nodes: NodeType[];
  proxyHostSecurity: any[];
  proxyALPN: any[];
  proxyFingerprint: any[];
  // Remark/address are already editable inline wherever this modal is opened
  // from a mobile card or the create-host row, so skip the duplicates there.
  hideRemarkAddress?: boolean;
  completeCatalog?: boolean;
};

export const HostAdvancedOptions = memo(
  ({
    hostKey,
    index,
    inbound,
    register,
    control,
    accordionErrors,
    t,
    bots,
    nodes,
    proxyHostSecurity,
    proxyALPN,
    proxyFingerprint,
    hideRemarkAddress,
    completeCatalog,
  }: HostAdvancedOptionsProps) => {
    const portPlaceholder = inbound?.port ?? "8080";
    const [isXhttpExtraOpen, setIsXhttpExtraOpen] = useState(false);
    const [botSearch, setBotSearch] = useState("");
    const form = useFormContext();
    const currentHost = useWatch({ control, name: `${hostKey}.${index}` }) || {};
    const effectiveInjection = currentHost.host_injection ?? currentHost.template_injection;
    const composite = !!effectiveInjection?.enabled;
    const [templatesLoaded, setTemplatesLoaded] = useState(false);
    const [tabIndex, setTabIndex] = useState(0);
    // ошибки берём из формы, а не из пропса: при сохранении счётчик отправок
    // и ошибки приходят в одном обновлении
    const { errors, submitCount } = useFormState({ control });
    const hostErrors = get(errors, `${hostKey}.${index}`);
    const tabHasErrors = HOST_TABS.map((tab) =>
      tab.fields.some((field) => !!hostErrors?.[field])
    );

    // Сохранение с ошибками открывает вкладку с первой из них, если на
    // текущей ошибок нет. Только по попытке сохранить: пока правишь поля,
    // вкладки сами не переключаются
    useEffect(() => {
      if (!submitCount || tabHasErrors[tabIndex]) return;
      const firstWithErrors = tabHasErrors.indexOf(true);
      if (firstWithErrors !== -1) setTabIndex(firstWithErrors);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [submitCount]);
    const [templateError, setTemplateError] = useState(false);

    // Новый список ботов хоста; снятые боты теряют и аренду — см.
    // withoutUnboundRentals.
    const setHostBots = (
      onChange: (value: string[]) => void,
      next: string[]
    ) => {
      onChange(next);

      const rentedPath = `${hostKey}.${index}.rented_bot_usernames`;
      const rented: string[] = form.getValues(rentedPath) || [];
      const kept = withoutUnboundRentals(rented, next);
      if (kept.length !== rented.length) {
        form.setValue(rentedPath, kept, { shouldDirty: true });
      }
    };
    const [nodeSearch, setNodeSearch] = useState("");
    const [clientConfigs, setClientConfigs] = useState<XrayTemplateDocument[]>(
      []
    );

    useEffect(() => {
      // Видов документов больше нет (NPVPN-2024): каждый документ — полный
      // самодостаточный конфиг и может быть назначен хосту.
      listTemplates()
        .then((docs) => { setClientConfigs(docs); setTemplatesLoaded(true); })
        .catch(() => setClientConfigs([]));
    }, []);

    useEffect(() => {
      if (!templatesLoaded) return;
      try {
        form.setValue(`${hostKey}.${index}.template_injection`, templateInjection(currentHost, clientConfigs));
        setTemplateError(false);
      } catch { setTemplateError(true); }
    }, [templatesLoaded, clientConfigs, currentHost.client_config_id, hostKey, index]);

    return (
      <VStack key={index} align="stretch" spacing={3} w="full">
        {/* NPVPN-2302: поля сгруппированы по смыслу во вкладках */}
        <Tabs
          variant="enclosed"
          colorScheme="primary"
          index={tabIndex}
          onChange={setTabIndex}
        >
          <TabList
            overflowX="auto"
            overflowY="hidden"
            whiteSpace="nowrap"
            // на телефоне компактнее: все четыре вкладки ближе к ширине экрана,
            // остальное прокручивается вбок
            sx={{
              "& > button": {
                px: { base: 2, md: 4 },
                fontSize: { base: "sm", md: "md" },
              },
            }}
          >
            {HOST_TABS.map((tab, i) => (
              <Tab key={tab.labelKey} flexShrink={0}>
                {t(tab.labelKey)}
                {tabHasErrors[i] && (
                  <Box
                    as="span"
                    ml={1.5}
                    w="6px"
                    h="6px"
                    borderRadius="full"
                    bg="red.500"
                    display="inline-block"
                    aria-label={t("hostsDialog.tabs.hasErrors")}
                  />
                )}
              </Tab>
            ))}
          </TabList>
          {/* панели не размонтируются при переключении (isLazy выключен) —
              значения скрытых полей остаются в форме */}
          <TabPanels>
            <TabPanel px={0}>
              <SimpleGrid
                  columns={{ base: 1, md: 2 }}
                  spacingX={3}
                  spacingY={3}
                  w="full"
                >
                {/* Remark и Address — в начале «Подключения»; какой хост открыт,
                    видно в заголовке окна */}
                {!hideRemarkAddress && (
                  <>
                    <RHFInput
                      label={t("hostsDialog.remark")}
                      registerProps={register(`${hostKey}.${index}.remark`)}
                      error={accordionErrors?.remark}
                      rightElement={<HostInfoPopover t={t} />}
                      formControlProps={{
                        gridColumn: { md: "1 / -1" },
                        position: "relative",
                        zIndex: 10,
                      }}
                      inputProps={{
                        size: "sm",
                        borderRadius: "4px",
                      }}
                      formLabelProps={{
                        pb: 1,
                        m: 0,
                        alignItems: "center",
                        gap: 1,
                      }}
                    />

                    <RHFInput
                      label={t("hostsDialog.address")}
                      registerProps={register(`${hostKey}.${index}.address`)}
                      error={accordionErrors?.address}
                      placeholder="{SERVER_IP}"
                      rightElement={<HostInfoPopover t={t} />}
                      formControlProps={{
                        gridColumn: { md: "1 / -1" },
                      }}
                      inputProps={{
                        size: "sm",
                        borderRadius: "4px",
                      }}
                      formLabelProps={{
                        pb: 1,
                        m: 0,
                        alignItems: "center",
                        gap: 1,
                      }}
                    />
                  </>
                )}
                <RHFInput
                  label={t("hostsDialog.port")}
                  registerProps={register(`${hostKey}.${index}.port`)}
                  error={accordionErrors?.port}
                  placeholder={String(portPlaceholder)}
                  type="number"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.port.info")}
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                <RHFInput
                  label={t("hostsDialog.sni")}
                  registerProps={register(`${hostKey}.${index}.sni`)}
                  error={accordionErrors?.sni}
                  placeholder="SNI (e.g. example.com)"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.sni.info")}
                          </Text>
                          <Text fontSize="xs" mt="2">
                            <Trans
                              i18nKey="hostsDialog.host.wildcard"
                              components={{
                                badge: <Badge />,
                              }}
                            />
                          </Text>
                          <Text fontSize="xs">
                            <Trans
                              i18nKey="hostsDialog.host.multiHost"
                              components={{
                                badge: <Badge />,
                              }}
                            />
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                <RHFInput
                  label={t("hostsDialog.host")}
                  registerProps={register(`${hostKey}.${index}.host`)}
                  error={accordionErrors?.host}
                  placeholder="Host (e.g. example.com)"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.host.info")}
                          </Text>
                          <Text fontSize="xs" mt="2">
                            <Trans
                              i18nKey="hostsDialog.host.wildcard"
                              components={{
                                badge: <Badge />,
                              }}
                            />
                          </Text>
                          <Text fontSize="xs">
                            <Trans
                              i18nKey="hostsDialog.host.multiHost"
                              components={{
                                badge: <Badge />,
                              }}
                            />
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                <RHFInput
                  label={t("hostsDialog.path")}
                  registerProps={register(`${hostKey}.${index}.path`)}
                  error={accordionErrors?.path}
                  placeholder="path (e.g. /vless)"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.path.info")}
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                <RHFSelect
                  label={t("hostsDialog.security")}
                  registerProps={register(`${hostKey}.${index}.security`)}
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.security.info")}
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  formControlProps={{
                    height: "66px",
                  }}
                  selectProps={{
                    size: "sm",
                  }}
                >
                  {proxyHostSecurity.map((s) => {
                    return (
                      <option key={s.value} value={s.value}>
                        {s.title}
                      </option>
                    );
                  })}
                </RHFSelect>

                <RHFSelect
                  label={t("hostsDialog.alpn")}
                  registerProps={register(`${hostKey}.${index}.alpn`)}
                  formControlProps={{
                    height: "66px",
                  }}
                  selectProps={{
                    size: "sm",
                  }}
                >
                  {proxyALPN.map((s) => {
                    return (
                      <option key={s.value} value={s.value}>
                        {s.title}
                      </option>
                    );
                  })}
                </RHFSelect>

                <RHFSelect
                  label={t("hostsDialog.fingerprint")}
                  registerProps={register(`${hostKey}.${index}.fingerprint`)}
                  formControlProps={{
                    height: "66px",
                    gridColumn: { md: "1 / -1" },
                  }}
                  selectProps={{
                    size: "sm",
                  }}
                >
                  {proxyFingerprint.map((s) => {
                    return (
                      <option key={s.value} value={s.value}>
                        {s.title}
                      </option>
                    );
                  })}
                </RHFSelect>

                <RHFCheckbox
                  label={t("hostsDialog.useSniAsHost")}
                  registerProps={register(`${hostKey}.${index}.use_sni_as_host`)}
                  error={accordionErrors?.use_sni_as_host}
                />

                <RHFCheckbox
                  label={t("hostsDialog.allowinsecure")}
                  registerProps={register(`${hostKey}.${index}.allowinsecure`)}
                  error={accordionErrors?.allowinsecure}
                />
              </SimpleGrid>
            </TabPanel>
            <TabPanel px={0}>
              <SimpleGrid
                  columns={{ base: 1, md: 2 }}
                  spacingX={3}
                  spacingY={3}
                  w="full"
                >
                <RHFInput
                  label={t("hostsDialog.fragment")}
                  registerProps={register(`${hostKey}.${index}.fragment_setting`)}
                  error={accordionErrors?.fragment_setting}
                  placeholder="10-100,100-200,tlshello"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.fragment.info")}
                          </Text>
                          <Text fontSize="xs" pr={5} pt={2} pb={1}>
                            {t("hostsDialog.fragment.info.examples")}
                          </Text>
                          <Text fontSize="xs" pr={5}>
                            100-200,10-20,tlshello
                          </Text>
                          <Text fontSize="xs" pr={5}>
                            100-200,10-20,1-3
                          </Text>
                          <Text fontSize="xs" pr={5} pt="3">
                            {t("hostsDialog.fragment.info.attention")}
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                <RHFInput
                  label={t("hostsDialog.noise")}
                  registerProps={register(`${hostKey}.${index}.noise_setting`)}
                  error={accordionErrors?.noise_setting}
                  placeholder="rand:10-20,100-200"
                  rightElement={
                    <Popover isLazy placement="right">
                      <PopoverTrigger>
                        <InfoIcon />
                      </PopoverTrigger>
                      <Portal>
                        <PopoverContent p={2}>
                          <PopoverArrow />
                          <PopoverCloseButton />
                          <Text fontSize="xs" pr={5}>
                            {t("hostsDialog.noise.info")}
                          </Text>
                          <Text fontSize="xs" pr={5} pt={2} pb={1}>
                            {t("hostsDialog.noise.info.examples")}
                          </Text>
                          <Text fontSize="xs" pr={5}>
                            rand:10-20,10-20
                          </Text>
                          <Text fontSize="xs" pr={5}>
                            rand:10-20,10-20&base64:7nQBAAABAAAAAAAABnQtcmluZwZtc2VkZ2UDbmV0AAABAAE=,10-25
                          </Text>
                          <Text fontSize="xs" pr={5} pt="3">
                            {t("hostsDialog.noise.info.attention")}
                          </Text>
                        </PopoverContent>
                      </Portal>
                    </Popover>
                  }
                  inputProps={{
                    size: "sm",
                    borderRadius: "4px",
                  }}
                  formLabelProps={{
                    pb: 1,
                    m: 0,
                    alignItems: "center",
                    gap: 1,
                  }}
                />

                {["splithttp", "xhttp"].includes(inbound?.network) && (
                  <FormControl
                    isInvalid={!!accordionErrors?.xhttp_extra}
                    gridColumn={{ md: "1 / -1" }}
                  >
                    <FormLabel>{t("hostsDialog.xhttpExtra")}</FormLabel>
                    <Controller
                      control={control}
                      name={`${hostKey}.${index}.xhttp_extra`}
                      render={({ field }) => {
                        const preview = (() => {
                          if (!field.value) return null;
                          try {
                            return JSON.stringify(JSON.parse(field.value));
                          } catch {
                            return field.value;
                          }
                        })();

                        return (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            w="full"
                            justifyContent="space-between"
                            onClick={() => setIsXhttpExtraOpen(true)}
                          >
                            <Text
                              as="span"
                              noOfLines={1}
                              fontFamily={preview ? "mono" : "body"}
                              fontSize={preview ? "xs" : "sm"}
                            >
                              {preview || t("hostsDialog.xhttpExtra.edit")}
                            </Text>
                            <PencilIcon />
                          </Button>

                          <XhttpExtraModal
                            isOpen={isXhttpExtraOpen}
                            onClose={() => setIsXhttpExtraOpen(false)}
                            value={field.value}
                            onChange={field.onChange}
                            error={
                              accordionErrors?.xhttp_extra?.message &&
                              t(accordionErrors.xhttp_extra.message)
                            }
                            t={t}
                          />
                        </>
                        );
                      }}
                    />
                    {accordionErrors?.xhttp_extra && (
                      <Error>{t(accordionErrors.xhttp_extra.message)}</Error>
                    )}
                  </FormControl>
                )}

                <RHFCheckbox
                  label={t("hostsDialog.muxEnable")}
                  registerProps={register(`${hostKey}.${index}.mux_enable`)}
                  error={accordionErrors?.mux_enable}
                />

                <RHFCheckbox
                  label={t("hostsDialog.randomUserAgent")}
                  registerProps={register(`${hostKey}.${index}.random_user_agent`)}
                  error={accordionErrors?.random_user_agent}
                />
              </SimpleGrid>
            </TabPanel>
            <TabPanel px={0}>
              <SimpleGrid
                  columns={{ base: 1, md: 2 }}
                  spacingX={3}
                  spacingY={3}
                  w="full"
                >
                {bots.length > 0 && (
                  <FormControl
                    isInvalid={!!accordionErrors?.bot_usernames}
                    gridColumn={{ md: "1 / -1" }}
                  >
                    <FormLabel>{t("hostsDialog.availableBots")}</FormLabel>
                    <Text
                      fontSize="xs"
                      color="gray.600"
                      _dark={{ color: "gray.400" }}
                      mb={2}
                    >
                      {t("hostsDialog.availableBots.info")}
                    </Text>
                    <Controller
                      control={control}
                      name={`${hostKey}.${index}.bot_usernames`}
                      render={({ field }) => {
                        const selectedBotUsernames: string[] = Array.isArray(
                          field.value
                        )
                          ? field.value
                          : [];
                        const selectedBots = bots.filter((bot: Bot) =>
                          selectedBotUsernames.includes(bot.username)
                        );
                        const query = botSearch.trim().toLowerCase();
                        const filteredBots = query
                          ? bots.filter(
                              (bot: Bot) =>
                                bot.username.toLowerCase().includes(query) ||
                                (bot.title ?? "").toLowerCase().includes(query)
                            )
                          : bots;

                        return (
                          <Popover
                            placement="bottom-start"
                            onClose={() => setBotSearch("")}
                          >
                            <PopoverTrigger>
                              <Button
                                variant="outline"
                                size="sm"
                                w="full"
                                justifyContent="space-between"
                              >
                                <Text as="span" noOfLines={1}>
                                  {/* NPVPN-2044: пустая привязка — «никому», а не
                                      «всем»; «все» — это выбраны все боты. */}
                                  {selectedBots.length === 0
                                    ? t("hostsDialog.availableBots.nobody")
                                    : selectedBots.length === bots.length &&
                                      bots.length > 1
                                    ? t("hostsDialog.availableBots.all")
                                    : t("hostsDialog.availableBots.selected", {
                                        count: selectedBots.length,
                                      })}
                                </Text>
                                <ChevronDownIcon width="16px" />
                              </Button>
                            </PopoverTrigger>
                            <Portal>
                              <PopoverContent w="280px" zIndex={1500}>
                                <PopoverArrow />
                                <PopoverBody>
                                  <VStack align="start" spacing={2}>
                                    <InputGroup size="xs">
                                      <InputLeftElement pointerEvents="none">
                                        <MagnifyingGlassIcon width="14px" />
                                      </InputLeftElement>
                                      <Input
                                        placeholder={t("search")}
                                        value={botSearch}
                                        onChange={(
                                          event: ChangeEvent<HTMLInputElement>
                                        ) => setBotSearch(event.target.value)}
                                        borderRadius="4px"
                                        pl={7}
                                      />
                                      {botSearch.length > 0 && (
                                        <InputRightElement>
                                          <IconButton
                                            onClick={() => setBotSearch("")}
                                            aria-label="clear"
                                            size="xs"
                                            variant="ghost"
                                          >
                                            <XMarkIcon width="14px" />
                                          </IconButton>
                                        </InputRightElement>
                                      )}
                                    </InputGroup>
                                    <HStack spacing={1}>
                                      {/* NPVPN-2215: при поиске — только найденных. */}
                                      {filteredBots.some(
                                        (bot: Bot) =>
                                          !selectedBotUsernames.includes(bot.username)
                                      ) && (
                                        <Button
                                          variant="ghost"
                                          size="xs"
                                          onClick={() =>
                                            setHostBots(
                                              field.onChange,
                                              selectAllBots(
                                                selectedBotUsernames,
                                                filteredBots.map(
                                                  (bot: Bot) => bot.username
                                                )
                                              )
                                            )
                                          }
                                        >
                                          {t("hostsDialog.availableBots.selectAll")}
                                        </Button>
                                      )}
                                      {selectedBotUsernames.length > 0 && (
                                        <Button
                                          variant="ghost"
                                          size="xs"
                                          onClick={() => setHostBots(field.onChange, [])}
                                        >
                                          {t("hostsDialog.availableBots.clear")}
                                        </Button>
                                      )}
                                    </HStack>
                                    <VStack
                                      align="start"
                                      spacing={2}
                                      maxH="240px"
                                      overflowY="auto"
                                      sx={thinScrollbarSx}
                                      w="full"
                                    >
                                      {filteredBots.map((bot: Bot) => (
                                        <Checkbox
                                          key={bot.username}
                                          isChecked={selectedBotUsernames.includes(
                                            bot.username
                                          )}
                                          onChange={(
                                            event: ChangeEvent<HTMLInputElement>
                                          ) => {
                                            if (event.target.checked) {
                                              field.onChange([
                                                ...selectedBotUsernames,
                                                bot.username,
                                              ]);
                                            } else {
                                              setHostBots(
                                                field.onChange,
                                                selectedBotUsernames.filter(
                                                  (username: string) =>
                                                    username !== bot.username
                                                )
                                              );
                                            }
                                          }}
                                        >
                                          <Text as="span" fontSize="sm">
                                            @{bot.username}
                                            {bot.title ? ` (${bot.title})` : ""}
                                          </Text>
                                        </Checkbox>
                                      ))}
                                      {filteredBots.length === 0 && (
                                        <Text fontSize="sm" color="gray.500">
                                          {t("hostsDialog.availableBots.notFound")}
                                        </Text>
                                      )}
                                    </VStack>
                                  </VStack>
                                </PopoverBody>
                              </PopoverContent>
                            </Portal>
                          </Popover>
                        );
                      }}
                    />
                    {accordionErrors?.bot_usernames && (
                      <Error>{t(accordionErrors.bot_usernames.message)}</Error>
                    )}
                  </FormControl>
                )}
                {nodes.filter((n) => n.id != null).length > 0 && (
                  <FormControl gridColumn={{ md: "1 / -1" }}>
                    <FormLabel>{t("hostsDialog.linkedNodes")}</FormLabel>
                    <Text
                      fontSize="xs"
                      color="gray.600"
                      _dark={{ color: "gray.400" }}
                      mb={2}
                    >
                      {t("hostsDialog.linkedNodes.info")}
                    </Text>
                    <Controller
                      control={control}
                      name={`${hostKey}.${index}.node_ids`}
                      render={({ field }) => {
                        const selectedIds: number[] = Array.isArray(field.value)
                          ? field.value
                          : [];
                        const availableNodes = nodes.filter((n) => n.id != null);
                        const query = nodeSearch.trim().toLowerCase();
                        const filteredNodes = query
                          ? availableNodes.filter((node: NodeType) =>
                              node.name.toLowerCase().includes(query)
                            )
                          : availableNodes;

                        return (
                          <Popover
                            isLazy
                            placement="bottom-start"
                            onClose={() => setNodeSearch("")}
                          >
                            <PopoverTrigger>
                              <Button
                                variant="outline"
                                size="sm"
                                w="full"
                                justifyContent="space-between"
                              >
                                <Text as="span" noOfLines={1}>
                                  {selectedIds.length
                                    ? t("hostsDialog.linkedNodes.selected", {
                                        count: selectedIds.length,
                                      })
                                    : t("hostsDialog.linkedNodes.none")}
                                </Text>
                                <ChevronDownIcon width="16px" />
                              </Button>
                            </PopoverTrigger>
                            <Portal>
                              <PopoverContent w="280px" zIndex={1500}>
                                <PopoverArrow />
                                <PopoverBody>
                                  <VStack align="start" spacing={2}>
                                    <InputGroup size="xs">
                                      <InputLeftElement pointerEvents="none">
                                        <MagnifyingGlassIcon width="14px" />
                                      </InputLeftElement>
                                      <Input
                                        placeholder={t("search")}
                                        value={nodeSearch}
                                        onChange={(
                                          event: ChangeEvent<HTMLInputElement>
                                        ) => setNodeSearch(event.target.value)}
                                        borderRadius="4px"
                                        pl={7}
                                      />
                                      {nodeSearch.length > 0 && (
                                        <InputRightElement>
                                          <IconButton
                                            onClick={() => setNodeSearch("")}
                                            aria-label="clear"
                                            size="xs"
                                            variant="ghost"
                                          >
                                            <XMarkIcon width="14px" />
                                          </IconButton>
                                        </InputRightElement>
                                      )}
                                    </InputGroup>
                                    {selectedIds.length > 0 && (
                                      <Button
                                        variant="ghost"
                                        size="xs"
                                        onClick={() => field.onChange([])}
                                      >
                                        {t("hostsDialog.linkedNodes.clear")}
                                      </Button>
                                    )}
                                    <VStack
                                      align="start"
                                      spacing={2}
                                      maxH="240px"
                                      overflowY="auto"
                                      sx={thinScrollbarSx}
                                      w="full"
                                    >
                                      {filteredNodes.map((node: NodeType) => {
                                        const nodeId = node.id as number;
                                        return (
                                          <Checkbox
                                            key={nodeId}
                                            isChecked={selectedIds.includes(nodeId)}
                                            onChange={(
                                              event: ChangeEvent<HTMLInputElement>
                                            ) => {
                                              if (event.target.checked) {
                                                field.onChange([
                                                  ...selectedIds,
                                                  nodeId,
                                                ]);
                                              } else {
                                                field.onChange(
                                                  selectedIds.filter(
                                                    (id: number) => id !== nodeId
                                                  )
                                                );
                                              }
                                            }}
                                          >
                                            <Text as="span" fontSize="sm">
                                              {node.name}
                                            </Text>
                                          </Checkbox>
                                        );
                                      })}
                                      {filteredNodes.length === 0 && (
                                        <Text fontSize="sm" color="gray.500">
                                          {t("hostsDialog.linkedNodes.notFound")}
                                        </Text>
                                      )}
                                    </VStack>
                                  </VStack>
                                </PopoverBody>
                              </PopoverContent>
                            </Portal>
                          </Popover>
                        );
                      }}
                    />
                  </FormControl>
                )}
                {/* почему поля ниже неактивны — до них, а не после */}
                {composite && <Text gridColumn="1 / -1" fontSize="xs">{t("hostsDialog.injection.pinsHint")}</Text>}
                <Box as="fieldset" disabled={composite} display="contents">
                {/* NPVPN-2072: сужение адресов — свойство ХОСТА: у локаций разное число нод,
                    и одна настройка на всего бота этого не выражала. */}
                <RHFCheckbox
                  label={t("hostsDialog.addressSubset")}
                  registerProps={register(`${hostKey}.${index}.address_subset_enabled`)}
                  error={accordionErrors?.address_subset_enabled}
                  // своей строкой: рядом с полем с подписью ряд выходил выше
                  // галочки, и «Менять набор…» отрывалось от неё
                  formControlProps={{ gridColumn: { md: "1 / -1" } }}
                />

                {/* размер и период действуют только при включённом сужении; fieldset,
                    а не disabled у поля: значения в форме так не теряются */}
                <Box
                  as="fieldset"
                  disabled={!currentHost.address_subset_enabled}
                  display="contents"
                  // стиль Chakra не видит отключения через fieldset — приглушаем сами
                  sx={
                    currentHost.address_subset_enabled
                      ? undefined
                      : {
                          "& label, & input, & [role=button]": {
                            opacity: 0.5,
                          },
                          "& input": { cursor: "not-allowed" },
                        }
                  }
                >
                <RHFInput
                  label={t("hostsDialog.addressSubsetSize")}
                  placeholder={t("hostsDialog.addressSubsetSize.placeholder")}
                  type="number"
                  registerProps={register(`${hostKey}.${index}.address_subset_size`)}
                  error={accordionErrors?.address_subset_size}
                  inputProps={{ min: 1 }}
                />

                <RHFInput
                  label={t("hostsDialog.addressRotationDays")}
                  placeholder={t("hostsDialog.addressRotationDays.placeholder")}
                  type="number"
                  registerProps={register(`${hostKey}.${index}.address_rotation_days`)}
                  error={accordionErrors?.address_rotation_days}
                  inputProps={{ min: 1 }}
                />
                </Box>

                </Box>
              </SimpleGrid>
            </TabPanel>
            <TabPanel px={0}>
              <SimpleGrid
                  columns={{ base: 1, md: 2 }}
                  spacingX={3}
                  spacingY={3}
                  w="full"
                >
                <FormControl>
                  <FormLabel>{t("hostsDialog.clientConfig")}</FormLabel>
                  <Controller
                    control={control}
                    name={`${hostKey}.${index}.client_config_id`}
                    render={({ field }) => (
                      <Select
                        size="sm"
                        value={field.value ?? ""}
                        onChange={(e) =>
                          field.onChange(
                            e.target.value === "" ? null : Number(e.target.value)
                          )
                        }
                      >
                        <option value="">
                          {t("hostsDialog.clientConfigDefault")}
                        </option>
                        {clientConfigs.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.title}
                          </option>
                        ))}
                      </Select>
                    )}
                  />
                </FormControl>
                {templateError && <Text color="red.500" gridColumn="1 / -1">{t("hostsDialog.injection.invalidTemplate")}</Text>}
                <HostInjectionOptions
                  path={`${hostKey}.${index}`}
                  errors={accordionErrors}
                  completeCatalog={completeCatalog}
                />
                <HostBalancingOptions hostKey={hostKey} index={index} nodes={nodes} errors={accordionErrors} composite={composite} />
              </SimpleGrid>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    );
  }
);

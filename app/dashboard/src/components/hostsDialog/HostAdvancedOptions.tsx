import {
  FormControl,
  Text,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverTrigger,
  Portal,
  VStack,
  Badge,
  Button,
  Checkbox,
  FormLabel,
} from "@chakra-ui/react";
import { ChevronDownIcon } from "@heroicons/react/24/outline";
import { NodeType } from "contexts/NodesContext";
import { ChangeEvent, memo, useEffect } from "react";
import { Control, Controller, UseFormRegister } from "react-hook-form";
import { Bot } from "types/Bot";
import { InfoIcon, Error } from "./constants";
import { Trans } from "react-i18next";
import { RHFInput } from "./RHFInput";
import { RHFCheckbox } from "./RHFCheckbox";
import { RHFSelect } from "./RHFSelect";

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
  }: HostAdvancedOptionsProps) => {
    const portPlaceholder = inbound?.port ?? "8080";

    return (
      <VStack key={index} w="full" borderRadius="4px">
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

        <RHFInput
          label={t("hostsDialog.fragment")}
          registerProps={register(`${hostKey}.${index}.fragment_setting`)}
          error={accordionErrors?.fragment_setting}
          placeholder="Fragment settings by pattern"
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
        />

        <RHFInput
          label={t("hostsDialog.noise")}
          registerProps={register(`${hostKey}.${index}.noise_setting`)}
          error={accordionErrors?.noise_setting}
          placeholder="Noise settings by pattern"
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
        />

        {["splithttp", "xhttp"].includes(inbound?.network) && (
          <RHFInput
            label={t("hostsDialog.xhttpExtra")}
            registerProps={register(`${hostKey}.${index}.xhttp_extra`)}
            error={accordionErrors?.xhttp_extra}
            placeholder='{"xPaddingMethod": "tokenish"}'
            inputProps={{ size: "sm", borderRadius: "4px" }}
          />
        )}

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

        {bots.length > 0 && (
          <FormControl isInvalid={!!accordionErrors?.bot_usernames}>
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

                return (
                  <Popover placement="bottom-start">
                    <PopoverTrigger>
                      <Button
                        variant="outline"
                        size="sm"
                        w="full"
                        justifyContent="space-between"
                      >
                        <Text as="span" noOfLines={1}>
                          {selectedBots.length
                            ? t("hostsDialog.availableBots.selected", {
                                count: selectedBots.length,
                              })
                            : t("hostsDialog.availableBots.all")}
                        </Text>
                        <ChevronDownIcon width="16px" />
                      </Button>
                    </PopoverTrigger>
                    <Portal>
                      <PopoverContent
                        w="280px"
                        maxH="320px"
                        overflowY="auto"
                        zIndex={1500}
                      >
                        <PopoverArrow />
                        <PopoverCloseButton />
                        <PopoverBody pt={8}>
                          <VStack align="start" spacing={2}>
                            {bots.map((bot: Bot) => (
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
                                    field.onChange(
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
                            {selectedBotUsernames.length > 0 && (
                              <Button
                                variant="ghost"
                                size="xs"
                                onClick={() => field.onChange([])}
                              >
                                {t("hostsDialog.availableBots.clear")}
                              </Button>
                            )}
                          </VStack>
                        </PopoverBody>
                      </PopoverContent>
                    </Portal>
                  </Popover>
                );
              }}
            />
            {accordionErrors?.bot_usernames && (
              <Error>{accordionErrors.bot_usernames.message}</Error>
            )}
          </FormControl>
        )}
        {nodes.filter((n) => n.id != null).length > 0 && (
          <FormControl>
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
                return (
                  <Popover isLazy placement="bottom-start">
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
                      <PopoverContent
                        w="280px"
                        maxH="320px"
                        overflowY="auto"
                        zIndex={1500}
                      >
                        <PopoverArrow />
                        <PopoverCloseButton />
                        <PopoverBody pt={8}>
                          <VStack align="start" spacing={2}>
                            {nodes
                              .filter((n) => n.id != null)
                              .map((node: NodeType) => {
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
                            {selectedIds.length > 0 && (
                              <Button
                                variant="ghost"
                                size="xs"
                                onClick={() => field.onChange([])}
                              >
                                {t("hostsDialog.linkedNodes.clear")}
                              </Button>
                            )}
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
      </VStack>
    );
  }
);

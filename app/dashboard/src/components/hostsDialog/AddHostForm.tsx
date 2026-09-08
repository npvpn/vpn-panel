import {
  Box,
  Button,
  Flex,
  FormControl,
  IconButton,
  Select,
  Switch,
  Tooltip,
} from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  proxyALPN,
  proxyFingerprint,
  proxyHostSecurity,
} from "constants/Proxies";
import { NodeType } from "contexts/NodesContext";
import { FC, useEffect, useState } from "react";
import { Controller, FormProvider, useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Bot } from "types/Bot";
import { z } from "zod";
import { GearIcon, hasAdvancedFieldErrors } from "./constants";
import { HostAdvancedOptionsModal } from "./HostAdvancedOptionsModal";
import { HostInfoPopover } from "./HostInfoPopover";
import { RHFInput } from "./RHFInput";
import { hostItemSchema, hostsFormSchema } from "./schema";

export const EMPTY_HOST: z.infer<typeof hostItemSchema> = {
  host: "",
  sni: "",
  port: null,
  path: null,
  address: "",
  remark: "",
  mux_enable: false,
  allowinsecure: false,
  is_disabled: false,
  fragment_setting: "",
  noise_setting: "",
  random_user_agent: false,
  security: "inbound_default",
  alpn: "",
  fingerprint: "",
  use_sni_as_host: false,
  xhttp_extra: "",
  bot_usernames: [],
  node_ids: [],
  order: 0,
  inbound_tag: "",
};

const HOST_KEY = "hosts";

type Props = {
  inboundTags: string[];
  defaultInboundTag: string;
  bots: Bot[];
  nodes: NodeType[];
  inboundMap: Map<string, any>;
  onAdded: (host: z.infer<typeof hostItemSchema>) => void;
};

export const AddHostForm: FC<Props> = ({
  inboundTags,
  defaultInboundTag,
  bots,
  nodes,
  inboundMap,
  onAdded,
}) => {
  const { t } = useTranslation();
  const initialTag = defaultInboundTag || inboundTags[0] || "";

  const form = useForm<z.infer<typeof hostsFormSchema>>({
    resolver: zodResolver(hostsFormSchema),
    defaultValues: {
      hosts: [{ ...EMPTY_HOST, inbound_tag: initialTag }],
    },
  });

  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);

  useEffect(() => {
    const tag = defaultInboundTag || inboundTags[0] || "";
    if (tag) {
      form.setValue("hosts.0.inbound_tag", tag);
    }
  }, [defaultInboundTag, inboundTags, form]);

  const inboundTag = useWatch({
    control: form.control,
    name: "hosts.0.inbound_tag",
  });

  const remark = useWatch({ control: form.control, name: "hosts.0.remark" });

  const accordionErrors = form.formState.errors.hosts?.[0];

  const hasAdvancedErrors = hasAdvancedFieldErrors(accordionErrors, true);

  const handleAdd = form.handleSubmit((data) => {
    onAdded(data.hosts[0]);

    form.reset({
      hosts: [
        {
          ...EMPTY_HOST,
          inbound_tag: defaultInboundTag || inboundTags[0] || "",
        },
      ],
    });

    requestAnimationFrame(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
  });

  return (
    <FormProvider {...form}>
      <Box
        border="1px solid"
        _dark={{ borderColor: "gray.600" }}
        _light={{ borderColor: "gray.200" }}
        borderRadius="4px"
        p={3}
        w="full"
        mb={3}
      >
        {inboundTag ? (
          <Flex wrap="wrap" gap={2} align="flex-start">
            <FormControl w="160px" flexShrink={0}>
              <Select
                size="sm"
                aria-label={t("hostsDialog.selectInbound") ?? undefined}
                value={inboundTag || ""}
                onChange={(e) =>
                  form.setValue("hosts.0.inbound_tag", e.target.value, {
                    shouldValidate: true,
                  })
                }
              >
                {inboundTags.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </Select>
            </FormControl>

            <RHFInput
              label="Remark"
              hideLabel
              registerProps={form.register(`${HOST_KEY}.0.remark`)}
              error={accordionErrors?.remark}
              placeholder="Remark"
              rightElement={<HostInfoPopover t={t} />}
              formControlProps={{
                flex: "2",
                minW: "160px",
                position: "relative",
                zIndex: 10,
              }}
              inputProps={{
                size: "sm",
                borderRadius: "4px",
                "aria-label": "Remark",
              }}
            />

            <RHFInput
              label="Address"
              hideLabel
              registerProps={form.register(`${HOST_KEY}.0.address`)}
              error={accordionErrors?.address}
              placeholder="{SERVER_IP}"
              rightElement={<HostInfoPopover t={t} />}
              formControlProps={{ flex: "1.5", minW: "140px" }}
              inputProps={{
                size: "sm",
                borderRadius: "4px",
                "aria-label": "Address",
              }}
            />

            <Flex
              flexShrink={0}
              align="center"
              gap={2}
              h="32px"
              alignSelf="center"
            >
              <Controller
                control={form.control}
                name={`${HOST_KEY}.0.is_disabled`}
                render={({ field }) => (
                  <Switch
                    colorScheme="primary"
                    isChecked={!field.value}
                    onChange={(e) => field.onChange(!e.target.checked)}
                  />
                )}
              />

              <Tooltip
                label={t("hostsDialog.advancedOptions")}
                placement="top"
              >
                <Box position="relative" display="inline-block">
                  <IconButton
                    aria-label={t("hostsDialog.advancedOptions")}
                    size="xs"
                    variant="ghost"
                    onClick={() => setIsAdvancedOpen(true)}
                  >
                    <GearIcon />
                  </IconButton>

                  {hasAdvancedErrors && (
                    <Box
                      position="absolute"
                      top="1px"
                      right="1px"
                      w="8px"
                      h="8px"
                      borderRadius="full"
                      bg="red.500"
                      border="2px solid"
                      borderColor="white"
                      _dark={{ borderColor: "gray.700" }}
                      pointerEvents="none"
                    />
                  )}
                </Box>
              </Tooltip>

              <Button
                type="button"
                size="sm"
                colorScheme="primary"
                onClick={handleAdd}
              >
                {t("hostsDialog.addHost")}
              </Button>
            </Flex>
          </Flex>
        ) : null}
      </Box>

      <HostAdvancedOptionsModal
        isOpen={isAdvancedOpen}
        onClose={() => setIsAdvancedOpen(false)}
        hostKey={HOST_KEY}
        index={0}
        inbound={inboundMap.get(inboundTag)}
        register={form.register}
        control={form.control}
        accordionErrors={accordionErrors}
        t={t}
        bots={bots}
        nodes={nodes}
        proxyHostSecurity={proxyHostSecurity}
        proxyALPN={proxyALPN}
        proxyFingerprint={proxyFingerprint}
        hideRemarkAddress
        remark={remark}
      />
    </FormProvider>
  );
};

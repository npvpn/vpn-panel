import { Box, Button, FormControl, FormLabel, HStack, Select, VStack } from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  proxyALPN,
  proxyFingerprint,
  proxyHostSecurity,
} from "constants/Proxies";
import { NodeType } from "contexts/NodesContext";
import { FC, useEffect } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Bot } from "types/Bot";
import { z } from "zod";
import { HostRow } from "./HostRow";
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
        <VStack align="stretch" spacing={3}>
          <FormControl>
            <FormLabel fontSize="sm" mb={1}>
              {t("hostsDialog.selectInbound")}
            </FormLabel>
            <Select
              size="sm"
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

          {inboundTag ? (
            <>
              <HostRow
                hostId="new-host"
                index={0}
                inboundTag={inboundTag}
                canMoveUp={false}
                canMoveDown={false}
                duplicateHost={() => undefined}
                moveHostPosition={() => undefined}
                removeHost={() => undefined}
                bots={bots}
                nodes={nodes}
                inbound={inboundMap.get(inboundTag)}
                accordionErrors={form.formState.errors.hosts}
                proxyHostSecurity={proxyHostSecurity}
                proxyALPN={proxyALPN}
                proxyFingerprint={proxyFingerprint}
                t={t}
                isFirst
                mode="create"
              />
              <HStack justify="flex-end">
                <Button
                  type="button"
                  size="sm"
                  colorScheme="primary"
                  onClick={handleAdd}
                >
                  {t("hostsDialog.addHost")}
                </Button>
              </HStack>
            </>
          ) : null}
        </VStack>
      </Box>
    </FormProvider>
  );
};

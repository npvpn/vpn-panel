import { Button, HStack, Select, VStack, Text } from "@chakra-ui/react";
import { FC, useCallback, useEffect, useMemo, useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Bot } from "types/Bot";
import {
  proxyALPN,
  proxyFingerprint,
  proxyHostSecurity,
} from "constants/Proxies";
import { NodeType } from "contexts/NodesContext";
import { hostsFormSchema } from "./schema";
import { HostRow } from "./HostRow";

const EMPTY_HOST = {
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
  inboundFilter: string;
  search: string;
  bots: Bot[];
  nodes: NodeType[];
  inboundMap: Map<string, any>;
};

export const HostsList: FC<Props> = ({
  inboundTags,
  inboundFilter,
  search,
  bots,
  nodes,
  inboundMap,
}) => {
  const { t } = useTranslation();
  const form = useFormContext<z.infer<typeof hostsFormSchema>>();
  const { errors } = form.formState;
  const accordionErrors = errors.hosts;

  const { fields, replace } = useFieldArray({
    control: form.control,
    name: "hosts",
  });

  const watchedHosts = useWatch({ control: form.control, name: "hosts" });
  const [addInboundTag, setAddInboundTag] = useState(
    inboundFilter || inboundTags[0] || ""
  );

  useEffect(() => {
    if (inboundFilter) {
      setAddInboundTag(inboundFilter);
    } else if (!addInboundTag || !inboundTags.includes(addInboundTag)) {
      setAddInboundTag(inboundTags[0] || "");
    }
  }, [inboundFilter, inboundTags, addInboundTag]);

  const visibleIndexes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return fields
      .map((_, index) => index)
      .filter((index) => {
        const host = watchedHosts?.[index];
        if (!host) return false;
        if (inboundFilter && host.inbound_tag !== inboundFilter) return false;
        if (query && !(host.remark || "").toLowerCase().includes(query))
          return false;
        return true;
      });
  }, [fields, watchedHosts, inboundFilter, search]);

  const renumberOrders = useCallback(
    (hosts: z.infer<typeof hostsFormSchema>["hosts"]) => {
      return hosts.map((host, index) => ({ ...host, order: index }));
    },
    []
  );

  const setHosts = useCallback(
    (hosts: z.infer<typeof hostsFormSchema>["hosts"]) => {
      replace(renumberOrders(hosts));
    },
    [renumberOrders, replace]
  );

  const handleAddHost = useCallback(() => {
    const tag = addInboundTag || inboundTags[0];
    if (!tag) return;
    const current = form.getValues("hosts") || [];
    setHosts([
      ...current,
      {
        ...EMPTY_HOST,
        inbound_tag: tag,
        order: current.length,
      },
    ]);
  }, [addInboundTag, form, inboundTags, setHosts]);

  const duplicateHost = useCallback(
    (index: number) => {
      const hosts = [...(form.getValues("hosts") || [])];
      const value = hosts[index];
      if (!value) return;
      hosts.splice(index + 1, 0, structuredClone(value));
      setHosts(hosts);
    },
    [form, setHosts]
  );

  const moveHostPosition = useCallback(
    (index: number, direction: "up" | "down") => {
      const visiblePos = visibleIndexes.indexOf(index);
      if (visiblePos < 0) return;
      const targetPos = direction === "up" ? visiblePos - 1 : visiblePos + 1;
      const targetIndex = visibleIndexes[targetPos];
      if (targetIndex === undefined) return;

      const hosts = [...(form.getValues("hosts") || [])];
      const tmp = hosts[index];
      hosts[index] = hosts[targetIndex];
      hosts[targetIndex] = tmp;
      setHosts(hosts);
    },
    [form, setHosts, visibleIndexes]
  );

  const removeHost = useCallback(
    (index: number) => {
      const hosts = [...(form.getValues("hosts") || [])];
      hosts.splice(index, 1);
      setHosts(hosts);
    },
    [form, setHosts]
  );

  if (inboundTags.length === 0) {
    return (
      <Text opacity={0.8} fontSize="sm">
        No inbound found. Please check your Xray config file.
      </Text>
    );
  }

  return (
    <VStack w="full" align="stretch" spacing={3}>
      {visibleIndexes.length === 0 ? (
        <Text opacity={0.7} fontSize="sm" py={4} textAlign="center">
          {t("hostsDialog.notFound")}
        </Text>
      ) : (
        visibleIndexes.map((index, visiblePos) => {
          const host = watchedHosts?.[index];
          const field = fields[index];
          if (!host || !field) return null;
          return (
            <HostRow
              key={field.id}
              hostId={field.id}
              index={index}
              inboundTag={host.inbound_tag}
              canMoveUp={visiblePos > 0}
              canMoveDown={visiblePos < visibleIndexes.length - 1}
              duplicateHost={duplicateHost}
              moveHostPosition={moveHostPosition}
              removeHost={removeHost}
              bots={bots}
              nodes={nodes}
              inbound={inboundMap.get(host.inbound_tag)}
              accordionErrors={accordionErrors}
              proxyHostSecurity={proxyHostSecurity}
              proxyALPN={proxyALPN}
              proxyFingerprint={proxyFingerprint}
              t={t}
              isFirst={visiblePos === 0}
            />
          );
        })
      )}

      <HStack w="full" spacing={2}>
        {!inboundFilter && (
          <Select
            size="sm"
            value={addInboundTag}
            onChange={(e) => setAddInboundTag(e.target.value)}
            maxW="60%"
          >
            {inboundTags.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </Select>
        )}
        <Button
          variant="outline"
          type="button"
          flex="1"
          size="sm"
          fontWeight="normal"
          onClick={handleAddHost}
          isDisabled={!addInboundTag}
        >
          {t("hostsDialog.addHost")}
        </Button>
      </HStack>
    </VStack>
  );
};

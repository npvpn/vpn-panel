import { VStack, Text } from "@chakra-ui/react";
import { FC, useCallback, useMemo } from "react";
import { useFormContext, useWatch } from "react-hook-form";
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

  const watchedHosts = useWatch({
    control: form.control,
    name: "hosts",
  });

  const visibleIndexes = useMemo(() => {
    const query = search.trim().toLowerCase();

    return (watchedHosts || [])
      .map((_, index) => index)
      .filter((index) => {
        const host = watchedHosts?.[index];

        if (!host) return false;

        if (inboundFilter && host.inbound_tag !== inboundFilter) {
          return false;
        }

        if (query && !(host.remark || "").toLowerCase().includes(query)) {
          return false;
        }

        return true;
      });
  }, [watchedHosts, inboundFilter, search]);

  const setHosts = useCallback(
    (hosts: z.infer<typeof hostsFormSchema>["hosts"]) => {
      const renumbered = hosts.map((host, index) => ({
        ...host,
        order: index,
      }));

      form.setValue("hosts", renumbered, {
        shouldDirty: true,
        shouldValidate: true,
      });
    },
    [form]
  );

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

          if (!host) return null;

          return (
            <HostRow
              key={`${index}-${host.remark || "host"}`}
              hostId={`${index}`}
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
    </VStack>
  );
};

import { Button, Collapse, VStack, Text } from "@chakra-ui/react";
import {
  ChevronDownIcon,
  PlusIcon as HeroIconPlusIcon,
} from "@heroicons/react/24/outline";
import { FC, useCallback, useMemo, useState } from "react";
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
import { AddHostForm, EMPTY_HOST } from "./AddHostForm";
import { hostsFormSchema, hostItemSchema } from "./schema";
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
  const [isAddingHost, setIsAddingHost] = useState(false);

  const { fields, replace } = useFieldArray({
    control: form.control,
    name: "hosts",
  });

  const watchedHosts = useWatch({ control: form.control, name: "hosts" });

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

  const handleHostAdded = useCallback(
    (host: z.infer<typeof hostItemSchema>) => {
      const current = form.getValues("hosts") || [];
      setHosts([
        ...current,
        {
          ...EMPTY_HOST,
          ...host,
          order: current.length,
        },
      ]);
      setIsAddingHost(false);
    },
    [form, setHosts]
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
      <Button
        w="full"
        variant="outline"
        leftIcon={<HeroIconPlusIcon width="20px" strokeWidth={2} />}
        rightIcon={
          <ChevronDownIcon
            width="16px"
            style={{
              transform: isAddingHost ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s ease",
            }}
          />
        }
        onClick={() => setIsAddingHost((prev) => !prev)}
      >
        {t("hostsDialog.addNewHost")}
      </Button>

      <Collapse in={isAddingHost} animateOpacity>
        <AddHostForm
          inboundTags={inboundTags}
          defaultInboundTag={inboundFilter || inboundTags[0] || ""}
          bots={bots}
          nodes={nodes}
          inboundMap={inboundMap}
          onAdded={handleHostAdded}
        />
      </Collapse>

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
    </VStack>
  );
};

import { VStack, Text } from "@chakra-ui/react";
import { FC, useCallback, useEffect, useMemo, useRef } from "react";
import {
  FieldArrayWithId,
  UseFieldArrayInsert,
  UseFieldArrayMove,
  UseFieldArrayRemove,
  useFormContext,
  useWatch,
} from "react-hook-form";
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

type HostField = FieldArrayWithId<z.infer<typeof hostsFormSchema>, "hosts">;

type Props = {
  fields: HostField[];
  inboundTags: string[];
  inboundFilter: string;
  search: string;
  bots: Bot[];
  nodes: NodeType[];
  inboundMap: Map<string, any>;
  insert: UseFieldArrayInsert<z.infer<typeof hostsFormSchema>, "hosts">;
  move: UseFieldArrayMove;
  remove: UseFieldArrayRemove;
};

export const HostsList: FC<Props> = ({
  fields,
  inboundTags,
  inboundFilter,
  search,
  bots,
  nodes,
  inboundMap,
  insert,
  move,
  remove,
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

    return fields
      .map((field, index) => ({ field, index }))
      .filter(({ index }) => {
        const host = watchedHosts?.[index];

        if (!host) return false;

        if (inboundFilter && host.inbound_tag !== inboundFilter) {
          return false;
        }

        if (query && !(host.remark || "").toLowerCase().includes(query)) {
          return false;
        }

        return true;
      })
      .map(({ index }) => index);
  }, [fields, watchedHosts, inboundFilter, search]);

  const duplicateHost = useCallback(
    (index: number) => {
      const value = form.getValues(`hosts.${index}`);

      if (!value) return;

      insert(index + 1, structuredClone(value), {
        shouldFocus: false,
      });
    },
    [form, insert]
  );

  const visibleIndexesRef = useRef(visibleIndexes);

  useEffect(() => {
    visibleIndexesRef.current = visibleIndexes;
  }, [visibleIndexes]);

  const moveHostPosition = useCallback(
    (index: number, direction: "up" | "down") => {
      const currentVisibleIndexes = visibleIndexesRef.current;
      const visiblePos = currentVisibleIndexes.indexOf(index);
      if (visiblePos < 0) return;
      const targetPos = direction === "up" ? visiblePos - 1 : visiblePos + 1;
      const targetIndex = currentVisibleIndexes[targetPos];
      if (targetIndex === undefined) return;
      move(index, targetIndex);
    },
    [move]
  );

  const removeHost = useCallback(
    (index: number) => {
      remove(index);
    },
    [remove]
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
          const field = fields[index];

          if (!field) return null;

          return (
            <HostRow
              key={field.id}
              hostId={field.id}
              index={index}
              inboundTag={watchedHosts?.[index]?.inbound_tag ?? ""}
              canMoveUp={visiblePos > 0}
              canMoveDown={visiblePos < visibleIndexes.length - 1}
              duplicateHost={duplicateHost}
              moveHostPosition={moveHostPosition}
              removeHost={removeHost}
              bots={bots}
              nodes={nodes}
              inbound={inboundMap.get(watchedHosts?.[index]?.inbound_tag)}
              accordionErrors={accordionErrors?.[index]}
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

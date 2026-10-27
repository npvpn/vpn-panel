import { Box, Tooltip } from "@chakra-ui/react";
import { memo } from "react";
import { Controller, useFormContext } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { Select } from "./constants";
import { changeHostInbound } from "./hostInbound";
import { hostsFormSchema } from "./schema";

export const HostInboundSelect = memo(function HostInboundSelect({
  index,
  inboundTags,
  inboundMap,
}: {
  index: number;
  inboundTags: string[];
  inboundMap: ReadonlyMap<string, { network?: string }>;
}) {
  const { control, getValues, setValue } =
    useFormContext<z.infer<typeof hostsFormSchema>>();
  const { t } = useTranslation();
  return (
    <Controller
      control={control}
      name={`hosts.${index}.inbound_tag`}
      render={({ field }) => (
        // полное название — в строке оно обрезается
        <Tooltip label={field.value} placement="top" openDelay={300}>
          <Box minW={0}>
            <Select
              {...field}
              aria-label={t("hostsDialog.selectInbound") ?? "Inbound"}
              size="xs"
              minW={0}
              fontSize="xs"
              onChange={(event) => {
                const current = getValues(`hosts.${index}`);
                const tag = event.target.value;
                const next = changeHostInbound(
                  current,
                  tag,
                  inboundMap.get(tag)?.network
                );
                field.onChange(next.inbound_tag);
                if (next.xhttp_extra !== current.xhttp_extra) {
                  setValue(`hosts.${index}.xhttp_extra`, next.xhttp_extra, {
                    shouldDirty: true,
                    shouldValidate: true,
                  });
                }
              }}
            >
              {inboundTags.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </Select>
          </Box>
        </Tooltip>
      )}
    />
  );
});

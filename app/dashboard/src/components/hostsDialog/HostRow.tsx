import {
  HStack,
  Switch,
  Tooltip,
  IconButton,
  Divider,
  Box,
  Badge,
  VStack,
} from "@chakra-ui/react";
import { NodeType } from "contexts/NodesContext";
import { motion } from "framer-motion";
import { memo, useState } from "react";
import { Controller, useFormContext, useWatch } from "react-hook-form";
import { Bot } from "types/Bot";
import { DuplicateIcon, DownIcon, UpIcon, GearIcon } from "./constants";
import { DeleteIcon } from "components/DeleteUserModal";
import { RHFInput } from "./RHFInput";
import { HostInfoPopover } from "./HostInfoPopover";
import { HostAdvancedOptionsModal } from "./HostAdvancedOptionsModal";
import { hostsFormSchema } from "./schema";
import { z } from "zod";

type HostRowProps = {
  index: number;
  hostId: string;
  inboundTag: string;
  bots: Bot[];
  nodes: NodeType[];
  accordionErrors?: any;
  t: (key: string, opts?: any) => string;
  duplicateHost: (index: number) => void;
  moveHostPosition: (index: number, direction: "up" | "down") => void;
  removeHost: (index: number) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  inbound: any;
  proxyHostSecurity: any[];
  proxyALPN: any[];
  proxyFingerprint: any[];
  isFirst?: boolean;
  mode?: "list" | "create";
};

const HOST_KEY = "hosts";

// Fields that live in the advanced-options modal rather than inline on the row.
const ADVANCED_FIELD_KEYS = [
  "port",
  "path",
  "sni",
  "host",
  "mux_enable",
  "allowinsecure",
  "fragment_setting",
  "noise_setting",
  "random_user_agent",
  "security",
  "alpn",
  "fingerprint",
  "use_sni_as_host",
  "xhttp_extra",
  "bot_usernames",
  "node_ids",
] as const;

export const HostRow = memo(function HostRow({
  index,
  hostId,
  inboundTag,
  bots,
  nodes,
  inbound,
  accordionErrors,
  t,
  duplicateHost,
  moveHostPosition,
  removeHost,
  canMoveUp,
  canMoveDown,
  proxyHostSecurity,
  proxyALPN,
  proxyFingerprint,
  isFirst,
  mode = "list",
}: HostRowProps) {
  const { register, control } =
    useFormContext<z.infer<typeof hostsFormSchema>>();

  const isCreate = mode === "create";

  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);

  const remark = useWatch({ control, name: `${HOST_KEY}.${index}.remark` });

  const hasAdvancedErrors = ADVANCED_FIELD_KEYS.some(
    (key) => !!accordionErrors?.[key]
  );

  const advancedOptionsButton = (
    <Tooltip label={t("hostsDialog.advancedOptions")} placement="top">
      <Box position="relative" display="inline-block">
        <IconButton
          aria-label={t("hostsDialog.advancedOptions")}
          size="sm"
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
  );

  return (
    <>
      {!isFirst && !isCreate && <Divider my={1.5} />}

      <motion.div
        initial={false}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{
          opacity: { duration: 0.1 },
        }}
        id={hostId}
        style={{ width: "100%" }}
      >
        <Box
          data-row-index={isCreate ? undefined : index}
          bg="white"
          _dark={{ bg: "gray.700" }}
          borderRadius="12px"
          boxShadow="0 2px 8px rgba(0,0,0,0.08)"
          border="1px solid"
          borderColor="gray.100"
          transition="all 0.2s ease"
          _hover={{
            boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
            _dark: {
              boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
            },
          }}
        >
          <VStack p={3} w="full" spacing={3}>
            {!isCreate && (
              <HStack w="100%" justify="space-between" alignItems="center">
                <Badge
                  colorScheme="gray"
                  fontSize="0.7rem"
                  maxW="100%"
                  isTruncated
                >
                  {inboundTag}
                </Badge>

                {advancedOptionsButton}
              </HStack>
            )}

            <HStack w="100%" alignItems="flex-start">
              <RHFInput
                label="Remark"
                registerProps={register(`${HOST_KEY}.${index}.remark`)}
                error={accordionErrors?.remark}
                rightElement={<HostInfoPopover t={t} />}
                formControlProps={{
                  position: "relative",
                  zIndex: 10,
                }}
                inputProps={{
                  size: "sm",
                  borderRadius: "4px",
                }}
              />
            </HStack>

            <RHFInput
              label="Address"
              registerProps={register(`${HOST_KEY}.${index}.address`)}
              error={accordionErrors?.address}
              placeholder="example.com"
              rightElement={<HostInfoPopover t={t} />}
              formControlProps={{
                isInvalid: !!accordionErrors?.address,
              }}
            />

            <HStack w="100%" justify="space-between" alignItems="center">
              <HStack spacing={1}>
                <Controller
                  control={control}
                  name={`${HOST_KEY}.${index}.is_disabled`}
                  render={({ field }) => (
                    <Switch
                      mx="1.5"
                      colorScheme="primary"
                      isChecked={!field.value}
                      onChange={(e) => field.onChange(!e.target.checked)}
                    />
                  )}
                />

                {!isCreate && (
                  <Tooltip label="Delete" placement="top">
                    <IconButton
                      aria-label="Delete"
                      size="sm"
                      colorScheme="red"
                      variant="ghost"
                      onClick={() => removeHost(index)}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </Tooltip>
                )}
              </HStack>

              {!isCreate && (
                <HStack spacing={1}>
                  <Tooltip label="Duplicate" placement="top">
                    <IconButton
                      aria-label="Duplicate"
                      size="sm"
                      colorScheme="white"
                      variant="ghost"
                      onClick={() => duplicateHost(index)}
                    >
                      <DuplicateIcon />
                    </IconButton>
                  </Tooltip>

                  {canMoveDown && (
                    <Tooltip label="Move Down" placement="top">
                      <IconButton
                        aria-label="Move Down"
                        size="sm"
                        colorScheme="white"
                        variant="ghost"
                        onClick={() => moveHostPosition(index, "down")}
                      >
                        <DownIcon />
                      </IconButton>
                    </Tooltip>
                  )}

                  {canMoveUp && (
                    <Tooltip label="Move Up" placement="top">
                      <IconButton
                        aria-label="Move Up"
                        size="sm"
                        colorScheme="white"
                        variant="ghost"
                        onClick={() => moveHostPosition(index, "up")}
                      >
                        <UpIcon />
                      </IconButton>
                    </Tooltip>
                  )}
                </HStack>
              )}

              {isCreate && advancedOptionsButton}
            </HStack>
          </VStack>
        </Box>
      </motion.div>

      <HostAdvancedOptionsModal
        isOpen={isAdvancedOpen}
        onClose={() => setIsAdvancedOpen(false)}
        remark={remark}
        hostKey={HOST_KEY}
        index={index}
        inbound={inbound}
        register={register}
        control={control}
        accordionErrors={accordionErrors}
        t={t}
        bots={bots}
        nodes={nodes}
        proxyHostSecurity={proxyHostSecurity}
        proxyALPN={proxyALPN}
        proxyFingerprint={proxyFingerprint}
      />
    </>
  );
});

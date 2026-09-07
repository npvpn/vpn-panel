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

  const botUsernames = useWatch({
    control,
    name: `${HOST_KEY}.${index}.bot_usernames`,
  }) as string[] | undefined;

  const botNames = (botUsernames || []).map((username) => {
    const bot = bots.find((b) => b.username === username);
    return bot?.title ? `${bot.title} (@${username})` : `@${username}`;
  });

  const isAvailableToAllBots = botNames.length === 0;

  const botBadgeLabel = isAvailableToAllBots
    ? bots.length > 1
      ? t("hostsDialog.availableBots.all")
      : null
    : botNames.length === 1
    ? botNames[0]
    : `${botNames[0]} +${botNames.length - 1}`;

  const allBotNames = bots.map((bot) =>
    bot.title ? `${bot.title} (@${bot.username})` : `@${bot.username}`
  );

  const botBadgeTooltip = isAvailableToAllBots
    ? allBotNames.join(", ") || null
    : botNames.length > 1
    ? botNames.join(", ")
    : null;

  const hasAdvancedErrors = ADVANCED_FIELD_KEYS.some(
    (key) => !!accordionErrors?.[key]
  );

  const advancedOptionsButton = (
    <Tooltip label={t("hostsDialog.advancedOptions")} placement="left">
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
  );

  return (
    <>
      {!isFirst && !isCreate && <Divider my={0} />}

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
          <HStack w="full" spacing={0} align="stretch">
            <VStack flex="1" minW={0} p={3} spacing={2} align="stretch">
              <HStack
                justify={isCreate ? "flex-end" : "space-between"}
                align="center"
              >
                {!isCreate && (
                  <HStack spacing={2} wrap="wrap">
                    <Badge
                      colorScheme="gray"
                      fontSize="0.7rem"
                      maxW="100%"
                      isTruncated
                    >
                      {inboundTag}
                    </Badge>

                    {botBadgeLabel && (
                      <Tooltip
                        label={botBadgeTooltip}
                        placement="top"
                        isDisabled={!botBadgeTooltip}
                      >
                        <Badge
                          colorScheme="blue"
                          variant={isAvailableToAllBots ? "outline" : "solid"}
                          textTransform="none"
                          fontSize="0.7rem"
                          maxW="100%"
                          isTruncated
                        >
                          {botBadgeLabel}
                        </Badge>
                      </Tooltip>
                    )}
                  </HStack>
                )}

                <Controller
                  control={control}
                  name={`${HOST_KEY}.${index}.is_disabled`}
                  render={({ field }) => (
                    <Switch
                      colorScheme="primary"
                      isChecked={!field.value}
                      onChange={(e) => field.onChange(!e.target.checked)}
                    />
                  )}
                />
              </HStack>

              <RHFInput
                label="Remark"
                registerProps={register(`${HOST_KEY}.${index}.remark`)}
                error={accordionErrors?.remark}
                rightElement={<HostInfoPopover t={t} />}
                formControlProps={{
                  position: "relative",
                  zIndex: 10,
                }}
                formLabelProps={{ mb: 1 }}
                inputProps={{
                  size: "sm",
                  borderRadius: "4px",
                }}
              />

              <RHFInput
                label="Address"
                registerProps={register(`${HOST_KEY}.${index}.address`)}
                error={accordionErrors?.address}
                placeholder="example.com"
                rightElement={<HostInfoPopover t={t} />}
                formControlProps={{
                  isInvalid: !!accordionErrors?.address,
                }}
                formLabelProps={{ mb: 1 }}
                inputProps={{
                  size: "sm",
                  borderRadius: "4px",
                }}
              />
            </VStack>

            <VStack
              spacing={2}
              py={3}
              px={3}
              w="52px"
              flexShrink={0}
              justify="flex-start"
              align="center"
              borderLeft="1px solid"
              borderColor="gray.100"
              _dark={{ borderColor: "gray.600" }}
            >
              {advancedOptionsButton}

              {!isCreate && (
                <>
                  <Tooltip label="Duplicate" placement="left">
                    <IconButton
                      aria-label="Duplicate"
                      size="xs"
                      colorScheme="white"
                      variant="ghost"
                      onClick={() => duplicateHost(index)}
                    >
                      <DuplicateIcon />
                    </IconButton>
                  </Tooltip>

                  {canMoveDown && (
                    <Tooltip label="Move Down" placement="left">
                      <IconButton
                        aria-label="Move Down"
                        size="xs"
                        colorScheme="white"
                        variant="ghost"
                        onClick={() => moveHostPosition(index, "down")}
                      >
                        <DownIcon />
                      </IconButton>
                    </Tooltip>
                  )}

                  {canMoveUp && (
                    <Tooltip label="Move Up" placement="left">
                      <IconButton
                        aria-label="Move Up"
                        size="xs"
                        colorScheme="white"
                        variant="ghost"
                        onClick={() => moveHostPosition(index, "up")}
                      >
                        <UpIcon />
                      </IconButton>
                    </Tooltip>
                  )}
                </>
              )}

              {!isCreate && <Box flex="1" />}

              {!isCreate && (
                <Tooltip label="Delete" placement="left">
                  <IconButton
                    aria-label="Delete"
                    size="xs"
                    colorScheme="red"
                    variant="ghost"
                    onClick={() => removeHost(index)}
                  >
                    <DeleteIcon />
                  </IconButton>
                </Tooltip>
              )}
            </VStack>
          </HStack>
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

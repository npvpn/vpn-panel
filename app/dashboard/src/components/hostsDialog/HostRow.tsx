import {
  HStack,
  Switch,
  Tooltip,
  IconButton,
  Divider,
  Box,
  Badge,
  VStack,
  Text,
  Tr,
  Td,
} from "@chakra-ui/react";
import { NodeType } from "contexts/NodesContext";
import { memo, useState } from "react";
import { Controller, useFormContext, useWatch } from "react-hook-form";
import { Bot } from "types/Bot";
import {
  DuplicateIcon,
  DownIcon,
  UpIcon,
  GearIcon,
  hasAdvancedFieldErrors,
} from "./constants";
import { DeleteIcon } from "components/DeleteUserModal";
import { RHFInput } from "./RHFInput";
import { HostInfoPopover } from "./HostInfoPopover";
import { HostAdvancedOptionsModal } from "./HostAdvancedOptionsModal";
import { hostsFormSchema } from "./schema";
import { z } from "zod";

type HostRowProps = {
  index: number;
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
  isTableView?: boolean;
};

const HOST_KEY = "hosts";

export const HostRow = memo(function HostRow({
  index,
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
  isTableView = false,
}: HostRowProps) {
  const { register, control } =
    useFormContext<z.infer<typeof hostsFormSchema>>();

  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);

  const remark = useWatch({ control, name: `${HOST_KEY}.${index}.remark` });
  const address = useWatch({ control, name: `${HOST_KEY}.${index}.address` });

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

  const hasAdvancedErrors = hasAdvancedFieldErrors(
    accordionErrors,
    !isTableView
  );

  const enableSwitch = (
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

  const cardLayout = (
    <>
      {!isFirst && <Divider my={0} />}

      <Box
        data-row-index={index}
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
            <HStack justify="space-between" align="center">
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

              {enableSwitch}
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
              placeholder="{SERVER_IP}"
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

            <Box flex="1" />

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
          </VStack>
        </HStack>
      </Box>
    </>
  );

  const tdBorder = {
    borderBottom: "1px solid",
    borderColor: "gray.100",
    _dark: { borderColor: "gray.600" },
  };

  const tableLayout = (
    <Tr
      data-row-index={index}
      _hover={{
        bg: "gray.50",
        _dark: { bg: "gray.750" },
      }}
      transition="background 0.15s ease"
    >
      <Td {...tdBorder} px={2} py={2} whiteSpace="nowrap">
        <Badge colorScheme="gray" fontSize="0.7rem" maxW="200px" isTruncated>
          {inboundTag}
        </Badge>
      </Td>

      <Td {...tdBorder} px={2} py={2} whiteSpace="nowrap">
        {botBadgeLabel && (
          <Tooltip
            label={botBadgeTooltip}
            placement="top"
            isDisabled={!botBadgeTooltip}
          >
            <Text fontSize="sm" opacity={0.7} maxW="160px" isTruncated>
              {botBadgeLabel}
            </Text>
          </Tooltip>
        )}
      </Td>

      <Td {...tdBorder} px={2} py={2}>
        <Tooltip label={remark} placement="top" isDisabled={!remark}>
          <Text fontSize="sm" maxW="360px" isTruncated>
            {remark || "—"}
          </Text>
        </Tooltip>
      </Td>

      <Td {...tdBorder} px={2} py={2}>
        <Tooltip label={address} placement="top" isDisabled={!address}>
          <Text fontSize="sm" opacity={0.7} maxW="280px" isTruncated>
            {address || "—"}
          </Text>
        </Tooltip>
      </Td>

      <Td {...tdBorder} px={2} py={2} textAlign="center">
        {enableSwitch}
      </Td>

      <Td {...tdBorder} px={2} py={2} whiteSpace="nowrap">
        <HStack spacing={1} justify="flex-end">
          {advancedOptionsButton}

          <Tooltip label="Duplicate" placement="top">
            <IconButton
              aria-label="Duplicate"
              size="xs"
              variant="ghost"
              onClick={() => duplicateHost(index)}
            >
              <DuplicateIcon />
            </IconButton>
          </Tooltip>

          <Tooltip label="Move Down" placement="top">
            <IconButton
              aria-label="Move Down"
              size="xs"
              variant="ghost"
              isDisabled={!canMoveDown}
              onClick={() => moveHostPosition(index, "down")}
            >
              <DownIcon />
            </IconButton>
          </Tooltip>

          <Tooltip label="Move Up" placement="top">
            <IconButton
              aria-label="Move Up"
              size="xs"
              variant="ghost"
              isDisabled={!canMoveUp}
              onClick={() => moveHostPosition(index, "up")}
            >
              <UpIcon />
            </IconButton>
          </Tooltip>

          <Tooltip label="Delete" placement="top">
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
        </HStack>
      </Td>
    </Tr>
  );

  return (
    <>
      {isTableView ? tableLayout : cardLayout}

      <HostAdvancedOptionsModal
        isOpen={isAdvancedOpen}
        onClose={() => setIsAdvancedOpen(false)}
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
        hideRemarkAddress={!isTableView}
        remark={remark}
      />
    </>
  );
});

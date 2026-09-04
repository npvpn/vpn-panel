import {
  Text,
  VStack,
  HStack,
  Accordion,
  AccordionItem,
  AccordionIcon,
  AccordionButton,
  Container,
  Switch,
  Tooltip,
  IconButton,
  Divider,
  Box,
  Badge,
} from "@chakra-ui/react";
import { NodeType } from "contexts/NodesContext";
import { motion } from "framer-motion";
import { memo } from "react";
import { Controller, useFormContext } from "react-hook-form";
import { Bot } from "types/Bot";
import { DuplicateIcon, DownIcon, UpIcon } from "./constants";
import { DeleteIcon } from "components/DeleteUserModal";
import { RHFInput } from "./RHFInput";
import { HostInfoPopover } from "./HostInfoPopover";
import { HostAdvancedOptions } from "./HostAdvancedOptions";
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

            <Accordion w="full" allowToggle>
              <AccordionItem border="0">
                {({ isExpanded }) => (
                  <>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                      }}
                    >
                      <AccordionButton
                        display="flex"
                        px={0}
                        py={1}
                        borderRadius={3}
                        _hover={{ bg: "transparent" }}
                      >
                        <Text
                          flex="3"
                          align="start"
                          fontSize="xs"
                          color="gray.600"
                          _dark={{ color: "gray.500" }}
                          pl={1}
                        >
                          {t("hostsDialog.advancedOptions")}
                          <AccordionIcon fontSize="sm" ml={1} />
                        </Text>

                        <Container flex="1" px="0" display="contents">
                          <Controller
                            control={control}
                            name={`${HOST_KEY}.${index}.is_disabled`}
                            render={({ field }) => (
                              <Switch
                                mx="1.5"
                                colorScheme="primary"
                                isChecked={!field.value}
                                onChange={(e) =>
                                  field.onChange(!e.target.checked)
                                }
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
                        </Container>
                      </AccordionButton>

                      {!isCreate && (
                        <>
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
                        </>
                      )}
                    </div>

                    {isExpanded && (
                      <HostAdvancedOptions
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
                    )}
                  </>
                )}
              </AccordionItem>
            </Accordion>
          </VStack>
        </Box>
      </motion.div>
    </>
  );
});

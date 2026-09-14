import {
  Alert,
  AlertDescription,
  Box,
  Button,
  ButtonProps,
  chakra,
  Checkbox,
  Collapse,
  FormControl,
  FormLabel,
  HStack,
  IconButton,
  Select,
  Switch,
  Text,
  Tooltip,
  VStack,
} from "@chakra-ui/react";
import { EyeIcon, EyeSlashIcon } from "@heroicons/react/24/outline";
import { NodeType, useNodesQuery } from "contexts/NodesContext";
import { FC, ReactNode, useEffect, useMemo, useState } from "react";
import { Controller, useFieldArray, UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { UseMutateFunction } from "react-query";
import "slick-carousel/slick/slick-theme.css";
import "slick-carousel/slick/slick.css";
import { useDashboard } from "../contexts/DashboardContext";
import { Input } from "./Input";

type NodeFormType = FC<{
  form: UseFormReturn<NodeType>;
  mutate: UseMutateFunction<unknown, unknown, any>;
  isLoading: boolean;
  submitBtnText: string;
  btnProps?: Partial<ButtonProps>;
  btnLeftAdornment?: ReactNode;
  addAsHost?: boolean;
  nodeSettings?: {
    min_node_version: string;
    certificate: string;
  };
}>;

const CustomInput = chakra(Input, {
  baseStyle: {
    bg: "white",
    _dark: {
      bg: "gray.700",
    },
  },
});

function selectText(element: HTMLElement) {
  if (window.getSelection) {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(element);
    selection!.removeAllRanges();
    selection!.addRange(range);
  }
}

export const NodeForm: NodeFormType = ({
  form,
  mutate,
  isLoading,
  submitBtnText,
  btnProps = {},
  btnLeftAdornment,
  addAsHost = false,
  nodeSettings,
}) => {
  const { t } = useTranslation();
  const { inbounds: allInbounds } = useDashboard();
  const inboundTags: string[] = useMemo(
    () =>
      Array.from(
        new Set(
          Array.from(allInbounds.values())
            .flat()
            .map((i) => i.tag)
        )
      ),
    [allInbounds]
  );
  const { data: allNodes } = useNodesQuery();
  const exitNodes = useMemo(
    () =>
      (allNodes || []).filter(
        (n) => n.role === "exit" && typeof n.id === "number"
      ),
    [allNodes]
  );
  const role = form.watch("role");
  const {
    fields: routeFields,
    append: appendRoute,
    remove: removeRoute,
  } = useFieldArray({ control: form.control, name: "cascade_routes" });
  const [showCertificate, setShowCertificate] = useState(false);

  const certUrl = useMemo(() => {
    if (!nodeSettings?.certificate) return null;
    return URL.createObjectURL(
      new Blob([nodeSettings.certificate], { type: "text/plain" })
    );
  }, [nodeSettings?.certificate]);

  useEffect(() => {
    return () => {
      if (certUrl) URL.revokeObjectURL(certUrl);
    };
  }, [certUrl]);

  return (
    <form onSubmit={form.handleSubmit((v) => mutate(v))}>
      <VStack>
        {nodeSettings && nodeSettings.certificate && (
          <Alert status="info" alignItems="start">
            <AlertDescription
              display="flex"
              flexDirection="column"
              overflow="hidden"
            >
              <span>{t("nodes.connection-hint")}</span>
              <HStack justify="end" py={2}>
                <Button
                  as="a"
                  colorScheme="primary"
                  size="xs"
                  download="ssl_client_cert.pem"
                  href={certUrl ?? ""}
                >
                  {t("nodes.download-certificate")}
                </Button>
                <Tooltip
                  placement="top"
                  label={t(
                    !showCertificate
                      ? "nodes.show-certificate"
                      : "nodes.show-certificate"
                  )}
                >
                  <IconButton
                    aria-label={t(
                      !showCertificate
                        ? "nodes.show-certificate"
                        : "nodes.show-certificate"
                    )}
                    onClick={setShowCertificate.bind(null, !showCertificate)}
                    colorScheme="whiteAlpha"
                    color="primary"
                    size="xs"
                  >
                    {!showCertificate ? (
                      <EyeIcon width="15px" />
                    ) : (
                      <EyeSlashIcon width="15px" />
                    )}
                  </IconButton>
                </Tooltip>
              </HStack>
              <Collapse in={showCertificate} animateOpacity>
                <Text
                  bg="rgba(255,255,255,.5)"
                  _dark={{
                    bg: "rgba(255,255,255,.2)",
                  }}
                  rounded="md"
                  p="2"
                  lineHeight="1.2"
                  fontSize="10px"
                  fontFamily="Courier"
                  whiteSpace="pre"
                  overflow="auto"
                  onClick={(e) => {
                    selectText(e.target as HTMLElement);
                  }}
                >
                  {nodeSettings.certificate}
                </Text>
              </Collapse>
            </AlertDescription>
          </Alert>
        )}

        <HStack w="full">
          <FormControl>
            <CustomInput
              label={t("nodes.nodeName")}
              size="sm"
              placeholder="Marzban-S2"
              {...form.register("name")}
              error={form.formState?.errors?.name?.message}
            />
          </FormControl>
          <HStack px={1}>
            <Controller
              name="status"
              control={form.control}
              render={({ field }) => {
                return (
                  <Tooltip
                    key={field.value}
                    placement="top"
                    label={
                      `${t("usersTable.status")}: ` +
                      (field.value !== "disabled" ? t("active") : t("disabled"))
                    }
                    textTransform="capitalize"
                  >
                    <Box mt="6">
                      <Switch
                        colorScheme="primary"
                        isChecked={field.value !== "disabled"}
                        onChange={(e) => {
                          if (e.target.checked) {
                            field.onChange("connecting");
                          } else {
                            field.onChange("disabled");
                          }
                        }}
                      />
                    </Box>
                  </Tooltip>
                );
              }}
            />
          </HStack>
        </HStack>
        <HStack alignItems="flex-start" w="100%">
          <Box w="100%">
            <CustomInput
              label={t("nodes.nodeAddress")}
              size="sm"
              placeholder="51.20.12.13"
              {...form.register("address")}
              error={form.formState?.errors?.address?.message}
            />
          </Box>
        </HStack>
        <HStack alignItems="flex-start" w="100%">
          <Box>
            <FormControl>
              <FormLabel>{t("nodes.nodeProtocol")}</FormLabel>
              <Select size="sm" {...form.register("protocol")}>
                <option value="rest">{t("nodes.protocol.rest")}</option>
                <option value="rpyc">{t("nodes.protocol.rpyc")}</option>
              </Select>
            </FormControl>
          </Box>
        </HStack>
        <HStack alignItems="flex-end" w="100%">
          <Box>
            <CustomInput
              label={t("nodes.nodePort")}
              size="sm"
              placeholder="62050"
              {...form.register("port")}
              error={form.formState?.errors?.port?.message}
            />
          </Box>
          <Box>
            <CustomInput
              label={t("nodes.nodeAPIPort")}
              size="sm"
              placeholder="62051"
              {...form.register("api_port")}
              error={form.formState?.errors?.api_port?.message}
            />
          </Box>
          <Box>
            <CustomInput
              label={t("nodes.usageCoefficient")}
              size="sm"
              placeholder="1"
              {...form.register("usage_coefficient")}
              error={form.formState?.errors?.usage_coefficient?.message}
            />
          </Box>
        </HStack>
        <Box w="100%">
          <CustomInput
            label={t("nodes.hostingTrafficLimitTb")}
            size="sm"
            placeholder="0,7"
            {...form.register("hosting_traffic_limit_tb")}
            error={form.formState?.errors?.hosting_traffic_limit_tb?.message}
          />
          <Text fontSize="xs" opacity={0.7} mt={1}>
            {t("nodes.hostingTrafficLimitTbHint")}
          </Text>
        </Box>
        <FormControl py={1}>
          <FormLabel>{t("nodes.role")}</FormLabel>
          <Controller
            name="role"
            control={form.control}
            render={({ field }) => (
              <Select size="sm" {...field}>
                <option value="direct">{t("nodes.roleDirect")}</option>
                <option value="entry">{t("nodes.roleEntry")}</option>
                <option value="exit">{t("nodes.roleExit")}</option>
              </Select>
            )}
          />
        </FormControl>
        <FormControl py={1}>
          <Checkbox {...form.register("is_bs")}>
            <FormLabel m={0}>{t("nodes.isBsNode")}</FormLabel>
          </Checkbox>
        </FormControl>
        {inboundTags.length > 0 && (
          <FormControl py={1}>
            <FormLabel>{t("nodes.inbounds")}</FormLabel>
            <Text fontSize="xs" opacity={0.7} mb={2}>
              {t("nodes.inboundsHint")}
            </Text>
            <Controller
              name="inbounds"
              control={form.control}
              render={({ field }) => {
                const selected: string[] = field.value || [];
                const toggle = (tag: string, checked: boolean) => {
                  field.onChange(
                    checked
                      ? [...selected, tag]
                      : selected.filter((t) => t !== tag)
                  );
                };
                return (
                  <VStack align="flex-start" spacing={1}>
                    {inboundTags.map((tag) => (
                      <Checkbox
                        key={tag}
                        isChecked={selected.includes(tag)}
                        onChange={(e) => toggle(tag, e.target.checked)}
                      >
                        <Text fontSize="sm">{tag}</Text>
                      </Checkbox>
                    ))}
                  </VStack>
                );
              }}
            />
          </FormControl>
        )}
        {role === "entry" && (
          <FormControl py={1}>
            <FormLabel>{t("nodes.balancerStrategy")}</FormLabel>
            <Text fontSize="xs" opacity={0.7} mb={2}>
              {t("nodes.balancerStrategyHint")}
            </Text>
            <Controller
              name="cascade_balancer_strategy"
              control={form.control}
              render={({ field }) => (
                <Select size="sm" {...field} value={field.value ?? "random"}>
                  <option value="random">{t("nodes.balancerRandom")}</option>
                  <option value="roundRobin">{t("nodes.balancerRoundRobin")}</option>
                  <option value="leastPing">{t("nodes.balancerLeastPing")}</option>
                  <option value="leastLoad">{t("nodes.balancerLeastLoad")}</option>
                </Select>
              )}
            />
          </FormControl>
        )}
        {role === "entry" && (
          <FormControl py={1}>
            <FormLabel>{t("nodes.cascadeRoutes")}</FormLabel>
            <Text fontSize="xs" opacity={0.7} mb={2}>
              {t("nodes.cascadeRoutesHint")}
            </Text>
            <VStack align="stretch" spacing={2}>
              {routeFields.map((rf, idx) => (
                <HStack key={rf.id} spacing={2}>
                  <Controller
                    name={`cascade_routes.${idx}.entry_inbound_tag`}
                    control={form.control}
                    render={({ field }) => (
                      <Select
                        size="sm"
                        placeholder={t("nodes.inbounds")}
                        {...field}
                      >
                        {inboundTags.map((tag) => (
                          <option key={tag} value={tag}>
                            {tag}
                          </option>
                        ))}
                      </Select>
                    )}
                  />
                  <Controller
                    name={`cascade_routes.${idx}.exit_node_id`}
                    control={form.control}
                    render={({ field }) => (
                      <Select
                        size="sm"
                        placeholder={t("nodes.roleExit")}
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(Number(e.target.value))}
                      >
                        {exitNodes.map((n) => (
                          <option key={n.id} value={n.id as number}>
                            {n.name}
                          </option>
                        ))}
                      </Select>
                    )}
                  />
                  <Controller
                    name={`cascade_routes.${idx}.cascade_inbound_tag`}
                    control={form.control}
                    render={({ field }) => {
                      const selectedExitId = form.watch(
                        `cascade_routes.${idx}.exit_node_id`
                      );
                      const exitNode = exitNodes.find(
                        (n) => n.id === Number(selectedExitId)
                      );
                      const exitInbounds = exitNode?.inbounds ?? inboundTags;
                      return (
                        <Select
                          size="sm"
                          placeholder={t("nodes.cascadeInbound")}
                          {...field}
                        >
                          {exitInbounds.map((tag) => (
                            <option key={tag} value={tag}>
                              {tag}
                            </option>
                          ))}
                        </Select>
                      );
                    }}
                  />
                  <Button size="sm" onClick={() => removeRoute(idx)}>
                    ✕
                  </Button>
                </HStack>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  appendRoute({
                    entry_inbound_tag: "",
                    exit_node_id: 0,
                    cascade_inbound_tag: "",
                  })
                }
              >
                {t("nodes.addCascadeRoute")}
              </Button>
            </VStack>
          </FormControl>
        )}
        {addAsHost && (
          <FormControl py={1}>
            <Checkbox {...form.register("add_as_new_host")}>
              <FormLabel m={0}>{t("nodes.addHostForEveryInbound")}</FormLabel>
            </Checkbox>
          </FormControl>
        )}
        <HStack w="full">
          {btnLeftAdornment}
          <Button
            flexGrow={1}
            type="submit"
            colorScheme="primary"
            size="sm"
            px={5}
            w="full"
            isLoading={isLoading}
            {...btnProps}
          >
            {submitBtnText}
          </Button>
        </HStack>
      </VStack>
    </form>
  );
};

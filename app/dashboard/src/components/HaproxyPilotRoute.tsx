import {
  Alert, AlertIcon, Badge, Box, Button, Flex, FormControl, FormLabel,
  HStack, Select, SimpleGrid, Text, VStack,
} from "@chakra-ui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { alreadyEnabled, canRestore, confirmedDestination, recordedDestination, RouteChange, RouteTarget, usePilotRoute } from "service/haproxyPilot";

function endpoint(address: string, port: number) {
  return address.includes(":") ? `[${address}]:${port}` : `${address}:${port}`;
}

export function HaproxyPilotRoute({ nodeId, operator }: { nodeId: number; operator: string }) {
  const { t } = useTranslation();
  const route = usePilotRoute(nodeId, operator);
  const { state, pending, history } = route;
  const [choice, setChoice] = useState("");
  const [disableRequest, setDisableRequest] = useState<{ change: RouteChange; entry: string } | null>(null);
  const active = state && confirmedDestination(state);
  const selected = state?.targets[choice] ? choice : (state?.target && state.targets[state.target] ? state.target : "");
  const confirmation = disableRequest && state?.revision === disableRequest.change.expected_revision
    ? disableRequest : null;
  const unavailable = route.busy || !!pending || state?.listener === "external";
  const locked = unavailable || !!confirmation;
  const targetLabel = (name: string, target: RouteTarget) =>
    `${name} · ${endpoint(target.address, target.port)} · ${t("pilot.exit", { id: target.exit_node_id })} · ${target.inbound_tag}`;
  const modeLabel = (enabled: boolean) => t(enabled ? "pilot.enabled" : "pilot.disabled");

  function requestChange(target: string, enabled: boolean, destination: RouteTarget | null | undefined) {
    if (!state || !destination || locked) return;
    const change = { target, enabled, expected_revision: state.revision, expected_destination: destination };
    if (!enabled && state.enabled) {
      setDisableRequest({ change, entry: endpoint(state.listen_address, state.listen_port) });
    } else {
      route.apply(change);
    }
  }

  return (
    <VStack as="section" aria-label={t("pilot.title")} align="stretch" spacing={3} my={3}
      borderWidth="1px" borderRadius="md" p={3} fontSize="sm">
      <Flex justify="space-between" align="center" gap={2} wrap="wrap">
        <Text as="h3" fontWeight="semibold">{t("pilot.title")}</Text>
        <Button size="xs" variant="outline" onClick={() => { setDisableRequest(null); route.refresh(); }} isDisabled={route.busy}>
          {t("pilot.refresh")}
        </Button>
      </Flex>
      {route.loading && <Text role="status">{t("pilot.loading")}</Text>}
      {route.error && <Alert status="error"><AlertIcon />{route.error}</Alert>}
      {route.supported === false && <Text>{t("pilot.unsupported")}</Text>}
      {!state && !route.loading && route.supported !== false && <Text>{t("pilot.unavailable")}</Text>}
      {state && (
        <>
          <Flex align="center" gap={2} wrap="wrap">
            <Badge colorScheme={state.enabled ? "blue" : "gray"}>{modeLabel(state.enabled)}</Badge>
            <Text>{t("pilot.revision", { revision: state.revision })}</Text>
          </Flex>
          <Box>
            <Text>{t("pilot.entry", { endpoint: endpoint(state.listen_address, state.listen_port) })}</Text>
            {state.target && <Text overflowWrap="anywhere">{t("pilot.current", {
              target: active ? targetLabel(state.target, active) : state.target,
            })}</Text>}
          </Box>
          <SimpleGrid columns={{ base: 1, sm: 3 }} spacing={2}>
            {([
              ["pilot.listener", state.listener], ["pilot.backend", state.backend], ["pilot.vpn", "untested"],
            ] as const).map(([label, value]) => (
              <Box key={label}>
                <Text fontSize="xs">{t(label)}</Text>
                <Badge colorScheme={{up: "green", down: "red", external: "orange", unknown: "gray", untested: "gray"}[value]}>
                  {t(`pilot.${value}`)}
                </Badge>
              </Box>
            ))}
          </SimpleGrid>
          {state.listener === "external" && <Text>{t("pilot.observe")}</Text>}
          <FormControl isDisabled={locked}>
            <FormLabel fontSize="sm">{t("pilot.destination")}</FormLabel>
            <Select size="sm" placeholder={t("pilot.select")} value={selected} onChange={e => setChoice(e.target.value)}>
              {Object.entries(state.targets).map(([name, target]) =>
                <option key={name} value={name}>{targetLabel(name, target)}</option>
              )}
            </Select>
          </FormControl>
          <Flex wrap="wrap" gap={2}>
            <Button colorScheme="primary" size="sm"
              isDisabled={locked || !state.targets[selected] || !!alreadyEnabled(state, selected)}
              onClick={() => requestChange(selected, true, state.targets[selected])}>{t("pilot.apply")}</Button>
            {state.enabled && state.target && <Button size="sm" variant="outline" isDisabled={locked}
              onClick={() => requestChange(state.target!, false, active)}>{t("pilot.disable")}</Button>}
          </Flex>
          {confirmation && <Alert status="warning" alignItems="flex-start">
            <AlertIcon />
            <Box overflowWrap="anywhere">
              <Text fontWeight="medium">{t("pilot.disableWarning")}</Text>
              <Text>{t("pilot.entry", { endpoint: confirmation.entry })} · {t("pilot.revision", { revision: confirmation.change.expected_revision })}</Text>
              <Text>{targetLabel(confirmation.change.target, confirmation.change.expected_destination)}</Text>
              <Flex gap={2} wrap="wrap" mt={2}>
                <Button size="sm" autoFocus onClick={() => setDisableRequest(null)}>{t("cancel")}</Button>
                <Button size="sm" colorScheme="red" isDisabled={unavailable} onClick={() => {
                  route.apply(confirmation.change);
                  setDisableRequest(null);
                }}>{t("pilot.confirmDisable")}</Button>
              </Flex>
            </Box>
          </Alert>}
        </>
      )}
      {pending && <Box role="status" borderLeftWidth="3px" borderColor="orange.400" pl={3}>
        <Text>{t("pilot.awaiting", { target: pending.target, mode: modeLabel(pending.enabled) })}</Text>
        <Text fontSize="xs" fontFamily="mono" overflowWrap="anywhere">{pending.operation_id}</Text>
        <Button size="xs" mt={2} onClick={route.retry} isDisabled={route.busy || route.supported === false}>
          {t("pilot.retry")}
        </Button>
      </Box>}
      {history[0] && (
        <>
          {["rejected", "rollback_failed"].includes(history[0].outcome) &&
            <Alert status="error"><AlertIcon />{t(`pilot.${history[0].outcome}`)}. {history[0].detail}</Alert>}
          <Box as="details">
            <Box as="summary" cursor="pointer" fontWeight="medium">{t("pilot.history")}</Box>
            <VStack as="ol" align="stretch" spacing={2} my={2} listStyleType="none">
              {history.map(record => (
                <Box as="li" key={record.operation_id} borderTopWidth="1px" pt={2} overflowWrap="anywhere">
                  <HStack wrap="wrap">
                    <Badge>{t(`pilot.${record.outcome}`)}</Badge>
                    <Text>{t("pilot.revision", { revision: record.revision ?? "—" })}</Text>
                  </HStack>
                  <Text>{modeLabel(record.enabled)} · {record.target}</Text>
                  <Text fontSize="xs">{record.created_at} · {record.operator}</Text>
                  <Text fontSize="xs" fontFamily="mono">{record.operation_id}</Text>
                  {record.detail && <Text>{record.detail}</Text>}
                  {state && canRestore(record, state) && <Button size="xs" my={1} variant="outline" isDisabled={locked}
                    onClick={() => requestChange(record.target, record.enabled, recordedDestination(record))}>
                    {t("pilot.restore", { revision: record.revision })}
                  </Button>}
                </Box>
              ))}
            </VStack>
          </Box>
        </>
      )}
    </VStack>
  );
}

import { Box, Button, Checkbox, FormControl, FormErrorMessage, FormLabel, HStack, Input, SimpleGrid, Text, VStack } from "@chakra-ui/react";
import { NodeType } from "contexts/NodesContext";
import { Controller, useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Select } from "./constants";
import { balancingDefaults, hasActiveEntryNodes } from "./hostBalancing";

function errorMessages(error: any): string[] {
  if (!error || typeof error !== "object") return [];
  if (typeof error.message === "string") return [error.message];
  return Object.entries(error).flatMap(([key, value]) => key === "ref" ? [] : errorMessages(value));
}

export function HostBalancingOptions({ hostKey, index, nodes, errors }: { hostKey: string; index: number; nodes: NodeType[]; errors: any }) {
  const { t } = useTranslation();
  const { control, register, setValue } = useFormContext();
  const path = `${hostKey}.${index}`;
  const source = useWatch({ control, name: `${path}.balancer_nodes_source` }) || "host";
  const balancing = useWatch({ control, name: `${path}.balancing` });
  const messages = [...errorMessages(errors?.balancing), ...errorMessages(errors?.balancer_node_ids), ...errorMessages(errors?.balancer_nodes_source)];
  const fieldError = (suffix: string) => suffix.split(".").reduce((value, key) => value?.[key], errors?.balancing);
  const textField = (suffix: string, label: string, numeric = false, step?: string) => (
    <FormControl key={suffix} isInvalid={!!fieldError(suffix)}>
      <FormLabel fontSize="sm" htmlFor={`${path}.balancing.${suffix}`}>{label}</FormLabel>
      <Input id={`${path}.balancing.${suffix}`} size="sm" type={numeric ? "number" : "text"} step={step} {...register(`${path}.balancing.${suffix}`, numeric ? { valueAsNumber: true } : {})} />
      <FormErrorMessage>{fieldError(suffix)?.message}</FormErrorMessage>
    </FormControl>
  );
  return (
    <Box gridColumn="1 / -1" borderTopWidth="1px" pt={3}>
      <Text fontWeight="semibold" mb={2}>{t("hostsDialog.balancing.title")}</Text>
      <VStack align="stretch" spacing={3}>
        <FormControl>
          <FormLabel fontSize="sm">{t("hostsDialog.balancing.source")}</FormLabel>
          <Controller control={control} name={`${path}.balancer_nodes_source`} render={({ field }) => (
            <Select size="sm" {...field} value={field.value || "host"}>
              <option value="host">{t("hostsDialog.balancing.hostSource")}</option>
              <option value="selected">{t("hostsDialog.balancing.selectedSource")}</option>
            </Select>
          )} />
        </FormControl>
        {source === "selected" && <>
          <Text fontSize="sm">{t("hostsDialog.balancing.entryHint")}</Text>
          <Controller control={control} name={`${path}.balancer_node_ids`} render={({ field }) => {
            const ids: number[] = field.value || [];
            return <VStack align="stretch" maxH="200px" overflowY="auto">
              {nodes.filter(node => node.id != null).map(node => <Checkbox key={node.id!}
                isChecked={ids.includes(node.id!)} isDisabled={node.status === "disabled" && !ids.includes(node.id!)}
                onChange={e => field.onChange(e.target.checked ? [...ids, node.id!] : ids.filter(id => id !== node.id))}>
                {node.name} ({node.address}){node.status === "disabled" ? ` — ${t("hostsDialog.balancing.disabled")}` : ""}
              </Checkbox>)}
              {!hasActiveEntryNodes(ids, nodes) && <Text color="orange.500" fontSize="sm">{t("hostsDialog.balancing.emptyPool")}</Text>}
            </VStack>;
          }} />
        </>}
        <FormControl>
          <FormLabel fontSize="sm">{t("hostsDialog.balancing.strategy")}</FormLabel>
          <Select size="sm" value={balancing?.strategy || ""} onChange={e => setValue(`${path}.balancing`, balancingDefaults(e.target.value), { shouldDirty: true, shouldValidate: true })}>
            <option value="">{t("hostsDialog.balancing.template")}</option>
            {["random", "roundRobin", "leastPing", "leastLoad"].map(strategy => <option key={strategy} value={strategy}>{strategy}</option>)}
          </Select>
          <Text fontSize="xs" mt={1}>{t("hostsDialog.balancing.strategyHint")}</Text>
          {(balancing?.strategy === "random" || balancing?.strategy === "roundRobin") && <Text fontSize="xs" color="orange.500">{t("hostsDialog.balancing.noHealth")}</Text>}
        </FormControl>
        {balancing?.probe && <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
          {textField("probe.url", t("hostsDialog.balancing.probeUrl"))}
          {textField("probe.interval", t("hostsDialog.balancing.interval"))}
          {balancing.strategy === "leastPing" ? <Controller control={control} name={`${path}.balancing.probe.enableConcurrency`} render={({ field }) => <Checkbox isChecked={field.value} onChange={e => field.onChange(e.target.checked)}>{t("hostsDialog.balancing.concurrency")}</Checkbox>} /> : <>
            {textField("probe.timeout", t("hostsDialog.balancing.timeout"))}
            {textField("probe.sampling", t("hostsDialog.balancing.sampling"), true)}
            {textField("probe.connectivity", t("hostsDialog.balancing.connectivity"))}
          </>}
        </SimpleGrid>}
        {balancing?.strategy === "leastLoad" && <>
          <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
            {textField("settings.expected", "expected", true)}
            {textField("settings.maxRTT", "maxRTT")}
            {textField("settings.tolerance", "tolerance", true, "any")}
          </SimpleGrid>
          <Text fontSize="xs">{t("hostsDialog.balancing.leastLoadHint")}</Text>
          <Box as="details">
            <Box as="summary" cursor="pointer">{t("hostsDialog.balancing.advanced")}</Box>
            <FormControl mt={2}>
              <FormLabel fontSize="sm">{t("hostsDialog.balancing.baselines")}</FormLabel>
              <Controller control={control} name={`${path}.balancing.settings.baselines`} render={({ field }) => <Input size="sm" value={(field.value || []).join(",")} placeholder="200ms,500ms" onChange={e => field.onChange(e.target.value === "" ? [] : e.target.value.split(",").map(value => value.trim()))} />} />
            </FormControl>
            <Controller control={control} name={`${path}.balancing.settings.costs`} render={({ field }) => {
              const costs: { match: string; regexp: boolean; value: number }[] = field.value || [];
              return <VStack align="stretch" mt={3}>
                <Text fontSize="sm">{t("hostsDialog.balancing.costs")}</Text>
                {costs.map((cost, i) => {
                  const update = (value: Partial<typeof cost>) => field.onChange(costs.map((item, j) => j === i ? { ...item, ...value } : item));
                  return <HStack key={i} flexWrap="wrap">
                    <Input size="sm" flex={1} aria-label="match" value={cost.match} onChange={e => update({ match: e.target.value })} placeholder="proxy-1" />
                    <Checkbox isChecked={cost.regexp} onChange={e => update({ regexp: e.target.checked })}>regexp</Checkbox>
                    <Input size="sm" w="90px" type="number" step="any" aria-label="cost" value={Number.isNaN(cost.value) ? "" : cost.value} onChange={e => update({ value: e.target.value === "" ? NaN : Number(e.target.value) })} />
                    <Button size="xs" onClick={() => field.onChange(costs.filter((_, j) => j !== i))}>{t("hostsDialog.balancing.remove")}</Button>
                  </HStack>;
                })}
                <Button size="xs" alignSelf="start" onClick={() => field.onChange([...costs, { match: "proxy", regexp: false, value: 1 }])}>{t("hostsDialog.balancing.addCost")}</Button>
              </VStack>;
            }} />
          </Box>
        </>}
        {!!messages.length && <FormControl isInvalid><FormErrorMessage>{[...new Set(messages)].join("; ")}</FormErrorMessage></FormControl>}
      </VStack>
    </Box>
  );
}

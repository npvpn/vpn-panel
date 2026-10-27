import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  IconButton,
  Input,
  Select,
  Text,
  VStack,
} from "@chakra-ui/react";
import { useHosts } from "contexts/HostsContext";
import { useDashboard } from "contexts/DashboardContext";
import { Controller, useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import {
  InjectionGroup,
  newInjectionGroup,
  previewHost,
  previewExcludedIds,
  previewDraftHosts,
} from "./hostInjection";
import { InjectionDiagnostics } from "./InjectionDiagnostics";
import { InfoHint } from "./InfoHint";
import { DeleteIcon } from "components/DeleteUserModal";
import { PlusIcon } from "@heroicons/react/24/outline";
import { CollapsibleSection } from "./CollapsibleSection";

function messages(error: any): string[] {
  if (!error || typeof error !== "object") return [];
  if (error.message) return [error.message];
  return Object.entries(error).flatMap(([k, v]) =>
    k === "ref" ? [] : messages(v)
  );
}
const move = <T,>(items: T[], index: number, delta: number): T[] => {
  const next = [...items];
  [next[index], next[index + delta]] = [next[index + delta], next[index]];
  return next;
};

export function HostInjectionOptions({
  path,
  errors,
  completeCatalog = false,
}: {
  path: string;
  errors: any;
  completeCatalog?: boolean;
}) {
  const { t } = useTranslation();
  const tr = (key: string) => t(`hostsDialog.injection.${key}`);
  const { control, setValue, register } = useFormContext();
  const row = useWatch({ control, name: path }) || {};
  const rows = useWatch({ control, name: "hosts" }) || [];
  const saved = useHosts((s) => s.hosts);
  const inbounds = useDashboard((s) => s.inbounds);
  const available = new Map<number, any>();
  Object.entries(saved).forEach(([tag, hosts]) =>
    hosts.forEach((host: any) => {
      if (host.id)
        available.set(host.id, { ...host, host_id: host.id, inbound_tag: tag });
    })
  );
  rows.forEach((host: any) => {
    if (host.host_id) available.set(host.host_id, host);
  });
  available.delete(row.host_id);
  const connections = Array.from(inbounds.values()).flat();
  const describe = (host: any) => {
    const inbound = connections.find((i) => i.tag === host.inbound_tag);
    return `${host.inbound_tag} · ${inbound?.network || ""}:${
      host.port || inbound?.port || ""
    } · #${host.host_id}`;
  };
  const inherited = row.host_injection == null;
  const effective = row.host_injection ?? row.template_injection;
  const mode = inherited
    ? "template"
    : row.host_injection.enabled
    ? "form"
    : "off";
  const set = (value: any) =>
    setValue(`${path}.host_injection`, value, {
      shouldDirty: true,
      shouldValidate: true,
    });
  const groups: InjectionGroup[] = row.host_injection?.injectHosts || [];
  const setGroups = (value: InjectionGroup[]) =>
    set({ ...row.host_injection, injectHosts: value });
  const change = (i: number, delta: Partial<InjectionGroup>) =>
    setGroups(groups.map((g, j) => (j === i ? { ...g, ...delta } : g)));
  const errorList = [
    ...messages(errors?.host_injection),
    ...messages(errors?.group_tag),
    ...messages(errors?.is_hidden),
  ];
  // Ошибка — у своего поля, а не общей строкой внизу блока: в длинной форме иначе
  // непонятно, что исправлять. Внизу остаются только ошибки без своего поля
  const shown: string[] = [];
  const fieldErrors = (error: any) => {
    const list = [...new Set(messages(error))];
    shown.push(...list);
    return list.length ? (
      <Text fontSize="xs" color="red.500">
        {list.map((m) => t(m)).join("; ")}
      </Text>
    ) : null;
  };
  const groupError = (i: number, key: string) =>
    fieldErrors(errors?.host_injection?.injectHosts?.[i]?.[key]);
  // свёрнутый блок показывает состояние; открыт сразу, если сборка включена
  const status =
    mode === "form"
      ? t("hostsDialog.injection.status.form", { count: groups.length })
      : mode === "template" && effective?.enabled
      ? tr("status.template")
      : tr("status.off");
  return (
    <CollapsibleSection
      title={tr("title")}
      status={status}
      defaultOpen={!!effective?.enabled}
      hasErrors={errorList.length > 0}
    >
      <VStack align="stretch" spacing={3}>
        <FormControl>
          <FormLabel fontSize="sm">{tr("groupTag")}</FormLabel>
          <Input size="sm" maxLength={128} {...register(`${path}.group_tag`)} />
          {fieldErrors(errors?.group_tag)}
        </FormControl>
        <Controller
          control={control}
          name={`${path}.is_hidden`}
          render={({ field }) => (
            <HStack spacing={1}>
              <Checkbox
                isChecked={!!field.value}
                onChange={(e) => field.onChange(e.target.checked)}
              >
                {tr("hidden")}
              </Checkbox>
              <InfoHint text={tr("visibilityHint")} />
            </HStack>
          )}
        />
        {fieldErrors(errors?.is_hidden)}
        <FormControl>
          <FormLabel fontSize="sm" display="flex" alignItems="center" gap={1}>
            {tr("source")}
            <InfoHint text={tr("priority")} />
          </FormLabel>
          <Select
            size="sm"
            value={mode}
            onChange={(e) =>
              set(
                e.target.value === "template"
                  ? null
                  : e.target.value === "off"
                  ? { enabled: false }
                  : {
                      enabled: true,
                      injectHosts: [newInjectionGroup()],
                      addVirtualHostAsOutbound: false,
                    }
              )
            }
          >
            <option value="template">{tr("inherit")}</option>
            <option value="off">{tr("ordinary")}</option>
            <option value="form">{tr("form")}</option>
          </Select>
        </FormControl>
        {inherited && (
          <Text fontSize="sm">
            {effective ? tr("templateActive") : tr("templateInactive")}
          </Text>
        )}
        {effective?.enabled && (
          <Text fontSize="sm">
            {effective.addVirtualHostAsOutbound
              ? tr("ownHint")
              : tr("virtualHint")}{" "}
            {tr("formatHint")}
          </Text>
        )}
        {mode === "form" && (
          <>
            <Checkbox
              isChecked={!!row.host_injection.addVirtualHostAsOutbound}
              onChange={(e) =>
                set({
                  ...row.host_injection,
                  addVirtualHostAsOutbound: e.target.checked,
                })
              }
            >
              {tr("own")}
            </Checkbox>
            {/* «выберите источники или своё подключение» — про группы целиком */}
            {fieldErrors([
              errors?.host_injection?.message && errors.host_injection,
              errors?.host_injection?.injectHosts?.message &&
                errors.host_injection.injectHosts,
              errors?.host_injection?.addVirtualHostAsOutbound,
            ])}
            {groups.map((group, i) => (
              <Box borderWidth="1px" borderRadius="md" p={3} key={i}>
                <HStack mb={2}>
                  <Text flex={1}>
                    {tr("group")} {i + 1}
                  </Text>
                  <Button
                    size="xs"
                    aria-label={tr("up")}
                    isDisabled={i === 0}
                    onClick={() => setGroups(move(groups, i, -1))}
                  >
                    ↑
                  </Button>
                  <Button
                    size="xs"
                    aria-label={tr("down")}
                    isDisabled={i === groups.length - 1}
                    onClick={() => setGroups(move(groups, i, 1))}
                  >
                    ↓
                  </Button>
                  <IconButton
                    aria-label={tr("remove")}
                    size="xs"
                    colorScheme="red"
                    variant="ghost"
                    onClick={() => setGroups(groups.filter((_, j) => i !== j))}
                  >
                    <DeleteIcon />
                  </IconButton>
                </HStack>
                <VStack align="stretch" spacing={2}>
                  <FormControl>
                    <FormLabel fontSize="xs" mb={1}>
                      {tr("selector")}
                    </FormLabel>
                    <Select
                      size="sm"
                      aria-label={tr("selector")}
                      value={group.selector.type}
                      onChange={(e) => {
                        const type = e.target
                          .value as InjectionGroup["selector"]["type"];
                        change(i, {
                          selector:
                            type === "ids"
                              ? { type, values: [] }
                              : type === "sameTagAsRecipient"
                              ? { type }
                              : { type, pattern: "^MAIN$" },
                          selectFrom: type === "ids" ? "ALL" : "HIDDEN",
                        });
                      }}
                    >
                      <option value="ids">{tr("ids")}</option>
                      <option value="tagRegex">{tr("tagRegex")}</option>
                      <option value="remarkRegex">{tr("remarkRegex")}</option>
                      <option value="sameTagAsRecipient">
                        {tr("sameTag")}
                      </option>
                    </Select>
                  </FormControl>
                  {group.selector.type === "ids" ? (
                    <>
                      <Text fontSize="xs">{tr("persistedOnly")}</Text>
                      <VStack align="stretch" maxH="180px" overflowY="auto">
                        {Array.from(available.values()).map((host) => {
                          const ids =
                            group.selector.type === "ids"
                              ? group.selector.values
                              : [];
                          return (
                            <Checkbox
                              key={host.host_id}
                              isDisabled={
                                host.is_disabled && !ids.includes(host.host_id)
                              }
                              isChecked={ids.includes(host.host_id)}
                              onChange={(e) =>
                                change(i, {
                                  selector: {
                                    type: "ids",
                                    values: e.target.checked
                                      ? [...ids, host.host_id]
                                      : ids.filter((id) => id !== host.host_id),
                                  },
                                })
                              }
                            >
                              {/* название — главное; инбаунд, порт и номер мельче,
                                  иначе соседние хосты различались только «#id» в конце */}
                              <Text>{host.remark}</Text>
                              <Text
                                fontSize="sm"
                                color="gray.600"
                                _dark={{ color: "gray.300" }}
                              >
                                {describe(host)}
                                {host.is_disabled ? ` · ${tr("disabled")}` : ""}
                              </Text>
                            </Checkbox>
                          );
                        })}
                      </VStack>
                      {group.selector.values.map((id, j) => (
                        <HStack key={id}>
                          <Text fontSize="xs" flex={1}>
                            {available.has(id)
                              ? available.get(id).remark
                              : `#${id}: ${tr("missing")}`}
                          </Text>
                          <Button
                            size="xs"
                            isDisabled={j === 0}
                            aria-label={tr("up")}
                            onClick={() =>
                              group.selector.type === "ids" &&
                              change(i, {
                                selector: {
                                  type: "ids",
                                  values: move(group.selector.values, j, -1),
                                },
                              })
                            }
                          >
                            ↑
                          </Button>
                          <Button
                            size="xs"
                            isDisabled={
                              group.selector.type !== "ids" ||
                              j === group.selector.values.length - 1
                            }
                            aria-label={tr("down")}
                            onClick={() =>
                              group.selector.type === "ids" &&
                              change(i, {
                                selector: {
                                  type: "ids",
                                  values: move(group.selector.values, j, 1),
                                },
                              })
                            }
                          >
                            ↓
                          </Button>
                          <IconButton
                            aria-label={tr("remove")}
                            size="xs"
                            colorScheme="red"
                            variant="ghost"
                            onClick={() =>
                              group.selector.type === "ids" &&
                              change(i, {
                                selector: {
                                  type: "ids",
                                  values: group.selector.values.filter(
                                    (v) => v !== id
                                  ),
                                },
                              })
                            }
                          >
                            <DeleteIcon />
                          </IconButton>
                        </HStack>
                      ))}
                    </>
                  ) : group.selector.type !== "sameTagAsRecipient" ? (
                    <Input
                      size="sm"
                      aria-label={tr("pattern")}
                      value={group.selector.pattern}
                      onChange={(e) =>
                        change(i, {
                          selector: {
                            type: group.selector.type as
                              | "tagRegex"
                              | "remarkRegex",
                            pattern: e.target.value,
                          },
                        })
                      }
                      placeholder="^MAIN$"
                    />
                  ) : (
                    !row.group_tag && (
                      <Text fontSize="xs" color="orange.500">
                        {tr("emptyTag")}
                      </Text>
                    )
                  )}
                  {/* ошибка выбора — под полем выбора (список хостов или выражение) */}
                  {groupError(i, "selector")}
                  <FormControl>
                    <FormLabel fontSize="xs" mb={1}>
                      {tr("pool")}
                    </FormLabel>
                    <Select
                      size="sm"
                      aria-label={tr("pool")}
                      value={group.selectFrom}
                      onChange={(e) =>
                        change(i, {
                          selectFrom: e.target
                            .value as InjectionGroup["selectFrom"],
                        })
                      }
                    >
                      <option value="HIDDEN">{tr("poolHidden")}</option>
                      <option value="NOT_HIDDEN">{tr("poolVisible")}</option>
                      <option value="ALL">{tr("poolAll")}</option>
                    </Select>
                  </FormControl>
                  {groupError(i, "selectFrom")}
                  <FormControl>
                    <FormLabel fontSize="xs" mb={1}>
                      {tr("tagging")}
                    </FormLabel>
                    <Select
                      size="sm"
                      aria-label={tr("tagging")}
                      value={
                        group.tagPrefix != null
                          ? "prefix"
                          : group.useHostTagAsTag
                          ? "tag"
                          : "remark"
                      }
                      onChange={(e) =>
                        change(i, {
                          tagPrefix:
                            e.target.value === "prefix" ? "proxy" : null,
                          useHostTagAsTag: e.target.value === "tag",
                          useHostRemarkAsTag: e.target.value === "remark",
                        })
                      }
                    >
                      <option value="prefix">{tr("prefix")}</option>
                      <option value="tag">{tr("hostTag")}</option>
                      <option value="remark">{tr("hostRemark")}</option>
                    </Select>
                  </FormControl>
                  {group.tagPrefix != null && (
                    <Input
                      size="sm"
                      aria-label={tr("prefix")}
                      value={group.tagPrefix}
                      maxLength={128}
                      onChange={(e) => change(i, { tagPrefix: e.target.value })}
                    />
                  )}
                  {groupError(i, "tagPrefix")}
                  {groupError(i, "useHostTagAsTag")}
                  {groupError(i, "useHostRemarkAsTag")}
                </VStack>
              </Box>
            ))}
            {/* как «Add new host»: видно, что кнопка продолжает список групп,
                а серая «Check sources» ниже — отдельная проверка */}
            <Button
              size="sm"
              alignSelf="start"
              variant="outline"
              colorScheme="primary"
              borderRadius="6px"
              _hover={{ bg: "rgba(57, 111, 228, 0.08)" }}
              _active={{ bg: "rgba(57, 111, 228, 0.16)" }}
              _dark={{
                _hover: { bg: "rgba(116, 154, 236, 0.12)" },
                _active: { bg: "rgba(116, 154, 236, 0.2)" },
              }}
              leftIcon={<PlusIcon width="16px" strokeWidth={2} />}
              isDisabled={groups.length >= 32}
              onClick={() =>
                setGroups([
                  ...groups,
                  {
                    ...newInjectionGroup(),
                    tagPrefix: groups.length
                      ? `group${groups.length + 1}`
                      : "proxy",
                  },
                ])
              }
            >
              {tr("addGroup")}
            </Button>
          </>
        )}
        {(() => {
          const rest = [...new Set(errorList)].filter(
            (m) => !shown.includes(m)
          );
          return rest.length ? (
            <FormControl isInvalid>
              <FormErrorMessage>
                {rest.map((m) => t(m)).join("; ")}
              </FormErrorMessage>
            </FormControl>
          ) : null;
        })()}
        <InjectionDiagnostics
          request={{
            recipient: previewHost(row),
            excluded_host_ids: previewExcludedIds(saved, rows, completeCatalog),
            hosts: previewDraftHosts(rows, completeCatalog),
          }}
        />
      </VStack>
    </CollapsibleSection>
  );
}

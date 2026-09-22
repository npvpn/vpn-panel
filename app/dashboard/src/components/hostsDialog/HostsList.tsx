import {
  VStack,
  Text,
  Box,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  useBreakpointValue,
} from "@chakra-ui/react";
import {
  closestCenter,
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  MeasuringStrategy,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import {
  FC,
  FocusEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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

const dndMeasuring = {
  droppable: { strategy: MeasuringStrategy.BeforeDragging },
};

const pointerSensorOptions = { activationConstraint: { distance: 4 } };
const keyboardSensorOptions = { coordinateGetter: sortableKeyboardCoordinates };
const dndModifiers = [restrictToVerticalAxis];

export type HostColumnWidths = {
  drag: number;
  inbound: number;
  remark: number;
  address: number;
  bot: number;
  enabled: number;
  actions: number;
};

type Props = {
  fields: HostField[];
  inboundTags: string[];
  inboundFilter: string;
  botFilter: string;
  activeOnly: boolean;
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
  botFilter,
  activeOnly,
  search,
  bots,
  nodes,
  inboundMap,
  insert,
  move,
  remove,
}) => {
  const { t } = useTranslation();

  // Computed once here (not per-row) so a freshly-inserted row (e.g. via
  // duplicate) already knows its layout instead of flashing card -> table.
  const isTableView = useBreakpointValue({ base: false, md: true });

  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [tableWidth, setTableWidth] = useState(900);

  useEffect(() => {
    const el = tableContainerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (!width) return;
      setTableWidth((prev) => (Math.abs(width - prev) > 4 ? width : prev));
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const lastColumnWidthsRef = useRef<HostColumnWidths | null>(null);

  const columnWidths = useMemo(() => {
    const DRAG = 32;
    const ENABLED = 56;
    const ACTIONS = 110;
    const flexTotal = Math.max(tableWidth - (DRAG + ENABLED + ACTIONS), 0);

    const next: HostColumnWidths = {
      drag: DRAG,
      inbound: Math.round(flexTotal * 0.16),
      remark: Math.round(flexTotal * 0.36),
      address: Math.round(flexTotal * 0.3),
      bot: Math.round(flexTotal * 0.18),
      enabled: ENABLED,
      actions: ACTIONS,
    };

    const prev = lastColumnWidthsRef.current;
    const unchanged =
      !!prev &&
      prev.drag === next.drag &&
      prev.inbound === next.inbound &&
      prev.remark === next.remark &&
      prev.address === next.address &&
      prev.bot === next.bot &&
      prev.enabled === next.enabled &&
      prev.actions === next.actions;

    if (unchanged) return prev as HostColumnWidths;

    lastColumnWidthsRef.current = next;
    return next;
  }, [tableWidth]);

  const form = useFormContext<z.infer<typeof hostsFormSchema>>();

  const { errors } = form.formState;
  const accordionErrors = errors.hosts;

  const watchNames = useMemo(
    () =>
      fields.flatMap(
        (_, i) =>
          [
            `hosts.${i}.remark`,
            `hosts.${i}.address`,
            `hosts.${i}.inbound_tag`,
            `hosts.${i}.bot_usernames`,
            `hosts.${i}.is_disabled`,
          ] as const
      ),
    [fields.length]
  );

  const watchedValues = useWatch({ control: form.control, name: watchNames });

  const watchedHosts = useMemo(
    () =>
      fields.map((_, i) => ({
        remark: watchedValues?.[i * 5] as string | undefined,
        address: watchedValues?.[i * 5 + 1] as string | undefined,
        inbound_tag: watchedValues?.[i * 5 + 2] as string | undefined,
        bot_usernames: watchedValues?.[i * 5 + 3] as string[] | undefined,
        is_disabled: watchedValues?.[i * 5 + 4] as boolean | undefined,
      })),
    [watchedValues, fields.length]
  );

  const [focusedId, setFocusedId] = useState<string | null>(null);

  const handleFocusCapture = useCallback((e: FocusEvent<HTMLDivElement>) => {
    const rowEl = (e.target as HTMLElement).closest<HTMLElement>(
      "[data-row-id]"
    );
    setFocusedId(rowEl?.dataset.rowId ?? null);
  }, []);

  const handleBlurCapture = useCallback(() => {
    setFocusedId(null);
  }, []);

  const visibleIndexes = useMemo(() => {
    const query = search.trim().toLowerCase();

    return fields
      .map((field, index) => ({ field, index }))
      .filter(({ field, index }) => {
        if (field.id === focusedId) return true;

        const host = watchedHosts?.[index];

        if (!host) return false;

        if (inboundFilter && host.inbound_tag !== inboundFilter) {
          return false;
        }

        if (botFilter) {
          const botUsernames: string[] = host.bot_usernames || [];
          if (botUsernames.length > 0 && !botUsernames.includes(botFilter)) {
            return false;
          }
        }

        if (activeOnly && host.is_disabled) {
          return false;
        }

        if (query) {
          const remark = (host.remark || "").toLowerCase();
          const address = (host.address || "").toLowerCase();
          if (!remark.includes(query) && !address.includes(query)) {
            return false;
          }
        }

        return true;
      })
      .map(({ index }) => index);
  }, [
    fields,
    watchedHosts,
    inboundFilter,
    botFilter,
    activeOnly,
    search,
    focusedId,
  ]);

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

  // Order of the currently visible rows, used as the drag-and-drop item ids
  // (dnd-kit reorders among these; filtered-out rows are left untouched).
  const sortableIds = useMemo(
    () =>
      visibleIndexes
        .map((index) => fields[index]?.id)
        .filter((id): id is string => !!id),
    [visibleIndexes, fields]
  );

  const pointerSensor = useSensor(PointerSensor, pointerSensorOptions);
  const keyboardSensor = useSensor(KeyboardSensor, keyboardSensorOptions);
  const dndSensors = useSensors(pointerSensor, keyboardSensor);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldVisiblePos = sortableIds.indexOf(active.id as string);
      const newVisiblePos = sortableIds.indexOf(over.id as string);
      if (oldVisiblePos < 0 || newVisiblePos < 0) return;

      move(visibleIndexes[oldVisiblePos], visibleIndexes[newVisiblePos]);
    },
    [sortableIds, visibleIndexes, move]
  );

  if (inboundTags.length === 0) {
    return (
      <Text opacity={0.8} fontSize="sm">
        No inbound found. Please check your Xray config file.
      </Text>
    );
  }

  const thBorder = {
    px: 3,
    pb: 1.5,
    textAlign: "center" as const,
    borderBottom: "1px solid",
    borderRight: "1px solid",
    borderColor: "gray.200",
    bg: "white",
    color: "gray.600",
    position: "sticky" as const,
    top: 0,
    zIndex: 1,
    _dark: { borderColor: "gray.600", bg: "gray.700", color: "gray.400" },
  };

  const rows = visibleIndexes.map((index, visiblePos) => {
    const field = fields[index];

    if (!field) return null;

    return (
      <HostRow
        key={field.id}
        id={field.id}
        index={index}
        inboundTag={watchedHosts?.[index]?.inbound_tag ?? ""}
        remark={watchedHosts?.[index]?.remark}
        address={watchedHosts?.[index]?.address}
        botUsernames={watchedHosts?.[index]?.bot_usernames}
        canMoveUp={visiblePos > 0}
        canMoveDown={visiblePos < visibleIndexes.length - 1}
        duplicateHost={duplicateHost}
        moveHostPosition={moveHostPosition}
        removeHost={removeHost}
        bots={bots}
        nodes={nodes}
        inbound={inboundMap.get(watchedHosts?.[index]?.inbound_tag ?? "")}
        accordionErrors={accordionErrors?.[index]}
        proxyHostSecurity={proxyHostSecurity}
        proxyALPN={proxyALPN}
        proxyFingerprint={proxyFingerprint}
        t={t}
        isFirst={visiblePos === 0}
        isTableView={isTableView}
        columnWidths={columnWidths}
      />
    );
  });

  return (
    <Box
      ref={tableContainerRef}
      w="full"
      onFocusCapture={handleFocusCapture}
      onBlurCapture={handleBlurCapture}
    >
      {visibleIndexes.length === 0 ? (
        <Text opacity={0.7} fontSize="sm" py={4} textAlign="center">
          {t("hostsDialog.notFound")}
        </Text>
      ) : isTableView ? (
        <DndContext
          sensors={dndSensors}
          collisionDetection={closestCenter}
          modifiers={dndModifiers}
          measuring={dndMeasuring}
          onDragEnd={handleDragEnd}
        >
          <Table size="sm" variant="unstyled" layout="fixed">
            <colgroup>
              <col style={{ width: `${columnWidths.drag}px` }} />
              <col style={{ width: `${columnWidths.inbound}px` }} />
              <col style={{ width: `${columnWidths.remark}px` }} />
              <col style={{ width: `${columnWidths.address}px` }} />
              <col style={{ width: `${columnWidths.bot}px` }} />
              <col style={{ width: `${columnWidths.enabled}px` }} />
              <col style={{ width: `${columnWidths.actions}px` }} />
            </colgroup>
            <Thead>
              <Tr>
                <Th {...thBorder} w={`${columnWidths.drag}px`} px={1} />
                <Th {...thBorder} w={`${columnWidths.inbound}px`}>
                  {t("hostsDialog.columnInbound")}
                </Th>
                <Th {...thBorder} w={`${columnWidths.remark}px`}>
                  Remark
                </Th>
                <Th {...thBorder} w={`${columnWidths.address}px`}>
                  Address
                </Th>
                <Th {...thBorder} w={`${columnWidths.bot}px`}>
                  {t("hostsDialog.columnBot")}
                </Th>
                <Th
                  {...thBorder}
                  w={`${columnWidths.enabled}px`}
                  whiteSpace="nowrap"
                >
                  {t("hostsDialog.columnEnabled")}
                </Th>
                <Th
                  {...thBorder}
                  w={`${columnWidths.actions}px`}
                  textAlign="right"
                >
                  {t("hostsDialog.columnActions")}
                </Th>
              </Tr>
            </Thead>
            <SortableContext
              items={sortableIds}
              strategy={verticalListSortingStrategy}
            >
              <Tbody>{rows}</Tbody>
            </SortableContext>
          </Table>
        </DndContext>
      ) : (
        <VStack align="stretch" spacing={2}>
          {rows}
        </VStack>
      )}
    </Box>
  );
};

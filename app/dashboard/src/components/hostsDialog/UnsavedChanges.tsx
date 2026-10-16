import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Box,
  BoxProps,
  Button,
  HStack,
} from "@chakra-ui/react";
import { FC, useRef } from "react";
import { Control, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { isSameHostValues } from "./hostValues";
import { hostsFormSchema } from "./schema";

type HostsForm = z.infer<typeof hostsFormSchema>;

// NPVPN-2215: пометка и переспрос о несохранённых изменениях — общие для
// окна настроек хоста и всего диалога хостов.

// Пометка «● Есть несохранённые изменения» у кнопок сохранения, пока
// значения отличаются от точки отсчёта (baseline) — как в настройках бота в
// админке (NPVPN-2067). Текстом, а не голой точкой: точку без подсказки не
// понять, а подсказки на телефоне не увидеть. Отдельный компонент: useWatch
// перерисовывает на каждое нажатие клавиши только его, а не окно целиком.
export const UnsavedChangesNote: FC<
  {
    control: Control<HostsForm>;
    name: "hosts" | `hosts.${number}`;
    baseline: unknown;
  } & BoxProps
> = ({ control, name, baseline, ...boxProps }) => {
  const { t } = useTranslation();
  const current = useWatch({ control, name });

  if (isSameHostValues(current, baseline)) return null;

  return (
    <HStack
      as="span"
      role="status"
      spacing={2}
      fontSize="sm"
      color="gray.600"
      _dark={{ color: "gray.400" }}
      {...boxProps}
    >
      <Box
        as="span"
        w="6px"
        h="6px"
        borderRadius="full"
        bg="orange.400"
        flexShrink={0}
      />
      <span>{t("hostsDialog.unsaved.note")}</span>
    </HStack>
  );
};

// «Не сохранять» отдельно слева, подальше от основных действий; основное —
// сохранение — в правом краю. Подписи короткие, чтобы всё помещалось в одну
// строку.
export const UnsavedChangesDialog: FC<{
  isOpen: boolean;
  body: string;
  saveLabel: string;
  onStay: () => void;
  onDiscard: () => void;
  onSave: () => void;
}> = ({ isOpen, body, saveLabel, onStay, onDiscard, onSave }) => {
  const { t } = useTranslation();
  const stayButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <AlertDialog
      isOpen={isOpen}
      leastDestructiveRef={stayButtonRef}
      onClose={onStay}
      isCentered
    >
      {/* Затемнение плотнее, чем у окон под ним, плюс рамка и тень: в тёмной
          теме фон вопроса совпадал с окном, и вопрос с ним сливался.
          Фон в _dark задан явно: проп _dark заменяет тёмные стили темы
          целиком, без bg окно в тёмной теме становилось белым. */}
      <AlertDialogOverlay bg="blackAlpha.600" backdropFilter="blur(2px)" />
      <AlertDialogContent
        mx={3}
        bg="white"
        borderWidth="1px"
        borderColor="gray.200"
        boxShadow="xl"
        _dark={{
          bg: "gray.700",
          borderColor: "gray.600",
          boxShadow: "dark-lg",
        }}
      >
        <AlertDialogHeader fontSize="md" pb={2}>
          {t("hostsDialog.unsaved.title")}
        </AlertDialogHeader>
        <AlertDialogBody fontSize="sm">{body}</AlertDialogBody>
        <AlertDialogFooter gap={2}>
          <Button
            variant="outline"
            colorScheme="red"
            size="sm"
            mr="auto"
            onClick={onDiscard}
          >
            {t("hostsDialog.unsaved.discard")}
          </Button>
          <Button
            ref={stayButtonRef}
            variant="ghost"
            size="sm"
            onClick={onStay}
          >
            {t("hostsDialog.unsaved.stay")}
          </Button>
          <Button
            variant="solid"
            colorScheme="primary"
            size="sm"
            onClick={onSave}
          >
            {saveLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

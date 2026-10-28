import {
  Button,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Text,
} from "@chakra-ui/react";
import { FC, useEffect, useState } from "react";
import { useFormContext } from "react-hook-form";
import { z } from "zod";
import {
  HostAdvancedOptions,
  HostAdvancedOptionsProps,
} from "./HostAdvancedOptions";
import { thinScrollbarSx } from "utils/thinScrollbar";
import { isSameHostValues } from "./hostValues";
import { hostItemSchema, hostsFormSchema } from "./schema";
import { UnsavedChangesDialog, UnsavedChangesNote } from "./UnsavedChanges";

type HostValues = z.infer<typeof hostItemSchema>;
type HostsForm = z.infer<typeof hostsFormSchema>;

type Props = HostAdvancedOptionsProps & {
  isOpen: boolean;
  onClose: () => void;
  // Сохраняет всю форму хостов, не закрывая диалог; true — сохранено.
  // Нет у формы добавления хоста: хост там ещё не в списке, сохранять
  // нечего — вместо этого кнопка «Готово», которая просто закрывает окно.
  onSaveAndContinue?: () => Promise<boolean>;
  remark?: string;
};

// NPVPN-2215: раньше у окна не было кнопок, кроме крестика, и правки
// «схлопывались» без следа. Теперь:
// - внизу явные действия: «Отмена» возвращает хост к значениям на момент
//   открытия, «Применить и продолжить» сохраняет все хосты (как одноимённая
//   кнопка диалога) и закрывает только это окно;
// - изменённый хост помечен «● Есть несохранённые изменения» у кнопок;
// - закрытие с изменениями (клик мимо, крестик, Esc) переспрашивает.
export const HostAdvancedOptionsModal: FC<Props> = ({
  isOpen,
  onClose,
  onSaveAndContinue,
  remark,
  ...advancedOptionsProps
}) => {
  const { t, index } = advancedOptionsProps;
  const form = useFormContext<HostsForm>();

  const [snapshot, setSnapshot] = useState<HostValues | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);

  useEffect(() => {
    // Снимок — только в момент открытия: index меняется при перестановке
    // строк, но открытое окно в это время модально и перестановку не даёт.
    setSnapshot(
      isOpen ? structuredClone(form.getValues(`hosts.${index}`)) : null
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const isDirty = () =>
    !!snapshot && !isSameHostValues(form.getValues(`hosts.${index}`), snapshot);

  const revert = () => {
    if (snapshot) {
      // По полю, а не setValue всего хоста: так обновляются уже
      // зарегистрированные инпуты, и строка не перемонтируется.
      (Object.keys(snapshot) as (keyof HostValues)[]).forEach((key) => {
        form.setValue(`hosts.${index}.${key}`, snapshot[key] as any, {
          shouldDirty: true,
        });
      });
      form.clearErrors(`hosts.${index}`);
    }
  };

  const handleCancel = () => {
    revert();
    onClose();
  };

  const requestClose = () => {
    if (isDirty()) {
      setIsConfirmOpen(true);
    } else {
      onClose();
    }
  };

  const handleSave = async () => {
    if (!onSaveAndContinue) {
      onClose();
      return;
    }

    setIsSaving(true);

    try {
      if (await onSaveAndContinue()) {
        onClose();
      }
    } finally {
      setIsSaving(false);
    }
  };

  const handleConfirmSave = async () => {
    setIsConfirmOpen(false);
    await handleSave();
  };

  const handleConfirmDiscard = () => {
    setIsConfirmOpen(false);
    handleCancel();
  };

  const saveLabel = onSaveAndContinue
    ? t("hostsDialog.applyAndContinue")
    : t("hostsDialog.advancedDone");

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={requestClose}
        size={{ base: "full", md: "2xl" }}
        scrollBehavior="inside"
      >
        <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
        <ModalContent maxH="90vh">
          <ModalHeader pr={12}>
            {t("hostsDialog.advancedOptions")}
            {/* какой хост открыт — видно всегда, и на «Подключении» Remark
                можно не искать (NPVPN-2302) */}
            {remark && (
              <Text
                as="span"
                display="block"
                fontSize="sm"
                fontWeight="normal"
                opacity={0.6}
                mt={1}
                isTruncated
              >
                {remark}
              </Text>
            )}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody
            pb={2}
            sx={{ overscrollBehavior: "contain", ...thinScrollbarSx }}
          >
            <HostAdvancedOptions {...advancedOptionsProps} />
          </ModalBody>
          <ModalFooter gap={2}>
            {snapshot && (
              <UnsavedChangesNote
                control={form.control}
                name={`hosts.${index}`}
                baseline={snapshot}
                mr="auto"
              />
            )}
            <Button
              variant="outline"
              size="sm"
              px={5}
              isDisabled={isSaving}
              onClick={handleCancel}
            >
              {t("cancel")}
            </Button>
            <Button
              variant="solid"
              colorScheme="primary"
              size="sm"
              px={5}
              isLoading={isSaving}
              onClick={handleSave}
            >
              {saveLabel}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <UnsavedChangesDialog
        isOpen={isConfirmOpen}
        body={t("hostsDialog.unsaved.body")}
        saveLabel={
          onSaveAndContinue ? t("apply") : t("hostsDialog.advancedDone")
        }
        onStay={() => setIsConfirmOpen(false)}
        onDiscard={handleConfirmDiscard}
        onSave={handleConfirmSave}
      />
    </>
  );
};

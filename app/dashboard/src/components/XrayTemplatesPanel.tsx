import {
  Alert,
  AlertDescription,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Badge,
  Box,
  Button,
  Collapse,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  HStack,
  IconButton,
  Input,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  UseRadioProps,
  useColorModeValue,
  useRadio,
  useRadioGroup,
  useToast,
  VStack,
  chakra,
} from "@chakra-ui/react";
import {
  ChevronDownIcon,
  PlusIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import dayjs from "dayjs";
import { FC, useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import {
  XrayTemplateDocument,
  XrayTemplateVersionMeta,
  createConfig,
  getVersion,
  listTemplates,
  listVersions,
  restoreConfig,
  revertTemplate,
  saveTemplate,
} from "service/xrayTemplates";
import { ArchiveConfigModal } from "./ArchiveConfigModal";
import { JsonEditor } from "./JsonEditor";
import { TemplateInjectionDiagnostics } from "./hostsDialog/InjectionDiagnostics";

const CloseIcon = chakra(XMarkIcon, { baseStyle: { w: 3.5, h: 3.5 } });

const parseBody = (body: string): any => {
  try {
    return JSON.parse(body);
  } catch {
    return {};
  }
};

// Пустой документ показывается в JsonEditor как {} (редактору нужен объект), и любое
// касание редактора отдаёт onChangeText("{}"). Сохранить такое — значит превратить
// «тело не заполнено, фолбэк на дефолтный конфиг» в «конфиг пустой»: серверы этого
// конфига молча получили бы пустышку вместо рабочего конфига. Поэтому объект без
// единого ключа сохраняем как пустое тело. Задать серверам заведомо пустой конфиг
// через этот редактор нельзя — это осознанный размен.
const normalizeBody = (body: string): string => {
  if (!body.trim()) return "";
  try {
    const parsed = JSON.parse(body);
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      Object.keys(parsed).length === 0
    ) {
      return "";
    }
  } catch {
    // невалидный JSON — отдаём как есть, ошибку покажет 422 от бэка
  }
  return body;
};

// Конфиг — «пилюля» в переносящемся ряду, и при этом радиокнопка, а не Box с onClick.
// Способ взят из UsageFilter: скрытый нативный <input> внутри <label> + оформление на
// getRadioProps(). Так группа попадает в таб-порядок одной остановкой, между пилюлями
// ходят стрелки, состояние «выбран» читает скринридер, а бейдж и крестик внутри пилюли
// остаются произвольной вёрсткой (ради неё и ушёл <select>).
//
// Два состояния намеренно оформлены по-разному, чтобы фокус не выдавал себя за выбор:
// ВЫБРАН — заливка акцентом (primary.500 + белый текст) в обеих темах; ФОКУС — тонкое
// кольцо-outline с отступом снаружи пилюли, только по клавиатуре (_focusVisible).
//
// Кнопка архивации лежит СНАРУЖИ <label> (позиционируется поверх правого края пилюли):
// внутри <label> клик по ней заодно переключал бы радио. Архивный конфиг — та же
// пилюля в той же радиогруппе, но приглушённая, с пунктиром и без крестика (NPVPN-2366).
const ConfigPill: FC<
  UseRadioProps & {
    doc: XrayTemplateDocument;
    onArchive: (doc: XrayTemplateDocument) => void;
    isHighlighted?: boolean;
  }
> = ({ doc, onArchive, isHighlighted = false, ...radioProps }) => {
  const { t } = useTranslation();
  const { getInputProps, getRadioProps, state } = useRadio(radioProps);
  const idleBorder = useColorModeValue("gray.300", "gray.600");
  const idleHoverBg = useColorModeValue("gray.100", "whiteAlpha.200");
  const focusRing = useColorModeValue("gray.700", "gray.200");
  const archiveColor = useColorModeValue("gray.500", "gray.400");
  const isChecked = state.isChecked;
  const isArchived = doc.archived_at != null;
  const canArchive = doc.archivable && !isArchived;

  return (
    <Box position="relative" display="inline-flex">
      <Box as="label" maxW="100%">
        <input {...getInputProps()} />
        <HStack
          {...getRadioProps()}
          spacing={2}
          pl={3}
          pr={canArchive ? 8 : 3}
          py={1}
          borderWidth="1px"
          borderStyle={isArchived && !isHighlighted ? "dashed" : "solid"}
          borderColor={isHighlighted ? "orange.400" : idleBorder}
          boxShadow={isHighlighted ? "0 0 0 3px var(--chakra-colors-orange-200)" : undefined}
          transition="box-shadow 0.3s, border-color 0.3s"
          color={isArchived ? archiveColor : undefined}
          borderRadius="full"
          cursor="pointer"
          _hover={{ bg: idleHoverBg }}
          _checked={{
            bg: "primary.500",
            color: "white",
            borderColor: "primary.500",
            _hover: { bg: "primary.500" },
          }}
          _focusVisible={{
            outline: "2px solid",
            outlineColor: focusRing,
            outlineOffset: "2px",
          }}
        >
          <Text fontSize="sm" noOfLines={1}>
            {doc.title}
          </Text>
          {!doc.archivable && (
            <Badge
              colorScheme="primary"
              fontSize="0.65rem"
              // на выбранной синей кнопке полупрозрачный бейдж сливался с фоном
              {...(isChecked && { bg: "white", color: "primary.600" })}
            >
              {t("panelSettings.xrayTemplates.defaultBadge")}
            </Badge>
          )}
        </HStack>
      </Box>
      {canArchive && (
        <Tooltip label={t("panelSettings.xrayTemplates.archiveConfig")}>
          <IconButton
            aria-label={`${t("panelSettings.xrayTemplates.archiveConfig")}: ${
              doc.title
            }`}
            icon={<CloseIcon />}
            size="xs"
            variant="ghost"
            borderRadius="full"
            position="absolute"
            right="1"
            top="50%"
            transform="translateY(-50%)"
            color={isChecked ? "white" : archiveColor}
            _hover={{
              bg: isChecked ? "whiteAlpha.300" : idleHoverBg,
              color: isChecked ? "white" : "red.500",
            }}
            onClick={() => onArchive(doc)}
          />
        </Tooltip>
      )}
    </Box>
  );
};

type XrayTemplatesPanelProps = {
  // Окно настроек спрашивает «Закрыть без сохранения?» и ставит точку на вкладке
  // по этому флагу: сохранение у вкладки своё, без него окно о правках не знало.
  onDirtyChange?: (dirty: boolean) => void;
};

export const XrayTemplatesPanel: FC<XrayTemplatesPanelProps> = ({
  onDirtyChange,
}) => {
  const { t } = useTranslation();
  const toast = useToast();

  const [documents, setDocuments] = useState<XrayTemplateDocument[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [body, setBody] = useState("");
  // Отдельно от `body`: это "снимок", который скармливается JsonEditor как проп `json`.
  // Обновляется только при смене документа/перезагрузке после save/revert — НИКОГДА на
  // каждый keystroke, иначе JSONEditor.update() дёргает aceEditor.setValue() и сбрасывает
  // курсор/незакоммиченный ввод на каждое изменение (см. jsoneditor/src/js/textmode.js).
  const [editorJson, setEditorJson] = useState<any>({});
  const [comment, setComment] = useState("");
  const [versions, setVersions] = useState<XrayTemplateVersionMeta[]>([]);
  const [preview, setPreview] = useState<
    (XrayTemplateVersionMeta & { body: string }) | null
  >(null);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // История свёрнута: иначе её заголовок торчит из-под края модалки,
  // и неочевидно, что ниже есть содержимое.
  const [showHistory, setShowHistory] = useState(false);
  const historyRef = useRef<HTMLDivElement>(null);

  // История раскрывается у нижнего края модалки — докручиваем к ней,
  // иначе после клика её почти не видно.
  useEffect(() => {
    if (showHistory) historyRef.current?.scrollIntoView({ block: "nearest" });
  }, [showHistory]);
  const [validationError, setValidationError] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [archiving, setArchiving] = useState<XrayTemplateDocument | null>(null);
  const [restoring, setRestoring] = useState(false);
  // Конфиг, на который хотят перейти при несохранённых правках, — ждёт подтверждения.
  const [pendingSwitchId, setPendingSwitchId] = useState<number | null>(null);
  const cancelSwitchRef = useRef<HTMLButtonElement>(null);
  // Актуальный выбор для отложенных вызовов (кнопка «Отменить» в тосте живёт
  // секунды, за это время выбор мог смениться — замыкание видело бы старый).
  const selectedIdRef = useRef<number | null>(null);
  selectedIdRef.current = selectedId;
  // Архив свёрнут по умолчанию — список может разрастись; заметность даёт рамка
  // секции со счётчиком.
  const [showArchive, setShowArchive] = useState(false);
  // Архивный конфиг, на который надо указать (занял slug нового) — подсвечивается на пару секунд.
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const helpBg = useColorModeValue("gray.100", "whiteAlpha.100");

  const activeDocuments = documents.filter((d) => d.archived_at == null);
  const archivedDocuments = documents.filter((d) => d.archived_at != null);
  const selectedDoc = documents.find((d) => d.id === selectedId) ?? null;
  // Архивный конфиг только просматривается: правка и откат версий — после восстановления.
  const isArchived = selectedDoc?.archived_at != null;
  // Несохранённое: тело отличается от текущей версии или введён комментарий.
  // normalizeBody с обеих сторон — «{}» и пустое тело считаются одним и тем же.
  const isDirty =
    selectedDoc != null &&
    !isArchived &&
    (normalizeBody(body) !== normalizeBody(selectedDoc.body ?? "") ||
      comment.trim() !== "");

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);
  // Вкладка размонтирована (окно закрыто) — флаг не должен залипнуть в окне.
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  // Группа радио на список конфигов: выбор документа обязан оставаться доступным с
  // клавиатуры (таб в группу, стрелки между строками) — ровно то, что раньше давал
  // нативный <select>.
  const { getRootProps, getRadioProps } = useRadioGroup({
    value: selectedId != null ? String(selectedId) : "",
    onChange: (value) => requestSelectDocument(Number(value)),
  });

  const showErrorToast = (titleKey: string, err?: any) => {
    const detail = err?.response?._data?.detail;
    toast({
      title: t(titleKey),
      description: typeof detail === "string" ? detail : undefined,
      status: "error",
      isClosable: true,
      position: "top",
    });
  };

  // Перечитывает список документов и одним согласованным переходом выставляет
  // selectedId + body + editorJson под ОДИН и тот же документ — так, чтобы не могло
  // возникнуть состояния "выбран документ A, а в редакторе тело документа B".
  // `desiredId` — id, который вызывающий код хочет видеть выбранным после релоада
  // (например, только что созданный документ); если он не передан или отсутствует
  // в свежем списке, приоритет у текущего selectedId (если он ещё существует), иначе
  // берётся первый документ.
  // keepDraft: релоад из-за действия с ДРУГИМ конфигом (архивация крестиком, «Отменить»
  // в тосте) — если выбор не меняется, несохранённый черновик в редакторе не трогаем.
  const loadDocuments = (
    desiredId?: number | null,
    { keepDraft = false }: { keepDraft?: boolean } = {}
  ) => {
    setLoading(true);
    const currentId = selectedIdRef.current;
    return listTemplates()
      .then((docs) => {
        setDocuments(docs);
        const candidates = [desiredId, currentId];
        const next =
          candidates.find(
            (id): id is number => id != null && docs.some((d) => d.id === id)
          ) ??
          docs[0]?.id ??
          null;
        const doc = docs.find((d) => d.id === next);
        setSelectedId(next);
        if (keepDraft && next === currentId) return docs;
        setBody(doc?.body ?? "");
        setEditorJson(parseBody(doc?.body ?? ""));
        setComment("");
        setValidationError(null);
        return docs;
      })
      .catch(() => showErrorToast("panelSettings.loadFailed"))
      .finally(() => setLoading(false));
  };

  const loadVersions = (id: number) => {
    listVersions(id)
      .then(setVersions)
      .catch(() => showErrorToast("panelSettings.loadFailed"));
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  useEffect(() => {
    if (selectedId != null) loadVersions(selectedId);
    setPreview(null);
  }, [selectedId]);

  // Переход на другой конфиг с несохранёнными правками — через подтверждение:
  // иначе черновик молча пропадал бы при клике по соседней пилюле.
  const requestSelectDocument = (id: number) => {
    if (id === selectedId) return;
    if (isDirty) {
      setPendingSwitchId(id);
      return;
    }
    handleSelectDocument(id);
  };

  const handleSelectDocument = (id: number) => {
    setSelectedId(id);
    const doc = documents.find((d) => d.id === id);
    setBody(doc?.body ?? "");
    setEditorJson(parseBody(doc?.body ?? ""));
    setComment("");
    setValidationError(null);
  };

  const handleSave = () => {
    if (selectedId == null) return;
    setSaving(true);
    setValidationError(null);
    saveTemplate(selectedId, normalizeBody(body), comment)
      .then(() => {
        toast({
          title: t("panelSettings.xrayTemplates.saved"),
          status: "success",
          isClosable: true,
          position: "top",
        });
        return loadDocuments(selectedId);
      })
      .then(() => {
        if (selectedId != null) loadVersions(selectedId);
      })
      .catch((err) => {
        const detail = err?.response?._data?.detail;
        if (err?.response?.status === 422) {
          setValidationError(
            typeof detail === "string"
              ? detail
              : t("panelSettings.xrayTemplates.invalidJson")
          );
        } else {
          showErrorToast("panelSettings.saveFailed", err);
        }
      })
      .finally(() => setSaving(false));
  };

  const handleRevert = (version: number) => {
    if (selectedId == null) return;
    revertTemplate(selectedId, version)
      .then(() => {
        toast({
          title: t("panelSettings.xrayTemplates.reverted"),
          status: "success",
          isClosable: true,
          position: "top",
        });
        return loadDocuments(selectedId);
      })
      .then(() => {
        if (selectedId != null) loadVersions(selectedId);
      })
      .catch((err) =>
        showErrorToast("panelSettings.xrayTemplates.revertFailed", err)
      );
  };

  const handleVersionClick = (version: number) => {
    if (selectedId == null) return;
    getVersion(selectedId, version)
      .then(setPreview)
      .catch((err) => showErrorToast("panelSettings.loadFailed", err));
  };

  const handleCreate = () => {
    if (!newSlug.trim() || !newTitle.trim()) return;
    setCreating(true);
    createConfig(newSlug.trim(), newTitle.trim())
      .then((created) => {
        setShowCreateForm(false);
        setNewSlug("");
        setNewTitle("");
        return loadDocuments(created.id);
      })
      .catch((err) => {
        if (err?.response?.status === 409) {
          // Архивный конфиг держит свой slug (иначе после восстановления было бы
          // два одинаковых), но в свёрнутом архиве его не видно — говорим прямо
          // и раскрываем архив, чтобы было видно, какой конфиг занял slug.
          const archivedOwner = archivedDocuments.find(
            (d) => d.slug === newSlug.trim()
          );
          if (archivedOwner) {
            setShowArchive(true);
            setHighlightedId(archivedOwner.id);
            window.setTimeout(() => setHighlightedId(null), 4000);
            toast({
              title: t("panelSettings.xrayTemplates.slugArchived", {
                title: archivedOwner.title,
              }),
              status: "error",
              isClosable: true,
              position: "top",
            });
          } else {
            // Без detail бэка: там по-английски то же самое, что в заголовке.
            showErrorToast("panelSettings.xrayTemplates.slugExists");
          }
        } else {
          showErrorToast("panelSettings.saveFailed", err);
        }
      })
      .finally(() => setCreating(false));
  };

  // Право на архивацию приходит с бэка полем `archivable` — фронт не решает это сам
  // сравнением slug с "default". Сам запрос делает модалка подтверждения.
  const handleArchive = (doc: XrayTemplateDocument) => {
    if (doc.archivable && doc.archived_at == null) setArchiving(doc);
  };

  const restore = (id: number) => {
    setRestoring(true);
    return restoreConfig(id)
      .then(() => {
        toast({
          title: t("panelSettings.xrayTemplates.restored"),
          status: "success",
          isClosable: true,
          position: "top",
        });
        // Восстановили выбранный (кнопка на плашке) — показываем его. Восстановили
        // другой («Отменить» в тосте) — выбор и черновик в редакторе не трогаем.
        const currentId = selectedIdRef.current;
        return currentId === id || currentId == null
          ? loadDocuments(id)
          : loadDocuments(currentId, { keepDraft: true });
      })
      .catch((err) =>
        showErrorToast("panelSettings.xrayTemplates.restoreFailed", err)
      )
      .finally(() => setRestoring(false));
  };

  // Архивация применяется сразу, без «Сохранить», — поэтому сообщаем о ней явно
  // и даём отменить из тоста: передумал или кликнул случайно.
  // Выбор не перескакивает на архивный конфиг: админ остаётся там, где был. Если
  // в архив ушёл как раз выбранный — возвращаемся на конфиг по умолчанию.
  const handleArchived = (id: number) => {
    const title = archiving?.title ?? "";
    setArchiving(null);
    // Ушёл в архив другой конфиг — черновик выбранного сохраняется.
    if (id === selectedId) loadDocuments(defaultDocId());
    else loadDocuments(selectedId, { keepDraft: true });
    const toastId = toast({
      status: "success",
      position: "top",
      duration: 8000,
      isClosable: true,
      title: t("panelSettings.xrayTemplates.archived", { title }),
      description: (
        <Button
          size="xs"
          mt={1}
          variant="outline"
          colorScheme="whiteAlpha"
          color="white"
          onClick={() => {
            toast.close(toastId);
            restore(id);
          }}
        >
          {t("panelSettings.xrayTemplates.undoArchive")}
        </Button>
      ),
    });
  };

  // Сворачивая архив, админ уходит из него: выбор возвращается на конфиг по
  // умолчанию, иначе статус архивного конфига висел бы без видимой пилюли.
  const toggleArchive = () => {
    const fallbackId = defaultDocId();
    if (showArchive && isArchived && fallbackId != null) {
      handleSelectDocument(fallbackId);
    }
    setShowArchive((v) => !v);
  };

  const defaultDocId = () =>
    (activeDocuments.find((d) => !d.archivable) ?? activeDocuments[0])?.id;

  return (
    <VStack spacing={4} align="stretch">
      <FormControl>
        <FormLabel mb={0}>{t("panelSettings.xrayTemplates.config")}</FormLabel>
        {/* Подсказка — к выбору конфига, поэтому сразу под заголовком, а не после
            формы создания, где она читалась как подсказка к slug/названию. */}
        <FormHelperText mt={1} mb={3}>
          {t("panelSettings.xrayTemplates.configHint")}
        </FormHelperText>
        {/* Видов документов больше нет: каждая строка — целый самодостаточный
            конфиг. Дефолтный отличается только тем, что достаётся серверам без
            явного выбора и не удаляется (NPVPN-2024). */}
        {/* Одна радиогруппа на оба ряда: архивный конфиг выбирается так же, как
            активный, — чтобы посмотреть его и восстановить. */}
        <Box {...getRootProps()} aria-label={t("panelSettings.xrayTemplates.config")}>
          <Box display="flex" flexWrap="wrap" alignItems="center" gap={2}>
            {activeDocuments.map((doc) => (
              <ConfigPill
                key={doc.id}
                {...getRadioProps({ value: String(doc.id) })}
                doc={doc}
                onArchive={handleArchive}
              />
            ))}
            {/* Плюс поворачивается в крестик, пока форма открыта, — как «Добавить
                хост» в диалоге хостов. */}
            <Button
              size="sm"
              variant="outline"
              borderRadius="full"
              aria-expanded={showCreateForm}
              leftIcon={
                <PlusIcon
                  width="16px"
                  style={{
                    transform: showCreateForm ? "rotate(45deg)" : "rotate(0deg)",
                    transition: "transform 0.2s ease",
                  }}
                />
              }
              onClick={() => setShowCreateForm((v) => !v)}
            >
              {t("panelSettings.xrayTemplates.newConfig")}
            </Button>
          </Box>
          {/* Форма создания — сразу под кнопкой «Добавить конфиг», к которой
              относится, а не между архивом и его статусом. */}
          <Collapse in={showCreateForm} animateOpacity>
            {/* Отступ внутри Collapse: он режет overflow, и без него кольцо фокуса
                у полей обрезалось. */}
            <HStack mt={2} p="3px">
              <Input
                size="sm"
                placeholder="slug"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
              />
              <Input
                size="sm"
                placeholder={t("panelSettings.xrayTemplates.configTitle")}
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
              <Button
                size="sm"
                flexShrink={0}
                colorScheme="primary"
                isLoading={creating}
                onClick={handleCreate}
              >
                {t("panelSettings.xrayTemplates.create")}
              </Button>
            </HStack>
          </Collapse>
          {/* Архив — отдельная секция в рамке (как группы во вкладке «Сообщения»):
              пилюли и статус выбранного архивного конфига — внутри неё, одним целым. */}
          {archivedDocuments.length > 0 && (
            <Box mt={3} border="1px solid" borderColor="inherit" borderRadius="md" p={3}>
              <Button
                size="xs"
                variant="unstyled"
                display="flex"
                alignItems="center"
                gap={1}
                h="auto"
                fontWeight="semibold"
                color="gray.500"
                textTransform="uppercase"
                letterSpacing="wide"
                onClick={toggleArchive}
                aria-expanded={showArchive}
              >
                {t("panelSettings.xrayTemplates.archiveToggle", {
                  count: archivedDocuments.length,
                })}
                <ChevronDownIcon
                  width={14}
                  height={14}
                  style={{
                    transform: showArchive ? "rotate(180deg)" : "rotate(0deg)",
                  }}
                />
              </Button>
              <Collapse in={showArchive} animateOpacity>
                <Box display="flex" flexWrap="wrap" alignItems="center" gap={2} mt={3} p="3px">
                  {archivedDocuments.map((doc) => (
                    <ConfigPill
                      key={doc.id}
                      {...getRadioProps({ value: String(doc.id) })}
                      doc={doc}
                      onArchive={handleArchive}
                      isHighlighted={highlightedId === doc.id}
                    />
                  ))}
                </Box>
              </Collapse>
              {/* Статус выбранного архивного конфига — не уведомление, а его
                  состояние: не закрывается, уходит при выборе другого конфига
                  или после восстановления. Вне Collapse — виден и при свёрнутом архиве. */}
                {selectedDoc && isArchived && (
                  <Alert status="warning" borderRadius="md" fontSize="sm" mt={3}>
                    <AlertDescription flex="1">
                      {/* Жирным — какой конфиг и что делать, остальное — справочно. */}
                      <Trans
                        // Автор неизвестен — строка без «· автор», а не с прочерком.
                        i18nKey={
                          selectedDoc.archived_by
                            ? "panelSettings.xrayTemplates.archivedBanner"
                            : "panelSettings.xrayTemplates.archivedBannerNoAuthor"
                        }
                        values={{
                          title: selectedDoc.title,
                          date: dayjs(selectedDoc.archived_at).format("YYYY-MM-DD HH:mm"),
                          by: selectedDoc.archived_by,
                        }}
                        components={{ b: <b /> }}
                      />
                      {selectedDoc.hosts.length > 0 && (
                        <Text>
                          {t("panelSettings.xrayTemplates.archivedBannerHosts", {
                            count: selectedDoc.hosts.length,
                          })}
                        </Text>
                      )}
                    </AlertDescription>
                    <Button
                      size="sm"
                      colorScheme="primary"
                      ml={3}
                      flexShrink={0}
                      isLoading={restoring}
                      onClick={() => restore(selectedDoc.id)}
                    >
                      {t("panelSettings.xrayTemplates.restoreConfig")}
                    </Button>
                  </Alert>
                )}
            </Box>
          )}
        </Box>
        <ArchiveConfigModal
          doc={archiving}
          onClose={() => setArchiving(null)}
          onArchived={handleArchived}
        />
        {/* Как «Закрыть без сохранения?» у окна настроек — тот же вид и тексты. */}
        <AlertDialog
          isCentered
          isOpen={pendingSwitchId != null}
          leastDestructiveRef={cancelSwitchRef}
          onClose={() => setPendingSwitchId(null)}
        >
          <AlertDialogOverlay>
            <AlertDialogContent>
              <AlertDialogHeader>
                {t("panelSettings.xrayTemplates.switchTitle")}
              </AlertDialogHeader>
              <AlertDialogBody>
                <Text fontSize="sm">{t("panelSettings.discardHint")}</Text>
              </AlertDialogBody>
              <AlertDialogFooter>
                <Button ref={cancelSwitchRef} onClick={() => setPendingSwitchId(null)}>
                  {t("cancel")}
                </Button>
                <Button
                  colorScheme="red"
                  ml={3}
                  onClick={() => {
                    if (pendingSwitchId != null) handleSelectDocument(pendingSwitchId);
                    setPendingSwitchId(null);
                  }}
                >
                  {t("panelSettings.xrayTemplates.switchConfirm")}
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialogOverlay>
        </AlertDialog>
      </FormControl>

      {/* Справка по JSON — перед редактором, где её и применяют; выделена фоном,
          чтобы не сливаться с полями формы. */}
      <Box as="details" bg={helpBg} borderRadius="md" px={3} py={2}>
        <Box as="summary" cursor="pointer" fontSize="sm">{t("hostsDialog.injection.jsonHelp")}</Box>
        <Text fontSize="sm" mt={2}>{t("hostsDialog.injection.jsonHint")}</Text>
        <Box as="pre" fontSize="xs" overflowX="auto" mt={2}>{JSON.stringify({ npvpn: { injectHosts: [{ selector: { type: "tagRegex", pattern: "^MAIN$" }, tagPrefix: "proxy", selectFrom: "NOT_HIDDEN" }], addVirtualHostAsOutbound: false } }, null, 2)}</Box>
        <Text fontSize="xs">{t("hostsDialog.injection.idsHint")}</Text>
        <Box as="pre" fontSize="xs" overflowX="auto">{'"selector": { "type": "ids", "values": [1, 2] }'}</Box>
      </Box>

      <FormControl isInvalid={!!validationError}>
        <Box minH="220px">
          {/* Архивный — тот же текстовый редактор, но только для чтения: JSON
              можно выделить и скопировать, чтобы взять за основу нового.
              key: опции JsonEditor задаются при создании — пересоздаём при смене. */}
          <JsonEditor
            key={isArchived ? "readonly" : "edit"}
            json={editorJson}
            onChange={setBody}
            readOnly={isArchived}
          />
        </Box>
        {validationError && (
          <FormErrorMessage>{validationError}</FormErrorMessage>
        )}
      </FormControl>

      <FormControl>
        <FormLabel>{t("panelSettings.xrayTemplates.versionComment")}</FormLabel>
        <Input
          size="sm"
          value={comment}
          isDisabled={isArchived}
          placeholder={t("panelSettings.xrayTemplates.versionCommentHint")}
          onChange={(e) => setComment(e.target.value)}
        />
      </FormControl>

      {selectedId != null && (
        <TemplateInjectionDiagnostics
          key={selectedId}
          templateId={selectedId}
          body={normalizeBody(body)}
        />
      )}

      <HStack>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setShowHistory((v) => !v)}
          aria-expanded={showHistory}
          rightIcon={
            <ChevronDownIcon
              width={16}
              height={16}
              style={{
                transform: showHistory ? "rotate(180deg)" : "rotate(0deg)",
              }}
            />
          }
        >
          {t("panelSettings.xrayTemplates.history")}
          <Badge ml={2} borderRadius="full" px={2}>
            {versions.length}
          </Badge>
        </Button>
      </HStack>

      {showHistory && (
        <FormControl ref={historyRef}>
          <Box
            maxH="220px"
            overflowY="auto"
            borderWidth="1px"
            borderRadius="md"
          >
            <Table size="sm">
              <Thead position="sticky" top={0} bg="chakra-body-bg">
                <Tr>
                  <Th>{t("panelSettings.xrayTemplates.version")}</Th>
                  <Th>{t("panelSettings.xrayTemplates.author")}</Th>
                  <Th>{t("panelSettings.xrayTemplates.date")}</Th>
                  <Th>{t("panelSettings.xrayTemplates.comment")}</Th>
                  <Th />
                </Tr>
              </Thead>
              <Tbody>
                {versions.map((v) => (
                  <Tr
                    key={v.version}
                    cursor="pointer"
                    onClick={() => handleVersionClick(v.version)}
                    _hover={{ bg: "gray.50", _dark: { bg: "gray.700" } }}
                  >
                    <Td>{v.version}</Td>
                    <Td>{v.author_username}</Td>
                    <Td>
                      {v.created_at
                        ? dayjs(v.created_at).format("YYYY-MM-DD HH:mm")
                        : ""}
                    </Td>
                    <Td>{v.comment}</Td>
                    <Td>
                      {/* Последняя версия — текущая: откат на неё ничего не меняет
                          и только плодит одинаковые версии, поэтому вместо кнопки метка. */}
                      {v.version === versions[0]?.version ? (
                        <Badge colorScheme="green" variant="subtle">
                          {t("panelSettings.xrayTemplates.currentVersion")}
                        </Badge>
                      ) : !isArchived && (
                        <Button
                          size="xs"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRevert(v.version);
                          }}
                        >
                          {t("panelSettings.xrayTemplates.restore")}
                        </Button>
                      )}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>
          {preview && (
            <Box mt={2}>
              <Text fontSize="xs" opacity={0.7} mb={1}>
                {t("panelSettings.xrayTemplates.version")} {preview.version}
              </Text>
              <Box minH="160px">
                <JsonEditor
                  json={parseBody(preview.body)}
                  onChange={() => undefined}
                  mode="view"
                />
              </Box>
            </Box>
          )}
          <FormHelperText>
            {t("panelSettings.xrayTemplates.historyHint")}
          </FormHelperText>
        </FormControl>
      )}

      {/* Сохранение закреплено внизу, как футер остальных вкладок окна: не надо
          докручивать до кнопки под редактором и историей. sticky внутри
          прокручиваемого ModalBody; фон — как у окна, чтобы контент не просвечивал. */}
      {/* bottom/mb = -0.5rem: у ModalBody нижний отступ 0.5rem, и полоса, прилипая
          к bottom: 0, оставляла под собой щель, где просвечивал контент. */}
      <HStack
        position="sticky"
        bottom="-0.5rem"
        mb="-0.5rem"
        zIndex={2}
        justify="flex-end"
        spacing={3}
        pt={3}
        pb="calc(0.75rem + 0.5rem)"
        borderTopWidth="1px"
        bg="white"
        _dark={{ bg: "gray.700" }}
      >
        {isDirty && (
          <Text fontSize="sm" color="orange.400">
            {t("panelSettings.unsavedChanges")}
          </Text>
        )}
        <Button
          colorScheme="primary"
          isLoading={saving}
          isDisabled={loading || !isDirty}
          onClick={handleSave}
        >
          {t("panelSettings.xrayTemplates.save")}
        </Button>
      </HStack>
    </VStack>
  );
};

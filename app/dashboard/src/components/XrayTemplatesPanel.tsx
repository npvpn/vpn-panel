import {
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
} from "@chakra-ui/react";
import { PlusIcon } from "@heroicons/react/24/outline";
import dayjs from "dayjs";
import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  XrayTemplateDocument,
  XrayTemplateVersionMeta,
  createConfig,
  deleteConfig,
  getVersion,
  listTemplates,
  listVersions,
  revertTemplate,
  saveTemplate,
} from "service/xrayTemplates";
import { DeleteIcon } from "./DeleteUserModal";
import { JsonEditor } from "./JsonEditor";

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
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && Object.keys(parsed).length === 0) {
      return "";
    }
  } catch {
    // невалидный JSON — отдаём как есть, ошибку покажет 422 от бэка
  }
  return body;
};

// Строка списка конфигов — радиокнопка, а не Box с onClick. Способ взят из
// UsageFilter: скрытый нативный <input> внутри <label> + оформление на getRadioProps().
// Так в таб-порядок и под стрелки список попадает сам, состояние «выбран» читает
// скринридер, а бейдж и прочая вёрстка внутри строки остаются произвольными (ради них
// и ушёл <select>). Кнопка удаления намеренно лежит СНАРУЖИ <label>: внутри неё клик
// заодно переключал бы радио.
const ConfigListItem: FC<
  UseRadioProps & {
    doc: XrayTemplateDocument;
    isDeleting: boolean;
    onDelete: (doc: XrayTemplateDocument) => void;
  }
> = ({ doc, isDeleting, onDelete, ...radioProps }) => {
  const { t } = useTranslation();
  const { getInputProps, getRadioProps } = useRadio(radioProps);
  const checkedBg = useColorModeValue("gray.100", "gray.700");

  return (
    <HStack
      spacing={0}
      borderTopWidth="1px"
      _first={{ borderTopWidth: 0 }}
      align="stretch"
    >
      <Box as="label" flexGrow={1} minW={0}>
        <input {...getInputProps()} />
        <HStack
          {...getRadioProps()}
          h="full"
          px={3}
          py={2}
          spacing={2}
          cursor="pointer"
          _checked={{ bg: checkedBg }}
          _focus={{ boxShadow: "outline" }}
        >
          <Text fontSize="sm" noOfLines={1}>
            {doc.title}
          </Text>
          {!doc.deletable && (
            <Badge colorScheme="primary" fontSize="0.65rem">
              {t("panelSettings.xrayTemplates.defaultBadge")}
            </Badge>
          )}
        </HStack>
      </Box>
      {doc.deletable && (
        <Tooltip label={t("panelSettings.xrayTemplates.deleteConfig")}>
          <IconButton
            aria-label={`${t("panelSettings.xrayTemplates.deleteConfig")}: ${
              doc.title
            }`}
            icon={<DeleteIcon />}
            size="xs"
            alignSelf="center"
            mr={2}
            variant="ghost"
            colorScheme="red"
            isLoading={isDeleting}
            onClick={() => onDelete(doc)}
          />
        </Tooltip>
      )}
    </HStack>
  );
};

export const XrayTemplatesPanel: FC = () => {
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
  const [validationError, setValidationError] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Группа радио на список конфигов: выбор документа обязан оставаться доступным с
  // клавиатуры (таб в группу, стрелки между строками) — ровно то, что раньше давал
  // нативный <select>.
  const { getRootProps, getRadioProps } = useRadioGroup({
    value: selectedId != null ? String(selectedId) : "",
    onChange: (value) => handleSelectDocument(Number(value)),
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
  const loadDocuments = (desiredId?: number | null) => {
    setLoading(true);
    return listTemplates()
      .then((docs) => {
        setDocuments(docs);
        const candidates = [desiredId, selectedId];
        const next =
          candidates.find(
            (id): id is number => id != null && docs.some((d) => d.id === id)
          ) ??
          docs[0]?.id ??
          null;
        const doc = docs.find((d) => d.id === next);
        setSelectedId(next);
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
      .catch((err) => showErrorToast("panelSettings.xrayTemplates.revertFailed", err));
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
          showErrorToast("panelSettings.xrayTemplates.slugExists", err);
        } else {
          showErrorToast("panelSettings.saveFailed", err);
        }
      })
      .finally(() => setCreating(false));
  };

  // Право на удаление приходит с бэка полем `deletable` — фронт не решает это сам
  // сравнением slug с "default".
  const handleDelete = (doc: XrayTemplateDocument) => {
    if (!doc.deletable) return;
    setDeletingId(doc.id);
    deleteConfig(doc.id)
      .then(() => loadDocuments())
      .catch((err) => {
        if (err?.response?.status === 409) {
          showErrorToast("panelSettings.xrayTemplates.deleteFailed", err);
        } else {
          showErrorToast("panelSettings.xrayTemplates.deleteGenericFailed", err);
        }
      })
      .finally(() => setDeletingId(null));
  };

  return (
    <VStack spacing={4} align="stretch">
      <FormControl>
        <FormLabel>{t("panelSettings.xrayTemplates.config")}</FormLabel>
        {/* Видов документов больше нет: каждая строка — целый самодостаточный
            конфиг. Дефолтный отличается только тем, что достаётся серверам без
            явного выбора и не удаляется (NPVPN-2024). */}
        <VStack
          {...getRootProps()}
          aria-label={t("panelSettings.xrayTemplates.config")}
          align="stretch"
          spacing={0}
          maxH="180px"
          overflowY="auto"
          borderWidth="1px"
          borderRadius="md"
        >
          {documents.map((doc) => (
            <ConfigListItem
              key={doc.id}
              {...getRadioProps({ value: String(doc.id) })}
              doc={doc}
              isDeleting={deletingId === doc.id}
              onDelete={handleDelete}
            />
          ))}
        </VStack>
        <Button
          mt={2}
          size="sm"
          variant="outline"
          leftIcon={<PlusIcon width="16px" />}
          onClick={() => setShowCreateForm((v) => !v)}
        >
          {t("panelSettings.xrayTemplates.newConfig")}
        </Button>
        <Collapse in={showCreateForm} animateOpacity>
          <HStack mt={2}>
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
              colorScheme="primary"
              isLoading={creating}
              onClick={handleCreate}
            >
              {t("panelSettings.xrayTemplates.create")}
            </Button>
          </HStack>
        </Collapse>
        <FormHelperText>
          {t("panelSettings.xrayTemplates.configHint")}
        </FormHelperText>
      </FormControl>

      <FormControl isInvalid={!!validationError}>
        <Box minH="220px">
          <JsonEditor json={editorJson} onChange={setBody} />
        </Box>
        {validationError && (
          <FormErrorMessage>{validationError}</FormErrorMessage>
        )}
      </FormControl>

      <FormControl>
        <FormLabel>{t("panelSettings.xrayTemplates.comment")}</FormLabel>
        <HStack>
          <Input
            size="sm"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <Button
            size="sm"
            colorScheme="primary"
            isLoading={saving}
            isDisabled={loading || selectedId == null}
            onClick={handleSave}
          >
            {t("panelSettings.xrayTemplates.save")}
          </Button>
        </HStack>
      </FormControl>

      <FormControl>
        <FormLabel>{t("panelSettings.xrayTemplates.history")}</FormLabel>
        <Box maxH="220px" overflowY="auto" borderWidth="1px" borderRadius="md">
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
    </VStack>
  );
};

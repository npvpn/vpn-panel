import {
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
  Select,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
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
  createProfile,
  deleteProfile,
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
// «тело пустое, фолбэк дальше по цепочке» в «routing пустой»: у всех серверов профиля
// routing молча обнулился бы. Поэтому объект без единого ключа сохраняем как пустое
// тело. Задать серверам заведомо пустой routing через этот редактор нельзя — это
// осознанный размен: молча потерять routing целой группы серверов дороже.
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
  const [deleting, setDeleting] = useState(false);

  const selectedDocument = documents.find((d) => d.id === selectedId) || null;

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
    createProfile(newSlug.trim(), newTitle.trim())
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

  const handleDelete = () => {
    if (selectedId == null || !selectedDocument?.deletable) return;
    setDeleting(true);
    deleteProfile(selectedId)
      .then(() => loadDocuments())
      .catch((err) => {
        if (err?.response?.status === 409) {
          showErrorToast("panelSettings.xrayTemplates.deleteFailed", err);
        } else {
          showErrorToast("panelSettings.xrayTemplates.deleteGenericFailed", err);
        }
      })
      .finally(() => setDeleting(false));
  };

  return (
    <VStack spacing={4} align="stretch">
      <FormControl>
        <FormLabel>{t("panelSettings.xrayTemplates.document")}</FormLabel>
        <HStack>
          <Select
            size="sm"
            value={selectedId ?? ""}
            onChange={(e) => handleSelectDocument(Number(e.target.value))}
          >
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title}
              </option>
            ))}
          </Select>
          <Tooltip label={t("panelSettings.xrayTemplates.newProfile")}>
            <IconButton
              aria-label={t("panelSettings.xrayTemplates.newProfile")}
              icon={<PlusIcon width="18px" />}
              size="sm"
              variant="outline"
              onClick={() => setShowCreateForm((v) => !v)}
            />
          </Tooltip>
          <Tooltip label={t("panelSettings.xrayTemplates.deleteProfile")}>
            <IconButton
              aria-label={t("panelSettings.xrayTemplates.deleteProfile")}
              icon={<DeleteIcon />}
              size="sm"
              variant="outline"
              colorScheme="red"
              isDisabled={!selectedDocument?.deletable}
              isLoading={deleting}
              onClick={handleDelete}
            />
          </Tooltip>
        </HStack>
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
              placeholder={t("panelSettings.xrayTemplates.document")}
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <Button
              size="sm"
              colorScheme="primary"
              isLoading={creating}
              onClick={handleCreate}
            >
              {t("panelSettings.xrayTemplates.newProfile")}
            </Button>
          </HStack>
        </Collapse>
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

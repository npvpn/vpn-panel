import {
  Box,
  Button,
  chakra,
  HStack,
  Tooltip,
  useColorModeValue,
  VStack,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  useToast,
} from "@chakra-ui/react";
import {
  ArchiveBoxIcon,
  InformationCircleIcon,
} from "@heroicons/react/24/outline";
import { FC, useState } from "react";
import { useTranslation } from "react-i18next";
import { XrayTemplateDocument, archiveConfig } from "service/xrayTemplates";
import { Icon } from "./Icon";

const ArchiveIcon = chakra(ArchiveBoxIcon, { baseStyle: { w: 5, h: 5 } });
const InfoIcon = chakra(InformationCircleIcon, { baseStyle: { w: 4, h: 4 } });

type ArchiveConfigModalProps = {
  // null — модалка закрыта.
  doc: XrayTemplateDocument | null;
  onClose: () => void;
  onArchived: (id: number) => void;
};

// Подтверждение архивации клиентского конфига (NPVPN-2366). Охват показываем до
// действия: хосты конфига на время архива уйдут на default, но привязку не теряют.
// При ошибке модалка остаётся открытой — админ видит тост и может повторить.
export const ArchiveConfigModal: FC<ArchiveConfigModalProps> = ({
  doc,
  onClose,
  onArchived,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  const hostsBg = useColorModeValue("gray.50", "whiteAlpha.50");

  const handleArchive = () => {
    if (!doc) return;
    setLoading(true);
    archiveConfig(doc.id)
      .then(() => onArchived(doc.id))
      .catch((err) => {
        const detail = err?.response?._data?.detail;
        toast({
          title: t(
            err?.response?.status === 409
              ? "panelSettings.xrayTemplates.archiveFailed"
              : "panelSettings.xrayTemplates.archiveGenericFailed"
          ),
          description: typeof detail === "string" ? detail : undefined,
          status: "error",
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setLoading(false));
  };

  return (
    <Modal isCentered isOpen={!!doc} onClose={onClose} size={{ base: "sm", md: "md" }}>
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3">
        <ModalHeader pt={6}>
          <Icon color="red">
            <ArchiveIcon />
          </Icon>
        </ModalHeader>
        <ModalCloseButton mt={3} />
        <ModalBody>
          <Text fontWeight="semibold" fontSize="lg">
            {t("panelSettings.xrayTemplates.archiveTitle", {
              title: doc?.title,
            })}
          </Text>
          {/* Два стиля на всю модалку: заголовок и обычный текст. Хосты — метками:
              видно, кого именно затронет, а длинные remark не ломают вёрстку. */}
          {/* Подпись и хосты — один блок в рамке: видно, что список относится к ней.
              Хосты столбиком; прокрутка — только если их больше шести. Строкам
              flexShrink=0: иначе при переполнении maxH flex сжимал строки с
              noOfLines (overflow hidden → min-height 0) до нулевой высоты. */}
          {!!doc?.hosts.length && (
            <Box mt={3} borderWidth="1px" borderRadius="md" bg={hostsBg} px={3} py={2}>
              <Text fontSize="sm" _dark={{ color: "gray.400" }} color="gray.600">
                {t("panelSettings.xrayTemplates.archiveHostsEffect", {
                  count: doc.hosts.length,
                })}
              </Text>
              <VStack as="ul" listStyleType="none" align="stretch" spacing={1} mt={2} maxH="180px" overflowY="auto">
                {doc.hosts.map((host, i) => (
                  <Tooltip
                    key={`${host.inbound_tag}-${i}`}
                    label={`${host.remark} · ${host.inbound_tag}`}
                    openDelay={300}
                  >
                    <Text as="li" fontSize="sm" noOfLines={1} flexShrink={0}>
                      {host.remark}
                    </Text>
                  </Tooltip>
                ))}
              </VStack>
            </Box>
          )}
          <HStack mt={3} spacing={2} align="flex-start" _dark={{ color: "gray.400" }} color="gray.600">
            <InfoIcon flexShrink={0} mt="2px" />
            <Text fontSize="sm">
              {t("panelSettings.xrayTemplates.archiveRestoreNote")}
            </Text>
          </HStack>
        </ModalBody>
        <ModalFooter display="flex">
          <Button size="sm" onClick={onClose} mr={3} w="full" variant="outline">
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            w="full"
            colorScheme="red"
            onClick={handleArchive}
            isDisabled={loading}
            leftIcon={loading ? <Spinner size="xs" /> : undefined}
          >
            {t("panelSettings.xrayTemplates.archiveConfirm")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};

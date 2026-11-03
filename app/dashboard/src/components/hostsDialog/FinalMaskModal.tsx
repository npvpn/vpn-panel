import {
  Box,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Text,
} from "@chakra-ui/react";
import { FC, useMemo } from "react";
import { JsonEditor } from "../JsonEditor";
import { Error } from "./constants";

type FinalMaskModalProps = {
  isOpen: boolean;
  onClose: () => void;
  value: string | null | undefined;
  onChange: (value: string) => void;
  error?: string;
  t: (key: string, opts?: any) => string;
};

export const FinalMaskModal: FC<FinalMaskModalProps> = ({
  isOpen,
  onClose,
  value,
  onChange,
  error,
  t,
}) => {
  const initialJson = useMemo(() => {
    if (!value) return {};
    try {
      return JSON.parse(value);
    } catch {
      return {};
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} size={{ base: "full", md: "2xl" }}>
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent h={{ base: "full", md: "80vh" }} maxH="90vh">
        <ModalHeader pr={12}>
          {t("hostsDialog.finalmask")}
          <Text
            as="span"
            display="block"
            fontSize="sm"
            fontWeight="medium"
            color="orange.600"
            _dark={{ color: "orange.300" }}
            mt={1}
          >
            {t("hostsDialog.finalmask.info")}
          </Text>
          <Text as="span" display="block" fontSize="sm" fontWeight="medium" mt={1}>
            {t("hostsDialog.finalmask.info.delay")}
          </Text>
          <Text as="span" display="block" fontSize="sm" fontWeight="medium" mt={1}>
            {t("hostsDialog.finalmask.info.balancer")}
          </Text>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6} display="flex" flexDirection="column">
          <Box position="relative" flex="1">
            <JsonEditor json={initialJson} onChange={onChange} />
          </Box>
          {error && <Error mt={2}>{error}</Error>}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

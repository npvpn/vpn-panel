import {
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
} from "@chakra-ui/react";
import { FC } from "react";
import {
  HostAdvancedOptions,
  HostAdvancedOptionsProps,
} from "./HostAdvancedOptions";

type Props = HostAdvancedOptionsProps & {
  isOpen: boolean;
  onClose: () => void;
  remark?: string;
};

export const HostAdvancedOptionsModal: FC<Props> = ({
  isOpen,
  onClose,
  remark,
  ...advancedOptionsProps
}) => {
  const { t } = advancedOptionsProps;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "full", md: "lg" }}
      scrollBehavior="inside"
    >
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent maxH="90vh">
        <ModalHeader pr={12}>
          {t("hostsDialog.advancedOptions")}
          {remark ? ` — ${remark}` : ""}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6} sx={{ overscrollBehavior: "contain" }}>
          <HostAdvancedOptions {...advancedOptionsProps} />
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};

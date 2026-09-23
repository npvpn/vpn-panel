import {
  Alert,
  AlertIcon,
  Button,
  chakra,
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
import { ArrowsRightLeftIcon } from "@heroicons/react/24/outline";
import { useDashboard } from "contexts/DashboardContext";
import { FC, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Icon } from "./Icon";

export const RotateAddressesIcon = chakra(ArrowsRightLeftIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export type RotateAddressesModalProps = {};

export const RotateAddressesModal: FC<RotateAddressesModalProps> = () => {
  const [loading, setLoading] = useState(false);
  const { rotateAddressesUser: user, rotateAddresses } = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const onClose = () => {
    useDashboard.setState({ rotateAddressesUser: null });
  };
  const onRotate = () => {
    if (user) {
      setLoading(true);
      rotateAddresses(user)
        .then(() => {
          toast({
            title: t("rotateAddresses.success", { username: user.username }),
            status: "success",
            isClosable: true,
            position: "top",
            duration: 3000,
          });
        })
        .catch(() => {
          toast({
            title: t("rotateAddresses.error"),
            status: "error",
            isClosable: true,
            position: "top",
            duration: 3000,
          });
        })
        .finally(() => {
          setLoading(false);
        });
    }
  };
  return (
    <Modal isCentered isOpen={!!user} onClose={onClose} size="sm">
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3">
        <ModalHeader pt={6}>
          <Icon color="blue">
            <RotateAddressesIcon />
          </Icon>
        </ModalHeader>
        <ModalCloseButton mt={3} />
        <ModalBody>
          <Text fontWeight="semibold" fontSize="lg">
            {t("rotateAddresses.title")}
          </Text>
          {user && (
            <Text
              mt={1}
              fontSize="sm"
              _dark={{ color: "gray.400" }}
              color="gray.600"
            >
              <Trans components={{ b: <b /> }}>
                {t("rotateAddresses.prompt", { username: user.username })}
              </Trans>
            </Text>
          )}
          <Alert status="warning" mt={3} borderRadius="md" fontSize="sm">
            <AlertIcon />
            {t("rotateAddresses.warning")}
          </Alert>
        </ModalBody>
        <ModalFooter display="flex">
          <Button size="sm" onClick={onClose} mr={3} w="full" variant="outline">
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            w="full"
            colorScheme="blue"
            onClick={onRotate}
            leftIcon={loading ? <Spinner size="xs" /> : undefined}
          >
            {t("rotateAddresses.confirm")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};

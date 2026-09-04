import {
  Select as ChakraSelect,
  FormErrorMessage,
  chakra,
} from "@chakra-ui/react";

import {
  ArrowDownIcon,
  ArrowUpIcon,
  Cog6ToothIcon,
  DocumentDuplicateIcon,
  LinkIcon,
  InformationCircleIcon,
} from "@heroicons/react/24/outline";

import { Input as CustomInput } from "../Input";

export const DuplicateIcon = chakra(DocumentDuplicateIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const UpIcon = chakra(ArrowUpIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const DownIcon = chakra(ArrowDownIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const Select = chakra(ChakraSelect, {
  baseStyle: {
    bg: "white",
    _dark: {
      bg: "gray.700",
    },
  },
});

export const Input = chakra(CustomInput, {
  baseStyle: {
    bg: "white",
    _dark: {
      bg: "gray.700",
    },
  },
});

export const InfoIcon = chakra(InformationCircleIcon, {
  baseStyle: {
    w: 4,
    h: 4,
    color: "gray.400",
    cursor: "pointer",
  },
});

export const Error = chakra(FormErrorMessage, {
  baseStyle: {
    color: "red.400",
    display: "block",
    textAlign: "left",
    w: "100%",
  },
});

export const ModalIcon = chakra(LinkIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export const GearIcon = chakra(Cog6ToothIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

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
  PencilSquareIcon,
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

export const PencilIcon = chakra(PencilSquareIcon, {
  baseStyle: {
    w: 4,
    h: 4,
  },
});

// Fields edited inside the settings modal rather than inline on a host row.
export const ADVANCED_FIELD_KEYS = [
  "remark",
  "address",
  "port",
  "path",
  "sni",
  "host",
  "mux_enable",
  "allowinsecure",
  "fragment_setting",
  "noise_setting",
  "random_user_agent",
  "security",
  "alpn",
  "fingerprint",
  "use_sni_as_host",
  "xhttp_extra",
  "bot_usernames",
  "node_ids",
] as const;

// Whether the settings-modal gear icon should show its error dot: remark/address
// errors only count when those fields are actually shown inside that modal
// (they're hidden there, in favor of an inline field, when hideRemarkAddress is set).
export const hasAdvancedFieldErrors = (
  accordionErrors: any,
  hideRemarkAddress?: boolean
) =>
  ADVANCED_FIELD_KEYS.some((key) => {
    if (hideRemarkAddress && (key === "remark" || key === "address")) {
      return false;
    }
    return !!accordionErrors?.[key];
  });

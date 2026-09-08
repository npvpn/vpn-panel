import {
  Text,
  Badge,
  Box,
  Popover,
  PopoverBody,
  PopoverContent,
  Portal,
  PopoverTrigger,
  PopoverArrow,
  PopoverCloseButton,
} from "@chakra-ui/react";
import { InfoIcon } from "./constants";

export const HostInfoPopover = ({ t }: { t: any }) => (
  <Popover isLazy placement="right">
    <PopoverTrigger>
      <Box>
        <InfoIcon />
      </Box>
    </PopoverTrigger>

    <Portal>
      <PopoverContent>
        <PopoverArrow />
        <PopoverCloseButton />
        <PopoverBody>
          <Box fontSize="xs">
            <Text pr="20px">{t("hostsDialog.desc")}</Text>
            {[
              ["SERVER_IP", "currentServer"],
              ["SERVER_IPV6", "currentServerv6"],
              ["USERNAME", "username"],
              ["DATA_USAGE", "dataUsage"],
              ["DATA_LEFT", "remainingData"],
              ["DATA_LIMIT", "dataLimit"],
              ["DAYS_LEFT", "remainingDays"],
              ["EXPIRE_DATE", "expireDate"],
              ["JALALI_EXPIRE_DATE", "jalaliExpireDate"],
              ["TIME_LEFT", "remainingTime"],
              ["STATUS_TEXT", "statusText"],
              ["STATUS_EMOJI", "statusEmoji"],
              ["PROTOCOL", "proxyProtocol"],
              ["TRANSPORT", "proxyMethod"],
            ].map(([key, label]) => (
              <Text key={key} mt={1}>
                <Badge>
                  {"{"}
                  {key}
                  {"}"}
                </Badge>{" "}
                {t(`hostsDialog.${label}`)}
              </Text>
            ))}
          </Box>
        </PopoverBody>
      </PopoverContent>
    </Portal>
  </Popover>
);

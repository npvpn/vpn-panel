import {
  Box,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverTrigger,
  Portal,
  Text,
} from "@chakra-ui/react";
import { InfoIcon } from "./constants";

// Справочное пояснение — иконкой «i», а не постоянным текстом: в длинной форме
// постоянные пояснения заслоняли предупреждения и ошибки. Открывается по клику,
// как HostInfoPopover у Remark/Address: подсказки длинные, а наведения на
// тачскрине нет
export const InfoHint = ({ text }: { text: string }) => (
  <Popover isLazy placement="top">
    <PopoverTrigger>
      <Box
        as="button"
        type="button"
        aria-label={text}
        display="inline-flex"
        verticalAlign="middle"
      >
        <InfoIcon w={3.5} h={3.5} />
      </Box>
    </PopoverTrigger>
    <Portal>
      <PopoverContent>
        <PopoverArrow />
        <PopoverCloseButton />
        <PopoverBody>
          <Text
            fontSize="xs"
            fontWeight="normal"
            textTransform="none"
            letterSpacing="normal"
            whiteSpace="normal"
            pr="20px"
          >
            {text}
          </Text>
        </PopoverBody>
      </PopoverContent>
    </Portal>
  </Popover>
);

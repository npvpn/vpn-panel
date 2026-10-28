import { Box, Collapse, HStack, Text } from "@chakra-ui/react";
import { ChevronRightIcon } from "@heroicons/react/24/outline";
import { ReactNode, useEffect, useState } from "react";

// Большой необязательный блок настроек хоста (сборка, балансировка). У большинства
// хостов он не используется — свёрнут в строку с текущим состоянием, чтобы не
// листать мимо него. Открыт сразу, если функция настроена; раскрывается сам при
// ошибке внутри, чтобы её не спрятать
export const CollapsibleSection = ({
  title,
  status,
  defaultOpen,
  hasErrors,
  nested = false,
  children,
}: {
  title: string;
  status: string;
  defaultOpen: boolean;
  hasErrors: boolean;
  // блок внутри другого блока — без линии сверху и с заголовком мельче
  nested?: boolean;
  children: ReactNode;
}) => {
  const [open, setOpen] = useState(defaultOpen || hasErrors);

  useEffect(() => {
    if (hasErrors) setOpen(true);
  }, [hasErrors]);

  return (
    <Box
      gridColumn="1 / -1"
      borderTopWidth={nested ? 0 : "1px"}
      pt={nested ? 0 : 3}
    >
      <HStack
        as="button"
        type="button"
        w="full"
        spacing={2}
        textAlign="left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {/* стрелка перед названием, а не у края окна: так видно, что строка раскрывается */}
        <ChevronRightIcon
          width={16}
          height={16}
          style={{
            flexShrink: 0,
            transform: open ? "rotate(90deg)" : "none",
            transition: "transform 0.2s",
          }}
        />
        <Text
          fontWeight={nested ? "medium" : "semibold"}
          fontSize={nested ? "sm" : undefined}
          flexShrink={0}
        >
          {title}
        </Text>
        <Text fontSize="sm" color="gray.500" flex={1} noOfLines={1}>
          {status}
        </Text>
      </HStack>
      <Collapse in={open} animateOpacity>
        <Box pt={2}>{children}</Box>
      </Collapse>
    </Box>
  );
};

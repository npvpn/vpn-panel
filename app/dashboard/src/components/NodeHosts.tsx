import {
  Alert, AlertIcon, Badge, Box, Button, Flex, Text, VStack,
} from "@chakra-ui/react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeHostRole, useNodeHosts } from "service/nodeHosts";

const previewHostCount = 3;

const roleColors: Record<NodeHostRole, string> = {
  direct: "blue",
  entry: "purple",
  exit: "teal",
  linked: "gray",
};

function RoleBadges({ roles }: { roles: NodeHostRole[] }) {
  const { t } = useTranslation();
  return <>
    {roles.map(role => (
      <Badge key={role} colorScheme={roleColors[role]} textTransform="none">
        {t(`nodeHosts.role.${role}`)}
      </Badge>
    ))}
  </>;
}

export function NodeHosts({ nodeId, operator }: { nodeId: number; operator: string }) {
  const { t } = useTranslation();
  const query = useNodeHosts(nodeId, operator);
  const [showAll, setShowAll] = useState(false);
  const listId = useId();
  const hosts = query.data?.hosts ?? [];
  const incompleteHostIds = query.data?.incomplete_host_ids ?? [];
  const visibleHosts = showAll ? hosts : hosts.slice(0, previewHostCount);

  return (
    <VStack as="section" aria-label={t("nodeHosts.title")} align="stretch" spacing={2}
      my={3} borderWidth="1px" borderRadius="md" p={3} fontSize="sm" overflowWrap="anywhere">
      <Text as="h3" fontWeight="semibold">{t("nodeHosts.title")}</Text>
      {query.isLoading && <Text role="status">{t("nodeHosts.loading")}</Text>}
      {(query.isError || incompleteHostIds.length > 0) && (
        <Alert status={query.isError ? "error" : "warning"} flexWrap="wrap" gap={2}>
          <AlertIcon m={0} />
          <Box flex="1" minW="10rem" fontSize="sm">
            {query.isError && <Text>{t(query.data ? "nodeHosts.refreshError" : "nodeHosts.error")}</Text>}
            {incompleteHostIds.length > 0 && (
              <Text maxH="4.5em" overflowY="auto" tabIndex={0}>
                {t("nodeHosts.incomplete", { ids: incompleteHostIds.map(id => `#${id}`).join(", ") })}
              </Text>
            )}
          </Box>
          <Button size="xs" onClick={() => query.refetch()} isLoading={query.isFetching}>
            {t("nodeHosts.retry")}
          </Button>
        </Alert>
      )}
      {query.isSuccess && hosts.length === 0 && incompleteHostIds.length === 0 && (
        <Text>{t("nodeHosts.empty")}</Text>
      )}
      {hosts.length > 0 && (
        <VStack as="ul" id={listId} align="stretch" listStyleType="none" spacing={2}>
          {visibleHosts.map(host => (
            <Box as="li" key={host.host_id} _notFirst={{ borderTopWidth: "1px", pt: 2 }}>
              <Flex align="baseline" wrap="wrap" gap={2}>
                <Text fontWeight="medium">{host.remark}</Text>
                <Text fontFamily="mono" fontSize="xs">#{host.host_id}</Text>
                {host.is_disabled && <Badge colorScheme="orange">{t("nodeHosts.disabled")}</Badge>}
                <RoleBadges roles={host.roles} />
              </Flex>
              <Text fontSize="xs">{t("nodeHosts.inbound", { tag: host.inbound_tag })}</Text>
              {host.sources.length > 0 && (
                <Box mt={1} ps={2} borderInlineStartWidth="2px">
                  <Text fontSize="xs">{t("nodeHosts.sources")}</Text>
                  {host.sources.map(source => (
                    <Flex key={source.host_id} align="baseline" wrap="wrap" gap={2} fontSize="xs">
                      <Text>{source.remark}</Text>
                      <Text fontFamily="mono">#{source.host_id}</Text>
                      <RoleBadges roles={source.roles} />
                    </Flex>
                  ))}
                </Box>
              )}
            </Box>
          ))}
        </VStack>
      )}
      {hosts.length > previewHostCount && (
        <Button size="xs" variant="outline" alignSelf="flex-start"
          aria-expanded={showAll} aria-controls={listId} onClick={() => setShowAll(!showAll)}>
          {showAll ? t("nodeHosts.showLess") : t("nodeHosts.showAll", { count: hosts.length })}
        </Button>
      )}
    </VStack>
  );
}

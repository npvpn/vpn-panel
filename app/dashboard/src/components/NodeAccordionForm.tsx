import { FC } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  NodeSchema,
  NodeType,
  useNodes,
  FetchNodesQueryKey,
  bytesToTbString,
} from "contexts/NodesContext";
import { useMutation, useQueryClient } from "react-query";
import { useToast, Tooltip, IconButton } from "@chakra-ui/react";
import { useTranslation } from "react-i18next";
import {
  generateErrorMessage,
  generateSuccessMessage,
} from "utils/toastHandler";
import { DeleteIcon } from "./DeleteUserModal";
import { NodeForm } from "./NodeForm";

type Props = {
  node: NodeType;
  nodeSettings?: { min_node_version: string; certificate: string };
  onDelete: () => void;
};

export const NodeAccordionForm: FC<Props> = ({
  node,
  nodeSettings,
  onDelete,
}) => {
  const { updateNode } = useNodes();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToast();

  const form = useForm<NodeType>({
    defaultValues: {
      ...node,
      hosting_traffic_limit_tb: bytesToTbString(node.hosting_traffic_limit_bytes),
    },
    resolver: zodResolver(NodeSchema),
  });

  const { isLoading, mutate } = useMutation(updateNode, {
    onSuccess: () => {
      generateSuccessMessage("Node updated successfully", toast);
      queryClient.invalidateQueries(FetchNodesQueryKey);
    },
    onError: (e) => {
      generateErrorMessage(e, toast, form);
    },
  });

  return (
    <NodeForm
      form={form}
      mutate={mutate}
      isLoading={isLoading}
      nodeSettings={nodeSettings}
      submitBtnText={t("nodes.editNode")}
      btnLeftAdornment={
        <Tooltip label={t("delete")} placement="top">
          <IconButton
            colorScheme="red"
            variant="ghost"
            size="sm"
            aria-label="delete node"
            onClick={onDelete}
          >
            <DeleteIcon />
          </IconButton>
        </Tooltip>
      }
    />
  );
};

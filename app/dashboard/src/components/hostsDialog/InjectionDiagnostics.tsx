import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Select,
  Text,
  VStack,
} from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { previewHost } from "./hostInjection";

type PreviewRequest = {
  recipient: ReturnType<typeof previewHost>;
  hosts?: ReturnType<typeof previewHost>[];
  excluded_host_ids?: number[];
  template_body?: string;
};
type Preview = {
  active: boolean;
  groups: { group: number; host_ids: number[]; pattern: string }[];
  issues: {
    code: string;
    level: "error" | "warning";
    group: number | null;
    host_id: number | null;
    path: string;
  }[];
};

// A new input snapshot remounts the request state: an old result cannot describe a new draft.
export function InjectionDiagnostics({ request }: { request: PreviewRequest }) {
  return <DiagnosticRequest key={JSON.stringify(request)} request={request} />;
}

function DiagnosticRequest({ request }: { request: PreviewRequest }) {
  const { t } = useTranslation();
  const tr = (key: string, values = {}) =>
    t(`hostsDialog.injection.diagnostics.${key}`, values);
  const [result, setResult] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const check = async () => {
    setLoading(true);
    setFailed(false);
    setResult(null);
    try {
      const response = await fetch("/hosts/injection/preview", {
        method: "POST",
        body: request,
      });
      if (alive.current) setResult(response as Preview);
    } catch {
      if (alive.current) setFailed(true);
    } finally {
      if (alive.current) setLoading(false);
    }
  };
  return (
    <VStack align="stretch" spacing={2}>
      <Button size="sm" alignSelf="start" onClick={check} isLoading={loading}>
        {tr("check")}
      </Button>
      <Text fontSize="xs">{tr("scope")}</Text>
      <Box aria-live="polite">
        {failed && (
          <Text role="alert" color="red.500" fontSize="sm">
            {tr("failed")}
          </Text>
        )}
        {result && (
          <>
            {!result.active &&
              !result.issues.some((i) => i.level === "error") && (
                <Text fontSize="sm">{tr("inactive")}</Text>
              )}
            {result.groups.map((g) => (
              <Text fontSize="sm" key={g.group}>
                {tr("group", { group: g.group, count: g.host_ids.length })}
                {g.pattern && ` · ${g.pattern}`}
                {!!g.host_ids.length && ` · #${g.host_ids.join(", #")}`}
              </Text>
            ))}
            {result.issues.map((issue, i) => (
              <Text
                key={i}
                fontSize="sm"
                color={issue.level === "error" ? "red.500" : "orange.500"}
              >
                {issue.group != null &&
                  `${tr("groupNumber", { group: issue.group })}: `}
                {issue.host_id != null && `#${issue.host_id}: `}
                {tr(issue.code)}
                {issue.path && ` (${issue.path})`}
              </Text>
            ))}
            {result.active && !result.issues.length && (
              <Text fontSize="sm">{tr("passed")}</Text>
            )}
          </>
        )}
      </Box>
    </VStack>
  );
}

export function TemplateInjectionDiagnostics({
  templateId,
  body,
}: {
  templateId: number;
  body: string;
}) {
  const { t } = useTranslation();
  const [hosts, setHosts] = useState<ReturnType<typeof previewHost>[]>([]);
  const [selected, setSelected] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch("/hosts")
      .then((data) => {
        if (!alive) return;
        const rows = Object.entries(data as Record<string, any[]>).flatMap(
          ([tag, values]) =>
            values.map((host) => previewHost({ ...host, inbound_tag: tag }))
        );
        setHosts(rows);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);
  const recipient = hosts.find((host) => String(host.id) === selected);
  return (
    <VStack align="stretch" spacing={2}>
      <FormControl>
        <FormLabel fontSize="sm">
          {t("hostsDialog.injection.diagnostics.recipient")}
        </FormLabel>
        <Select
          size="sm"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          placeholder={t("hostsDialog.injection.diagnostics.chooseRecipient")}
        >
          {hosts.map((host) => (
            <option key={host.id} value={host.id ?? ""}>
              {host.remark} · #{host.id}
            </option>
          ))}
        </Select>
      </FormControl>
      {failed && (
        <Text color="red.500" role="alert">
          {t("hostsDialog.injection.diagnostics.failed")}
        </Text>
      )}
      {recipient && (
        <InjectionDiagnostics
          request={{
            recipient: { ...recipient, client_config_id: templateId },
            template_body: body,
          }}
        />
      )}
    </VStack>
  );
}

import { Button, FormControl, FormLabel, Select, Text, VStack } from "@chakra-ui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";

type Entry = {
  source_host_id: number;
  source_name: string;
  node_name: string | null;
  address: string;
};

type Composition = { entries: Entry[]; excluded_by_bot: Entry[] };

function Members({ hostId, bot }: { hostId: number; bot: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<Composition>();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const load = async () => {
    setLoading(true);
    setFailed(false);
    setData(undefined);
    try {
      setData(await fetch<Composition>(`/hosts/${hostId}/composition`, {
        method: "GET", query: bot ? { bot_username: bot } : {},
      }));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };
  const entryLabel = (e: Entry) =>
    `${e.node_name || t("addressPins.unmappedAddress")} · ${e.address} · ${e.source_name} (#${e.source_host_id})`;
  return <VStack align="start">
    <Button size="sm" onClick={load} isLoading={loading}>{t("addressPins.savedComposition")}</Button>
    {failed && <Text role="alert">{t("addressPins.pinnableHostsLoadError")}</Text>}
    {data && !data.entries.length && <Text>{t("addressPins.hostHasNoNodes")}</Text>}
    {data?.entries.map(e => <Text key={entryLabel(e)}>{entryLabel(e)}</Text>)}
    {data?.excluded_by_bot.map(e => <Text key={entryLabel(e)}>{entryLabel(e)} · {t("addressPins.botExcluded")}</Text>)}
  </VStack>;
}

export function SavedHostComposition({ hostId, bots }: { hostId: number; bots: { username: string }[] }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState("");
  const bot = selected || bots[0]?.username || "";
  return <FormControl gridColumn="1 / -1">
    <FormLabel>{t("addressPins.savedComposition")}</FormLabel>
    {bots.length > 0 && <Select size="sm" value={bot} onChange={e => setSelected(e.target.value)}>
      {bots.map(b => <option key={b.username} value={b.username}>{b.username}</option>)}
    </Select>}
    <Members key={`${hostId}/${bot}`} hostId={hostId} bot={bot} />
  </FormControl>;
}

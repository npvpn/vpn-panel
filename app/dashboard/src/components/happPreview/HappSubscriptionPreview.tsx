import {
  FormControl,
  FormLabel,
  HStack,
  Select,
  Text,
  VStack,
} from "@chakra-ui/react";
import { FC, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { Bot, BotSettings } from "types/Bot";
import { PanelSettings } from "types/PanelSettings";
import { NodeType } from "../../contexts/NodesContext";
import {
  flattenHosts,
  HappPreviewHost,
  HappPreviewScenario,
  hostsForBot,
  previewAnnounce,
  previewServers,
  substitutePlaceholders,
} from "./happPreview";
import "./happPreview.css";

const FLAGS = ["🇩🇪", "🇳🇱", "🇫🇮"];

type Props = {
  settings: PanelSettings;
  scenario: HappPreviewScenario;
  onScenarioChange: (scenario: HappPreviewScenario) => void;
};

export const HappSubscriptionPreview: FC<Props> = ({
  settings,
  scenario,
  onScenarioChange,
}) => {
  const { t } = useTranslation();
  const [bots, setBots] = useState<Bot[]>([]);
  const [botUsername, setBotUsername] = useState("");
  const [hostsByInbound, setHostsByInbound] = useState<
    Record<string, HappPreviewHost[]>
  >({});
  const [nodes, setNodes] = useState<NodeType[]>([]);
  const [botSettings, setBotSettings] = useState<BotSettings | null>(null);

  useEffect(() => {
    fetch<Bot[]>("/bots")
      .then((items) => {
        setBots(items);
        setBotUsername((current) => current || items[0]?.username || "");
      })
      .catch(() => setBots([]));
    fetch<Record<string, HappPreviewHost[]>>("/hosts")
      .then((hosts) => setHostsByInbound(hosts || {}))
      .catch(() => setHostsByInbound({}));
    fetch<NodeType[]>("/nodes")
      .then((items) => setNodes(items || []))
      .catch(() => setNodes([]));
  }, []);

  useEffect(() => {
    if (!botUsername) {
      setBotSettings(null);
      return;
    }
    let cancelled = false;
    fetch<BotSettings>(`/bots/${botUsername}/settings`)
      .then((data) => {
        if (!cancelled) setBotSettings(data);
      })
      .catch(() => {
        if (!cancelled) setBotSettings(null);
      });
    return () => {
      cancelled = true;
    };
  }, [botUsername]);

  const bsNodeIds = useMemo(
    () =>
      new Set(
        nodes
          .filter((node) => node.is_bs && node.id != null)
          .map((node) => Number(node.id))
      ),
    [nodes]
  );
  const botHosts = useMemo(
    () => hostsForBot(flattenHosts(hostsByInbound), botUsername, bsNodeIds),
    [hostsByInbound, botUsername, bsNodeIds]
  );
  const servers = useMemo(
    () =>
      previewServers(
        settings,
        scenario,
        botHosts,
        Boolean(botSettings?.sub_device_limit_hard_mode)
      ),
    [settings, scenario, botHosts, botSettings]
  );
  const announce = previewAnnounce(settings, scenario);
  const title =
    substitutePlaceholders(botSettings?.sub_profile_title || "") ||
    bots.find((bot) => bot.username === botUsername)?.title ||
    t("botSettings.subProfileTitle");
  const interval = botSettings?.sub_update_interval || "12";
  const selectedBot = bots.find((bot) => bot.username === botUsername);

  return (
    <VStack className="happ-preview-panel" align="stretch" spacing={3}>
      <HStack justify="space-between" align="flex-start" spacing={2}>
        <Text fontWeight="bold">{t("panelSettings.happPreview")}</Text>
      </HStack>
      <HStack spacing={2}>
        <FormControl>
          <FormLabel fontSize="xs" mb={1}>
            {t("panelSettings.previewBot")}
          </FormLabel>
          <Select
            size="sm"
            value={botUsername}
            onChange={(e) => setBotUsername(e.target.value)}
          >
            {bots.length === 0 && (
              <option value="">{t("panelSettings.previewNoBots")}</option>
            )}
            {bots.map((bot) => (
              <option key={bot.username} value={bot.username}>
                @{bot.username}
                {bot.title ? ` — ${bot.title}` : ""}
              </option>
            ))}
          </Select>
        </FormControl>
        <FormControl>
          <FormLabel fontSize="xs" mb={1}>
            {t("panelSettings.previewScenario")}
          </FormLabel>
          <Select
            size="sm"
            value={scenario}
            onChange={(e) =>
              onScenarioChange(e.target.value as HappPreviewScenario)
            }
          >
            <option value="normal">
              {t("panelSettings.previewScenarioNormal")}
            </option>
            <option value="expired">
              {t("panelSettings.previewScenarioExpired")}
            </option>
            <option value="revoked">
              {t("panelSettings.previewScenarioRevoked")}
            </option>
            <option value="unsupported">
              {t("panelSettings.previewScenarioUnsupported")}
            </option>
            <option value="device">
              {t("panelSettings.previewScenarioDevice")}
            </option>
            <option value="bs">{t("panelSettings.previewScenarioBs")}</option>
          </Select>
        </FormControl>
      </HStack>
      <Text fontSize="sm" color="gray.500">
        {t("panelSettings.previewHint")}
      </Text>

      <div className="happ-preview-phone">
        <div className="happ-preview-phone-top">
          <span>10:24</span>
        </div>
        <div className="happ-preview-toolbar">
          <span>⚙</span>
          <span>＋</span>
        </div>
        <div className="happ-preview-power" aria-hidden="true">
          <span>⏻</span>
        </div>
        <div className="happ-preview-hide">Скрыть все</div>
        <div className="happ-preview-card">
          <div className="happ-preview-card-header">
            <span className="happ-preview-chevron">⌄</span>
            <div className="happ-preview-title-wrap">
              <div className="happ-preview-title">{title}</div>
              <div className="happ-preview-meta">
                24.09.2026 10:24 | Автообновление · {interval} ч.
                {selectedBot ? ` · @${selectedBot.username}` : ""}
              </div>
            </div>
            <span className="happ-preview-actions">
              <span aria-hidden="true">↻</span>
              <svg
                className="happ-preview-speedometer"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path d="M4 15a8 8 0 1 1 16 0"></path>
                <path d="M12 15l4-5"></path>
                <circle cx="12" cy="15" r="1"></circle>
              </svg>
              <span aria-hidden="true">···</span>
            </span>
          </div>
          <div className="happ-preview-usage-row">
            <span className="happ-preview-info">ⓘ</span>
            <div className="happ-preview-usage">0B/53,0GB</div>
            <span>Истекает: 22.12.2026</span>
          </div>
          <div className="happ-preview-announce">
            {announce.trim() || t("panelSettings.previewEmptyAnnounce")}
          </div>
          <div>
            {servers.length === 0 && (
              <div className="happ-preview-server">
                <div className="happ-preview-server-text">
                  <div className="happ-preview-server-name">
                    {t("panelSettings.previewNoHosts")}
                  </div>
                </div>
              </div>
            )}
            {servers.map((server, index) => (
              <div className="happ-preview-server" key={`${server.name}-${index}`}>
                <div className="happ-preview-server-icon">
                  {server.isStub ? "⚠" : FLAGS[index % FLAGS.length]}
                </div>
                <div className="happ-preview-server-text">
                  <div className="happ-preview-server-name">{server.name}</div>
                  <div className="happ-preview-server-protocol">
                    {server.isStub ? "недоступно" : "vless"}
                  </div>
                </div>
                <div className="happ-preview-server-arrow">›</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </VStack>
  );
};

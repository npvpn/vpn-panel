import {
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Textarea,
  VStack,
  useToast,
} from "@chakra-ui/react";
import { useDashboard } from "contexts/DashboardContext";
import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { PanelSettings } from "types/PanelSettings";

const GB_IN_BYTES = 1073741824;

const emptySettings: PanelSettings = {
  sub_custom_headers: "",
  bs_monthly_limit: 0,
  sub_routing_happ: "",
  sub_routing_v2raytun: "",
  sub_v2ray_json_template: "",
  sub_routing_json_default: "",
  sub_routing_json_bs: "",
};

const thinScrollbarSx = {
  "&::-webkit-scrollbar": {
    width: "6px",
  },
  "&::-webkit-scrollbar-track": {
    background: "transparent",
  },
  "&::-webkit-scrollbar-thumb": {
    background: "var(--chakra-colors-gray-300)",
    borderRadius: "full",
  },
  "&::-webkit-scrollbar-thumb:hover": {
    background: "var(--chakra-colors-gray-400)",
  },
  scrollbarWidth: "thin",
  scrollbarColor: "var(--chakra-colors-gray-300) transparent",
} as const;

export const PanelSettingsDialog: FC = () => {
  const { isEditingPanelSettings, onEditingPanelSettings } = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<PanelSettings>(emptySettings);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const showValidationErrorToast = (err: any) => {
    const detail = err?.response?._data?.detail;
    if (detail && typeof detail === "object") {
      Object.keys(detail).forEach((key) => {
        toast({
          title: `${detail[key]} (${key})`,
          status: "error",
          isClosable: true,
          position: "top",
        });
      });
      return;
    }
    toast({
      title: t("panelSettings.saveFailed"),
      description: typeof detail === "string" ? detail : undefined,
      status: "error",
      isClosable: true,
      position: "top",
    });
  };

  useEffect(() => {
    if (!isEditingPanelSettings) return;
    setSettings(emptySettings);
    setLoading(true);
    fetch("/settings/panel")
      .then((data: PanelSettings) => setSettings(data))
      .catch(() =>
        toast({
          title: t("panelSettings.loadFailed"),
          status: "error",
          isClosable: true,
          position: "top",
        })
      )
      .finally(() => setLoading(false));
  }, [isEditingPanelSettings]);

  const updateSettings = (patch: Partial<PanelSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  };

  const resetToDefaults = () => {
    setLoading(true);
    fetch("/settings/panel/defaults")
      .then((data: PanelSettings) => setSettings(data))
      .catch(() =>
        toast({
          title: t("panelSettings.loadFailed"),
          status: "error",
          isClosable: true,
          position: "top",
        })
      )
      .finally(() => setLoading(false));
  };

  const save = () => {
    setSaving(true);
    fetch("/settings/panel", { method: "PUT", body: settings })
      .then((data: PanelSettings) => {
        setSettings(data);
        toast({
          title: t("panelSettings.saved"),
          status: "success",
          isClosable: true,
          position: "top",
        });
        onEditingPanelSettings(false);
      })
      .catch((err) => showValidationErrorToast(err))
      .finally(() => setSaving(false));
  };

  return (
    <Modal
      isOpen={isEditingPanelSettings}
      onClose={() => onEditingPanelSettings(false)}
      size="4xl"
      scrollBehavior="inside"
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>{t("panelSettings.title")}</ModalHeader>
        <ModalCloseButton />
        <ModalBody sx={thinScrollbarSx}>
          <Tabs variant="enclosed" colorScheme="primary">
            <TabList overflowX="auto" overflowY="hidden" whiteSpace="nowrap">
              <Tab>{t("panelSettings.tabSubscription")}</Tab>
              <Tab>{t("panelSettings.tabV2rayJson")}</Tab>
            </TabList>
            <TabPanels>
              <TabPanel px={0}>
                <VStack spacing={4} align="stretch">
                  <FormControl>
                    <FormLabel>{t("panelSettings.subRoutingHapp")}</FormLabel>
                    <Input
                      value={settings.sub_routing_happ}
                      placeholder="happ://"
                      onChange={(e) =>
                        updateSettings({ sub_routing_happ: e.target.value })
                      }
                    />
                  </FormControl>
                  <FormControl>
                    <FormLabel>
                      {t("panelSettings.subRoutingV2raytun")}
                    </FormLabel>
                    <Input
                      value={settings.sub_routing_v2raytun}
                      placeholder="v2ray://"
                      onChange={(e) =>
                        updateSettings({
                          sub_routing_v2raytun: e.target.value,
                        })
                      }
                    />
                  </FormControl>
                  <FormControl>
                    <FormLabel>{t("panelSettings.subCustomHeaders")}</FormLabel>
                    <Textarea
                      value={settings.sub_custom_headers}
                      placeholder={"routing-enable: 0"}
                      onChange={(e) =>
                        updateSettings({ sub_custom_headers: e.target.value })
                      }
                    />
                    <FormHelperText>
                      {t("panelSettings.subCustomHeadersHint")}
                    </FormHelperText>
                  </FormControl>
                  <FormControl>
                    <FormLabel>{t("panelSettings.bsMonthlyLimitGb")}</FormLabel>
                    <Input
                      type="number"
                      value={
                        settings.bs_monthly_limit
                          ? String(settings.bs_monthly_limit / GB_IN_BYTES)
                          : ""
                      }
                      placeholder="0"
                      onChange={(e) => {
                        const gb = parseFloat(e.target.value);
                        updateSettings({
                          bs_monthly_limit:
                            e.target.value === "" || isNaN(gb)
                              ? 0
                              : Math.round(gb * GB_IN_BYTES),
                        });
                      }}
                    />
                    <FormHelperText>
                      {t("panelSettings.bsMonthlyLimitGbHint")}
                    </FormHelperText>
                  </FormControl>
                </VStack>
              </TabPanel>
              <TabPanel px={0}>
                <VStack spacing={4} align="stretch">
                  <FormControl>
                    <FormLabel>
                      {t("panelSettings.v2rayJsonTemplate")}
                    </FormLabel>
                    <Textarea
                      fontFamily="mono"
                      minH="180px"
                      value={settings.sub_v2ray_json_template}
                      placeholder='{ "dns": {...}, "routing": {...}, ... }'
                      onChange={(e) =>
                        updateSettings({
                          sub_v2ray_json_template: e.target.value,
                        })
                      }
                    />
                    <FormHelperText>
                      {t("panelSettings.v2rayJsonTemplateHint")}
                    </FormHelperText>
                  </FormControl>
                  <FormControl>
                    <FormLabel>{t("panelSettings.routingDefault")}</FormLabel>
                    <Textarea
                      fontFamily="mono"
                      minH="140px"
                      value={settings.sub_routing_json_default}
                      placeholder='{ "domainStrategy": "IPIfNonMatch", "rules": [...] }'
                      onChange={(e) =>
                        updateSettings({
                          sub_routing_json_default: e.target.value,
                        })
                      }
                    />
                    <FormHelperText>
                      {t("panelSettings.routingDefaultHint")}
                    </FormHelperText>
                  </FormControl>
                  <FormControl>
                    <FormLabel>{t("panelSettings.routingBs")}</FormLabel>
                    <Textarea
                      fontFamily="mono"
                      minH="140px"
                      value={settings.sub_routing_json_bs}
                      placeholder='{ "domainStrategy": "AsIs", "rules": [...] }'
                      onChange={(e) =>
                        updateSettings({
                          sub_routing_json_bs: e.target.value,
                        })
                      }
                    />
                    <FormHelperText>
                      {t("panelSettings.routingBsHint")}
                    </FormHelperText>
                  </FormControl>
                </VStack>
              </TabPanel>
            </TabPanels>
          </Tabs>
        </ModalBody>
        <ModalFooter>
          <HStack>
            <Button
              variant="outline"
              onClick={resetToDefaults}
              isLoading={loading}
            >
              {t("panelSettings.resetDefaults")}
            </Button>
            <Button
              colorScheme="primary"
              onClick={save}
              isLoading={saving}
              isDisabled={loading}
            >
              {t("core.save")}
            </Button>
          </HStack>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};

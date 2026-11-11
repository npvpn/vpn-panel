import {
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  Input,
  SimpleGrid,
  Switch,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";

type SubscriptionProfile = {
  sub_support_url: string;
  sub_profile_title: string;
  sub_profile_url: string;
  sub_subscription_domain: string;
  sub_update_interval: string;
  web_url: string;
  show_ads: boolean;
  sub_device_limit_hard_mode: boolean;
  bs_extra_reset_pool_on_prolong: boolean;
};

const EMPTY: SubscriptionProfile = {
  sub_support_url: "",
  sub_profile_title: "",
  sub_profile_url: "",
  sub_subscription_domain: "",
  sub_update_interval: "",
  web_url: "",
  show_ads: true,
  sub_device_limit_hard_mode: false,
  bs_extra_reset_pool_on_prolong: false,
};

export const SubscriptionProfileForm: FC = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [profile, setProfile] = useState<SubscriptionProfile>(EMPTY);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch<SubscriptionProfile>("/settings/subscription")
      .then((data) => setProfile({ ...EMPTY, ...data }))
      .catch(() => setProfile(EMPTY));
  }, []);

  const update = (patch: Partial<SubscriptionProfile>) => {
    setProfile((current) => ({ ...current, ...patch }));
  };

  const save = () => {
    setSaving(true);
    fetch<SubscriptionProfile>("/settings/subscription", {
      method: "PUT",
      body: profile,
    })
      .then((updated) => {
        setProfile({ ...EMPTY, ...updated });
        toast({
          title: t("botSettings.subscriptionSaved"),
          status: "success",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .catch(() => {
        toast({
          title: t("core.generalErrorMessage"),
          status: "error",
          duration: 2500,
          isClosable: true,
          position: "top",
        });
      })
      .finally(() => setSaving(false));
  };

  return (
    <VStack spacing={4} align="stretch">
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        <FormControl>
          <FormLabel>{t("botSettings.subSupportUrl")}</FormLabel>
          <Input
            value={profile.sub_support_url}
            onChange={(event) => update({ sub_support_url: event.target.value })}
          />
          <FormHelperText>{t("botSettings.subSupportUrlHint")}</FormHelperText>
        </FormControl>
        <FormControl>
          <FormLabel>{t("botSettings.subProfileTitle")}</FormLabel>
          <Input
            value={profile.sub_profile_title}
            onChange={(event) => update({ sub_profile_title: event.target.value })}
          />
          <FormHelperText>{t("botSettings.subProfileTitleHint")}</FormHelperText>
        </FormControl>
        <FormControl>
          <FormLabel>{t("botSettings.subProfileUrl")}</FormLabel>
          <Input
            value={profile.sub_profile_url}
            onChange={(event) => update({ sub_profile_url: event.target.value })}
          />
          <FormHelperText>{t("botSettings.subProfileUrlHint")}</FormHelperText>
        </FormControl>
        <FormControl>
          <FormLabel>{t("botSettings.subSubscriptionDomain")}</FormLabel>
          <Input
            value={profile.sub_subscription_domain}
            onChange={(event) =>
              update({ sub_subscription_domain: event.target.value })
            }
          />
          <FormHelperText>
            {t("botSettings.subSubscriptionDomainHint")}
          </FormHelperText>
        </FormControl>
        <FormControl>
          <FormLabel>{t("botSettings.subUpdateInterval")}</FormLabel>
          <Input
            value={profile.sub_update_interval}
            onChange={(event) =>
              update({ sub_update_interval: event.target.value })
            }
          />
          <FormHelperText>{t("botSettings.subUpdateIntervalHint")}</FormHelperText>
        </FormControl>
        <FormControl>
          <FormLabel>{t("botSettings.webUrl")}</FormLabel>
          <Input
            value={profile.web_url}
            onChange={(event) => update({ web_url: event.target.value })}
          />
          <FormHelperText>{t("botSettings.webUrlHint")}</FormHelperText>
        </FormControl>
      </SimpleGrid>
      <FormControl>
        <HStack justify="space-between">
          <FormLabel mb={0}>{t("botSettings.showAds")}</FormLabel>
          <Switch
            colorScheme="primary"
            isChecked={profile.show_ads}
            onChange={(event) => update({ show_ads: event.target.checked })}
          />
        </HStack>
        <FormHelperText>{t("botSettings.showAdsHint")}</FormHelperText>
      </FormControl>
      <FormControl>
        <HStack justify="space-between">
          <FormLabel mb={0}>{t("botSettings.bsExtraResetPoolOnProlong")}</FormLabel>
          <Switch
            colorScheme="primary"
            isChecked={profile.bs_extra_reset_pool_on_prolong}
            onChange={(event) =>
              update({ bs_extra_reset_pool_on_prolong: event.target.checked })
            }
          />
        </HStack>
        <FormHelperText>
          {t("botSettings.bsExtraResetPoolOnProlongHint")}
        </FormHelperText>
      </FormControl>
      <FormControl>
        <HStack justify="space-between">
          <FormLabel mb={0}>{t("botSettings.subDeviceLimitHardMode")}</FormLabel>
          <Switch
            colorScheme="primary"
            isChecked={profile.sub_device_limit_hard_mode}
            onChange={(event) =>
              update({ sub_device_limit_hard_mode: event.target.checked })
            }
          />
        </HStack>
        <FormHelperText>
          {t("botSettings.subDeviceLimitHardModeHint")}
        </FormHelperText>
      </FormControl>
      <Button alignSelf="flex-end" colorScheme="primary" onClick={save} isLoading={saving}>
        {t("core.save")}
      </Button>
    </VStack>
  );
};

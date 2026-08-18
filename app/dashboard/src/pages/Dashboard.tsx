import { Box, VStack } from "@chakra-ui/react";
import { AppSettingsDialog } from "components/AppSettingsDialog";
import { CoreSettingsModal } from "components/CoreSettingsModal";
import { BotSettingsDialog } from "components/BotSettingsDialog";
import { PanelSettingsDialog } from "components/PanelSettingsDialog";
import { DeleteUserModal } from "components/DeleteUserModal";
import { Filters } from "components/Filters";
import { Footer } from "components/Footer";
import { Header } from "components/Header";
import { HostsDialog } from "components/HostsDialog";
import { NodesDialog } from "components/NodesModal";
import { NodesUsage } from "components/NodesUsage";
import { QRCodeDialog } from "components/QRCodeDialog";
import { ResetAllUsageModal } from "components/ResetAllUsageModal";
import { SyncInboundsModal } from "components/SyncInboundsModal";
import { ResetUserUsageModal } from "components/ResetUserUsageModal";
import { RevokeSubscriptionModal } from "components/RevokeSubscriptionModal";
import { UserDialog } from "components/UserDialog";
import { UsersTable } from "components/UsersTable";
import { fetchInbounds, useDashboard } from "contexts/DashboardContext";
import { FC, useEffect } from "react";
import { Statistics } from "../components/Statistics";

export const Dashboard: FC = () => {
  useEffect(() => {
    // Префилл поиска из URL (#/?search=<username>) — deep-link из Chatwoot.
    const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
    const search = params.get("search");
    if (search) {
      useDashboard.getState().onFilterChange({ search });
    } else {
      useDashboard.getState().refetchUsers();
    }
    useDashboard.getState().onEditingBotSettings(false);
    fetchInbounds();
  }, []);
  return (
    <VStack justifyContent="space-between" minH="100vh" p="6" rowGap={4}>
      <Box w="full">
        <Header />
        <Statistics mt="4" />
        <Filters />
        <UsersTable />
        <UserDialog />
        <DeleteUserModal />
        <QRCodeDialog />
        <HostsDialog />
        <ResetUserUsageModal />
        <RevokeSubscriptionModal />
        <NodesDialog />
        <NodesUsage />
        <ResetAllUsageModal />
        <SyncInboundsModal />
        <CoreSettingsModal />
        <BotSettingsDialog />
        <PanelSettingsDialog />
        <AppSettingsDialog />
      </Box>
      <Footer />
    </VStack>
  );
};

export default Dashboard;

import { StatisticsQueryKey } from "components/Statistics";
import { fetch } from "service/http";
import { User, UserCreate } from "types/User";
import { queryClient } from "utils/react-query";
import { getUsersPerPageLimitSize } from "utils/userPreferenceStorage";
import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export type FilterType = {
  search?: string;
  limit?: number;
  offset?: number;
  sort: string;
  bot_username?: string;
  status?: "active" | "disabled" | "limited" | "expired" | "on_hold";
};
export type ProtocolType = "vmess" | "vless" | "trojan" | "shadowsocks";

export type FilterUsageType = {
  start?: string;
  end?: string;
};

export type InboundType = {
  tag: string;
  protocol: ProtocolType;
  network: string;
  tls: string;
  port?: number;
};
export type Inbounds = Map<ProtocolType, InboundType[]>;

type DashboardStateType = {
  isCreatingNewUser: boolean;
  editingUser: User | null | undefined;
  deletingUser: User | null;
  version: string | null;
  users: {
    users: User[];
    total: number;
  };
  inbounds: Inbounds;
  loading: boolean;
  filters: FilterType;
  subscribeUrl: string | null;
  QRcodeLinks: string[] | null;
  isEditingHosts: boolean;
  isEditingNodes: boolean;
  isEditingBotSettings: boolean;
  isEditingAppSettings: boolean;
  isEditingPanelSettings: boolean;
  isShowingNodesUsage: boolean;
  isResetingAllUsage: boolean;
  isConfirmingSyncInbounds: boolean;
  isSyncingInbounds: boolean;
  syncStatus: {
    running: boolean;
    scheduled: number;
    done: number;
    total: number;
  } | null;
  resetUsageUser: User | null;
  revokeSubscriptionUser: User | null;
  isEditingCore: boolean;
  onCreateUser: (isOpen: boolean) => void;
  onEditingUser: (user: User | null) => void;
  onDeletingUser: (user: User | null) => void;
  onResetAllUsage: (isResetingAllUsage: boolean) => void;
  onConfirmingSyncInbounds: (isConfirmingSyncInbounds: boolean) => void;
  refetchUsers: () => void;
  resetAllUsage: () => Promise<void>;
  syncInbounds: () => Promise<void>;
  pollSyncStatus: (opId: string) => void;
  onFilterChange: (filters: Partial<FilterType>) => void;
  deleteUser: (user: User) => Promise<void>;
  createUser: (user: UserCreate) => Promise<void>;
  editUser: (user: UserCreate) => Promise<void>;
  fetchUserUsage: (user: User, query: FilterUsageType) => Promise<void>;
  setQRCode: (links: string[] | null) => void;
  setSubLink: (subscribeURL: string | null) => void;
  onEditingHosts: (isEditingHosts: boolean) => void;
  onEditingNodes: (isEditingHosts: boolean) => void;
  onEditingBotSettings: (isEditingBotSettings: boolean) => void;
  onEditingAppSettings: (isEditingAppSettings: boolean) => void;
  onEditingPanelSettings: (isEditingPanelSettings: boolean) => void;
  onShowingNodesUsage: (isShowingNodesUsage: boolean) => void;
  resetDataUsage: (user: User) => Promise<void>;
  revokeSubscription: (user: User) => Promise<void>;
};

const fetchUsers = (query: FilterType): Promise<User[]> => {
  for (const key in query) {
    if (!query[key as keyof FilterType]) delete query[key as keyof FilterType];
  }
  useDashboard.setState({ loading: true });
  return fetch("/users", { query })
    .then((users) => {
      useDashboard.setState({ users });
      return users;
    })
    .finally(() => {
      useDashboard.setState({ loading: false });
    });
};

export const fetchInbounds = () => {
  return fetch("/inbounds")
    .then((inbounds: Inbounds) => {
      useDashboard.setState({
        inbounds: new Map(Object.entries(inbounds)) as Inbounds,
      });
    })
    .finally(() => {
      useDashboard.setState({ loading: false });
    });
};

export const useDashboard = create(
  subscribeWithSelector<DashboardStateType>((set, get) => ({
    version: null,
    editingUser: null,
    deletingUser: null,
    isCreatingNewUser: false,
    QRcodeLinks: null,
    subscribeUrl: null,
    users: {
      users: [],
      total: 0,
    },
    loading: true,
    isResetingAllUsage: false,
    isConfirmingSyncInbounds: false,
    isSyncingInbounds: false,
    syncStatus: null,
    isEditingHosts: false,
    isEditingNodes: false,
    isEditingBotSettings: false,
    isEditingAppSettings: false,
    isEditingPanelSettings: false,
    isShowingNodesUsage: false,
    resetUsageUser: null,
    revokeSubscriptionUser: null,
    filters: {
      search: "",
      limit: getUsersPerPageLimitSize(),
      sort: "-created_at",
    },
    inbounds: new Map(),
    isEditingCore: false,
    refetchUsers: () => {
      fetchUsers(get().filters);
    },
    resetAllUsage: () => {
      return fetch(`/users/reset`, { method: "POST" }).then(() => {
        get().onResetAllUsage(false);
        get().refetchUsers();
      });
    },
    syncInbounds: () => {
      set({ isSyncingInbounds: true });
      // eslint-disable-next-line no-console
      console.debug("[syncInbounds] sending POST /users/sync-inbounds");
      return fetch(`/users/sync-inbounds`, { method: "POST" })
        .then((res: any) => {
          // eslint-disable-next-line no-console
          console.debug("[syncInbounds] success response", res);
          if (res?.op_id) {
            set({
              syncStatus: {
                running: true,
                scheduled: res.users_scheduled || 0,
                done: 0,
                total: res.users_processed || 0,
              },
            });
            get().pollSyncStatus(res.op_id);
          }
          get().refetchUsers();
        })
        .catch((err) => {
          // eslint-disable-next-line no-console
          console.debug("[syncInbounds] error", err);
          throw err;
        })
        .finally(() => set({ isSyncingInbounds: false }));
    },
    pollSyncStatus: (opId: string) => {
      let stopped = false;
      const tick = () => {
        if (stopped) return;
        fetch(`/users/sync-inbounds/status`, { method: "GET", query: { op_id: opId } })
          .then((st: any) => {
            if (!st || st.detail) return;
            set({
              syncStatus: {
                running: !!st.running,
                scheduled: st.scheduled || 0,
                done: st.done || 0,
                total: st.total || 0,
              },
            });
            if (!st.running) {
              stopped = true;
              return;
            }
            setTimeout(tick, 1000);
          })
          .catch(() => {
            setTimeout(tick, 1500);
          });
      };
      setTimeout(tick, 500);
    },
    onResetAllUsage: (isResetingAllUsage) => set({ isResetingAllUsage }),
    onConfirmingSyncInbounds: (isConfirmingSyncInbounds) =>
      set({ isConfirmingSyncInbounds }),
    onCreateUser: (isCreatingNewUser) => set({ isCreatingNewUser }),
    onEditingUser: (editingUser) => {
      set({ editingUser });
    },
    onDeletingUser: (deletingUser) => {
      set({ deletingUser });
    },
    onFilterChange: (filters) => {
      set({
        filters: {
          ...get().filters,
          ...filters,
        },
      });
      get().refetchUsers();
    },
    setQRCode: (QRcodeLinks) => {
      set({ QRcodeLinks });
    },
    deleteUser: (user: User) => {
      set({ editingUser: null });
      return fetch(`/user/${user.username}`, { method: "DELETE" }).then(() => {
        set({ deletingUser: null });
        get().refetchUsers();
        queryClient.invalidateQueries(StatisticsQueryKey);
      });
    },
    createUser: (body: UserCreate) => {
      return fetch(`/user`, { method: "POST", body }).then(() => {
        set({ editingUser: null });
        get().refetchUsers();
        queryClient.invalidateQueries(StatisticsQueryKey);
      });
    },
    editUser: (body: UserCreate) => {
      return fetch(`/user/${body.username}`, { method: "PUT", body }).then(
        () => {
          get().onEditingUser(null);
          get().refetchUsers();
        }
      );
    },
    fetchUserUsage: (body: User, query: FilterUsageType) => {
      for (const key in query) {
        if (!query[key as keyof FilterUsageType])
          delete query[key as keyof FilterUsageType];
      }
      return fetch(`/user/${body.username}/usage`, { method: "GET", query });
    },
    onEditingHosts: (isEditingHosts: boolean) => {
      set({ isEditingHosts });
    },
    onEditingNodes: (isEditingNodes: boolean) => {
      set({ isEditingNodes });
    },
    onEditingBotSettings: (isEditingBotSettings: boolean) => {
      set({ isEditingBotSettings });
    },
    onEditingAppSettings: (isEditingAppSettings: boolean) => {
      set({ isEditingAppSettings });
    },
    onEditingPanelSettings: (isEditingPanelSettings: boolean) => {
      set({ isEditingPanelSettings });
    },
    onShowingNodesUsage: (isShowingNodesUsage: boolean) => {
      set({ isShowingNodesUsage });
    },
    setSubLink: (subscribeUrl) => {
      set({ subscribeUrl });
    },
    resetDataUsage: (user) => {
      return fetch(`/user/${user.username}/reset`, { method: "POST" }).then(
        () => {
          set({ resetUsageUser: null });
          get().refetchUsers();
        }
      );
    },
    revokeSubscription: (user) => {
      return fetch(`/user/${user.username}/revoke_sub`, {
        method: "POST",
      }).then((user) => {
        set({ revokeSubscriptionUser: null, editingUser: user });
        get().refetchUsers();
      });
    },
  }))
);

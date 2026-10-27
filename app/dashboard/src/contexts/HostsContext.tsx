import { fetch } from "service/http";
import { create } from "zustand";

type HostsSchema = Record<
  string,
  {
    remark: string;
    address: string;
    port: number | null;
    path: string | null;
    sni: string | null;
    host: string | null;
    bot_usernames?: string[];
  }[]
>;

type HostsStore = {
  isLoading: boolean;
  isPostLoading: boolean;
  hosts: HostsSchema;
  fetchHosts: () => Promise<void>;
  setHosts: (hosts: HostsSchema) => Promise<void>;
};
export const useHosts = create<HostsStore>((set) => ({
  isLoading: false,
  isPostLoading: false,
  hosts: {},
  fetchHosts: () => {
    set({ isLoading: true });
    return fetch("/hosts")
      .then((hosts) => {
        set({ hosts });
      })
      .finally(() => set({ isLoading: false }));
  },
  setHosts: (body) => {
    set({ isPostLoading: true });
    return fetch("/hosts", { method: "PUT", body }).finally(() => {
      set({ isPostLoading: false });
    });
  },
}));
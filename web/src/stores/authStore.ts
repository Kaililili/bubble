import { create } from "zustand";
import client from "../api/client";

interface User {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;

  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchMe: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem("token"),
  isAuthenticated: !!localStorage.getItem("token"),
  loading: false,

  login: async (username: string, password: string) => {
    set({ loading: true });
    try {
      const res = await client.post("/auth/login", { username, password });
      const { access_token, user } = res.data;
      localStorage.setItem("token", access_token);
      set({ user, token: access_token, isAuthenticated: true, loading: false });
    } catch {
      set({ loading: false });
      throw new Error("登录失败");
    }
  },

  register: async (username: string, email: string, password: string) => {
    set({ loading: true });
    try {
      const res = await client.post("/auth/register", { username, email, password });
      set({ loading: false });
      // 注册成功后自动登录
      const loginRes = await client.post("/auth/login", { username, password });
      const { access_token, user } = loginRes.data;
      localStorage.setItem("token", access_token);
      set({ user, token: access_token, isAuthenticated: true });
    } catch {
      set({ loading: false });
      throw new Error("注册失败");
    }
  },

  logout: () => {
    localStorage.removeItem("token");
    set({ user: null, token: null, isAuthenticated: false });
  },

  fetchMe: async () => {
    try {
      const res = await client.get("/auth/me");
      set({ user: res.data, isAuthenticated: true });
    } catch {
      localStorage.removeItem("token");
      set({ user: null, token: null, isAuthenticated: false });
    }
  },
}));

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "./client";

export const qk = {
  me: ["me"] as const,
  meta: ["meta"] as const,
  workspaces: ["workspaces"] as const,
  workspace: (id: string) => ["workspaces", id] as const,
  brandKit: (id: string) => ["workspaces", id, "brand-kit"] as const,
};

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => unwrap(api.GET("/api/v1/auth/me")) });
}

export function useMeta() {
  return useQuery({
    queryKey: qk.meta,
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: Infinity,
  });
}

export function useWorkspaces() {
  return useQuery({
    queryKey: qk.workspaces,
    queryFn: () => unwrap(api.GET("/api/v1/workspaces")),
  });
}

export function useWorkspace(id: string) {
  return useQuery({
    queryKey: qk.workspace(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}", { params: { path: { workspace_id: id } } }),
      ),
  });
}

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["WorkspaceCreate"]) =>
      unwrap(api.POST("/api/v1/workspaces", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.workspaces }),
  });
}

export function useBrandKit(id: string) {
  return useQuery({
    queryKey: qk.brandKit(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/brand-kit", {
          params: { path: { workspace_id: id } },
        }),
      ),
  });
}

export function useSaveBrandKit(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["BrandKitIn"]) =>
      unwrap(
        api.PUT("/api/v1/workspaces/{workspace_id}/brand-kit", {
          params: { path: { workspace_id: id } },
          body,
        }),
      ),
    onSuccess: (kit) => qc.setQueryData(qk.brandKit(id), kit),
  });
}

export function useLogout() {
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    // Hard navigation on purpose: drops all cached client state for the old session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    onSettled: () => window.location.assign("/login"),
  });
}

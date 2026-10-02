"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, uploadFile, type Schemas } from "./client";

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

export function useBrandKit(id: string, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: qk.brandKit(id),
    enabled: opts.enabled ?? true,
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

// ---------------------------------------------------------------- brand identity + voice

const path = (id: string) => ({ params: { path: { workspace_id: id } } });

export function useUploadLogo(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      uploadFile<Schemas["LogoUploadOut"]>(`/api/v1/workspaces/${id}/brand-kit/logo`, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.brandKit(id) }),
  });
}

export function useVoiceProfile(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (samples: string[]) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/brand-kit/voice-profile", {
          ...path(id),
          body: { samples },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.brandKit(id) }),
  });
}

// ---------------------------------------------------------------- brand knowledge

export const qkDocs = (id: string) => ["workspaces", id, "brand-docs"] as const;
export const qkIndex = (id: string) => ["workspaces", id, "brand-index"] as const;

export function useBrandDocs(id: string) {
  return useQuery({
    queryKey: qkDocs(id),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/brand-docs", path(id))),
    // Poll while anything is still being ingested by the worker.
    refetchInterval: (q) =>
      q.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false,
  });
}

export function useBrandIndex(id: string) {
  return useQuery({
    queryKey: qkIndex(id),
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/brand-index", path(id))),
  });
}

function useDocsMutation<A>(id: string, fn: (arg: A) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qkDocs(id) });
      qc.invalidateQueries({ queryKey: qkIndex(id) });
    },
  });
}

export function useUploadDoc(id: string) {
  return useDocsMutation(id, (file: File) =>
    uploadFile<Schemas["BrandDocumentOut"]>(`/api/v1/workspaces/${id}/brand-docs`, file),
  );
}

export function useImportUrl(id: string) {
  return useDocsMutation(id, (url: string) =>
    unwrap(
      api.POST("/api/v1/workspaces/{workspace_id}/brand-docs/url", {
        ...path(id),
        body: { url, max_pages: 10 },
      }),
    ),
  );
}

export function useDeleteDoc(id: string) {
  return useDocsMutation(id, (docId: string) =>
    unwrap(
      api.DELETE("/api/v1/workspaces/{workspace_id}/brand-docs/{doc_id}", {
        params: { path: { workspace_id: id, doc_id: docId } },
      }),
    ),
  );
}

export function useReindexDoc(id: string) {
  return useDocsMutation(id, (docId: string) =>
    unwrap(
      api.POST("/api/v1/workspaces/{workspace_id}/brand-docs/{doc_id}/reindex", {
        params: { path: { workspace_id: id, doc_id: docId } },
      }),
    ),
  );
}

export function useReindexAll(id: string) {
  return useDocsMutation(id, () =>
    unwrap(api.POST("/api/v1/workspaces/{workspace_id}/brand-index/reindex", path(id))),
  );
}

export function useRetrieval(id: string) {
  return useMutation({
    mutationFn: (query: string) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/brand-docs/search", {
          ...path(id),
          body: { query, k: 6 },
        }),
      ),
  });
}

// ---------------------------------------------------------------- content

export const qkContent = (id: string) => ["workspaces", id, "content"] as const;

export function useContentList(id: string, status?: Schemas["ContentStatus"][]) {
  return useQuery({
    queryKey: [...qkContent(id), status ?? "all"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/content", {
          params: { path: { workspace_id: id }, query: { status, limit: 50 } },
        }),
      ),
  });
}

export function useEditContent(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, content }: { itemId: string; content: Record<string, unknown> }) =>
      unwrap(
        api.PATCH("/api/v1/workspaces/{workspace_id}/content/{item_id}", {
          params: { path: { workspace_id: id, item_id: itemId } },
          body: { content },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qkContent(id) }),
  });
}

export function useRegenerate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/content/{item_id}/regenerate", {
          params: { path: { workspace_id: id, item_id: itemId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qkContent(id) }),
  });
}

// ---------------------------------------------------------------- AI settings + usage

export function useAISettings(id: string) {
  return useQuery({
    queryKey: ["workspaces", id, "ai-settings"],
    queryFn: () => unwrap(api.GET("/api/v1/workspaces/{workspace_id}/ai-settings", path(id))),
  });
}

export function useSaveAISettings(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["AISettingsIn"]) =>
      unwrap(api.PUT("/api/v1/workspaces/{workspace_id}/ai-settings", { ...path(id), body })),
    onSuccess: (data) => qc.setQueryData(["workspaces", id, "ai-settings"], data),
  });
}

export function useUsage(id: string, month?: string) {
  return useQuery({
    queryKey: ["workspaces", id, "usage", month ?? "current"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/usage", {
          params: { path: { workspace_id: id }, query: { month } },
        }),
      ),
  });
}

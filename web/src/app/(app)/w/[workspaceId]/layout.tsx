import { AppShell } from "@/components/app-shell";

export default async function WorkspaceLayout({
  children,
  params,
}: LayoutProps<"/w/[workspaceId]">) {
  const { workspaceId } = await params;
  return <AppShell workspaceId={workspaceId}>{children}</AppShell>;
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { savedVersion, subscribeSaved } from "@/lib/savedSeed";
import { seedVersion, subscribeSeed } from "@/lib/searchSeed";
import { SideNav } from "@/components/shell/SideNav";
import { AuthGate } from "@/features/auth/AuthGate";
import { TopBar } from "@/components/shell/TopBar";
import { SearchPage } from "@/features/search/SearchPage";
import { SourcesPage } from "@/features/sources/SourcesPage";
import { TemplatesPage } from "@/features/templates/TemplatesPage";
import { AccountPasswordPage } from "@/features/auth/AccountPasswordPage";
import { UsersPage } from "@/features/users/UsersPage";
import { AccountPage } from "@/features/account/AccountPage";
import { SavedSearchesPage } from "@/features/saved/SavedSearchesPage";
import { ProvidersPage } from "@/features/providers/ProvidersPage";
import { RulesPage } from "@/features/detect/RulesPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { AlertTargetsPage } from "@/features/alerts/AlertTargetsPage";
import { SchedulesPage } from "@/features/schedules/SchedulesPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { AuditLogPage } from "@/features/audit/AuditLogPage";
import { AiUsagePage } from "@/features/ai/AiUsagePage";
import { InvestigatePage } from "@/features/investigate/InvestigatePage";
import { IdentitiesPage } from "@/features/identities/IdentitiesPage";
import { EnrichmentPage } from "@/features/settings/EnrichmentPage";
import { McpPage } from "@/features/settings/McpPage";
import { SetupPage } from "@/features/setup/SetupPage";
import { HealthPage } from "@/features/health/HealthPage";
import { usePage } from "@/lib/route";
import { SETTINGS_IDS } from "@/lib/nav";
import { cn } from "@/lib/cn";
import { SettingsNav } from "@/components/shell/SettingsNav";
import { applyTheme, type Theme } from "@/lib/theme";

interface AppProps {
  initialTheme: Theme;
  queryClient?: QueryClient;
}

export function App({ initialTheme, queryClient }: AppProps) {
  const [client] = useState(
    () => queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: 1 } } }),
  );
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const page = usePage();
  const [palette, setPalette] = useState(false);
  // Narrow screens: the side nav is hidden behind a Menu button; any navigation closes it.
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [page]);
  // A handoff into Search or Saved searches remounts that page so it takes the handoff.
  const searchKey = useSyncExternalStore(subscribeSeed, seedVersion);
  const savedKey = useSyncExternalStore(subscribeSaved, savedVersion);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };

  return (
    <QueryClientProvider client={client}>
      {page === "account" ? (
        // Invite and reset links work signed out, so this page sits outside the gate.
        <AccountPasswordPage />
      ) : (
        <AuthGate>
          {(user, signOut) => (
            <div className="flex min-h-full flex-col">
              <TopBar
                theme={theme}
                onToggleTheme={toggleTheme}
                user={user}
                onSignOut={signOut}
                onOpenPalette={() => setPalette(true)}
                menuOpen={menu}
                onToggleMenu={() => setMenu((open) => !open)}
              />
              {palette ? (
                <CommandPalette
                  page={page}
                  isAdmin={!user || user.role === "admin"}
                  canAudit={!user || user.role !== "analyst"}
                  canAsk={!user || user.role !== "auditor"}
                  theme={theme}
                  onToggleTheme={toggleTheme}
                  onClose={() => setPalette(false)}
                />
              ) : null}
              <div className="flex min-h-0 flex-1 flex-wrap">
                <SideNav
                  // Ask is a tab of Search (ADR-0008); /ask still works and opens it.
                  active={page === "ask" ? "search" : page}
                  isAdmin={!user || user.role === "admin"}
                  canAudit={!user || user.role !== "analyst"}
                  open={menu}
                />
                <main
                  className={cn(
                    "flex min-w-0 flex-[999_1_560px] bg-bg",
                    SETTINGS_IDS.has(page) && "flex-col md:flex-row",
                  )}
                >
                  {SETTINGS_IDS.has(page) ? (
                    <SettingsNav
                      active={page}
                      isAdmin={!user || user.role === "admin"}
                      canAudit={!user || user.role !== "analyst"}
                    />
                  ) : null}
                  {page === "rules" ? (
                    <RulesPage
                      isAdmin={!user || user.role === "admin"}
                      canRun={!user || user.role !== "auditor"}
                    />
                  ) : page === "alerts" && (!user || user.role === "admin") ? (
                    <AlertTargetsPage />
                  ) : page === "dashboard" ? (
                    <DashboardPage />
                  ) : page === "schedules" ? (
                    <SchedulesPage
                      canCreate={!user || user.role !== "auditor"}
                      isAdmin={!user || user.role === "admin"}
                    />
                  ) : page === "saved" ? (
                    <SavedSearchesPage key={savedKey} me={user} />
                  ) : page === "me" && user ? (
                    <AccountPage me={user} />
                  ) : page === "providers" && (!user || user.role === "admin") ? (
                    <ProvidersPage />
                  ) : page === "users" && (!user || user.role === "admin") ? (
                    <UsersPage me={user} />
                  ) : page === "templates" && (!user || user.role === "admin") ? (
                    <TemplatesPage />
                  ) : page === "audit" && (!user || user.role !== "analyst") ? (
                    <AuditLogPage isAdmin={!user || user.role === "admin"} />
                  ) : page === "ai" ? (
                    <AiUsagePage isAdmin={!user || user.role === "admin"} />
                  ) : page === "identities" && (!user || user.role === "admin") ? (
                    <IdentitiesPage />
                  ) : page === "mcp" && (!user || user.role === "admin") ? (
                    <McpPage />
                  ) : page === "enrichment" && (!user || user.role === "admin") ? (
                    <EnrichmentPage />
                  ) : page === "setup" && (!user || user.role === "admin") ? (
                    <SetupPage />
                  ) : page === "health" ? (
                    <HealthPage isAdmin={!user || user.role === "admin"} />
                  ) : page === "investigate" ? (
                    <InvestigatePage />
                  ) : page === "overview" ? (
                    <OverviewPage />
                  ) : page === "sources" ? (
                    // Open mode (no accounts) is the local admin.
                    <SourcesPage canManage={!user || user.role === "admin"} />
                  ) : (
                    <SearchPage
                      key={`${page}:${searchKey}`}
                      canSave={!user || user.role !== "auditor"}
                      canAsk={!user || user.role !== "auditor"}
                      isAdmin={!user || user.role === "admin"}
                      initialTab={page === "ask" ? "ask" : undefined}
                    />
                  )}
                </main>
              </div>
            </div>
          )}
        </AuthGate>
      )}
    </QueryClientProvider>
  );
}

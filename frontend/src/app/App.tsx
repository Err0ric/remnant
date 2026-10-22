import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState, useSyncExternalStore } from "react";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { savedVersion, subscribeSaved } from "@/lib/savedSeed";
import { seedVersion, subscribeSeed } from "@/lib/searchSeed";
import { SideNav } from "@/components/shell/SideNav";
import { SearchPage } from "@/features/search/SearchPage";
// Small, and the target of "Schedule" handoffs from Search; kept with Search.
import { SchedulesPage } from "@/features/schedules/SchedulesPage";
import { AuthGate } from "@/features/auth/AuthGate";
import { TopBar } from "@/components/shell/TopBar";
import { AccountPasswordPage } from "@/features/auth/AccountPasswordPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { HomeRedirect } from "@/features/dashboard/HomeRedirect";
import { usePage } from "@/lib/route";
import { SETTINGS_IDS } from "@/lib/nav";
import { cn } from "@/lib/cn";
import { SettingsNav } from "@/components/shell/SettingsNav";
import { applyTheme, type Theme } from "@/lib/theme";

// Pages load on first visit, so the first screen does not carry every page (install
// finding: one 961 kB chunk). Search, Schedules, and Overview stay in the main bundle;
// the SQL editor (CodeMirror) is its own chunk, loaded after the page shows.
const SourcesPage = lazy(() =>
  import("@/features/sources/SourcesPage").then((m) => ({ default: m.SourcesPage })),
);
const TemplatesPage = lazy(() =>
  import("@/features/templates/TemplatesPage").then((m) => ({ default: m.TemplatesPage })),
);
const UsersPage = lazy(() =>
  import("@/features/users/UsersPage").then((m) => ({ default: m.UsersPage })),
);
const AccountPage = lazy(() =>
  import("@/features/account/AccountPage").then((m) => ({ default: m.AccountPage })),
);
const SavedSearchesPage = lazy(() =>
  import("@/features/saved/SavedSearchesPage").then((m) => ({ default: m.SavedSearchesPage })),
);
const ProvidersPage = lazy(() =>
  import("@/features/providers/ProvidersPage").then((m) => ({ default: m.ProvidersPage })),
);
const RulesPage = lazy(() =>
  import("@/features/detect/RulesPage").then((m) => ({ default: m.RulesPage })),
);
const DashboardPage = lazy(() =>
  import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const AlertTargetsPage = lazy(() =>
  import("@/features/alerts/AlertTargetsPage").then((m) => ({ default: m.AlertTargetsPage })),
);
const AuditLogPage = lazy(() =>
  import("@/features/audit/AuditLogPage").then((m) => ({ default: m.AuditLogPage })),
);
const AiUsagePage = lazy(() =>
  import("@/features/ai/AiUsagePage").then((m) => ({ default: m.AiUsagePage })),
);
const InvestigatePage = lazy(() =>
  import("@/features/investigate/InvestigatePage").then((m) => ({ default: m.InvestigatePage })),
);
const IdentitiesPage = lazy(() =>
  import("@/features/identities/IdentitiesPage").then((m) => ({ default: m.IdentitiesPage })),
);
const EnrichmentPage = lazy(() =>
  import("@/features/settings/EnrichmentPage").then((m) => ({ default: m.EnrichmentPage })),
);
const McpPage = lazy(() =>
  import("@/features/settings/McpPage").then((m) => ({ default: m.McpPage })),
);
const SetupPage = lazy(() =>
  import("@/features/setup/SetupPage").then((m) => ({ default: m.SetupPage })),
);
const HealthPage = lazy(() =>
  import("@/features/health/HealthPage").then((m) => ({ default: m.HealthPage })),
);

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
                  <Suspense fallback={<div className="flex-1" aria-busy="true" />}>
                    {page === "rules" ? (
                      <RulesPage
                        isAdmin={!user || user.role === "admin"}
                        canRun={!user || user.role !== "auditor"}
                      />
                    ) : page === "alerts" && (!user || user.role === "admin") ? (
                      <AlertTargetsPage />
                    ) : page === "dashboard" ? (
                      <DashboardPage me={user} />
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
                    ) : page === "home" ? (
                      <HomeRedirect />
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
                  </Suspense>
                </main>
              </div>
            </div>
          )}
        </AuthGate>
      )}
    </QueryClientProvider>
  );
}

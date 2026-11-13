import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/shell/PageHeader";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState, useSyncExternalStore } from "react";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { savedVersion, subscribeSaved } from "@/lib/savedSeed";
import { seedVersion, subscribeSeed } from "@/lib/searchSeed";
import { SideNav } from "@/components/shell/SideNav";
import { SearchPage } from "@/features/search/SearchPage";
import { searchNavVersion, subscribeSearchNav } from "@/lib/searchUrl";
// Small, and the target of "Schedule" handoffs from Logs; kept with Logs.
import { SchedulesPage } from "@/features/schedules/SchedulesPage";
import { AuthGate } from "@/features/auth/AuthGate";
import { TopBar } from "@/components/shell/TopBar";
import { AccountPasswordPage } from "@/features/auth/AccountPasswordPage";
import { HomeRedirect, ToHealth, ToLogs } from "@/features/dashboard/HomeRedirect";
import { canonical, usePage, useSection, useTab } from "@/lib/route";
import { SqlOnly, ViewerProvider } from "@/app/ViewerProvider";
import { SqlOffNotice } from "@/features/search/SqlOffNotice";
import { SETTINGS_IDS } from "@/lib/nav";
import { cn } from "@/lib/cn";
import { OfflineBanner } from "@/components/shell/OfflineBanner";
import { SettingsNav } from "@/components/shell/SettingsNav";
import { applyTheme, type Theme } from "@/lib/theme";
import { ApiError } from "@/lib/api";
import { ErrorBoundary, PageBoundary } from "@/components/ErrorBoundary";
import { AskPage } from "@/features/ask/AskPage";
import { AskSlideOver } from "@/features/ask/AskSlideOver";
import { withChunkReload } from "@/lib/chunkReload";

// Pages load on first visit, so the first screen does not carry every page (install
// finding: one 961 kB chunk). Logs, Schedules, and Overview stay in the main bundle;
// the SQL editor (CodeMirror) is its own chunk, loaded after the page shows.
const SsoPage = lazy(
  withChunkReload(() =>
    import("@/features/settings/SsoPage").then((m) => ({ default: m.SsoPage })),
  ),
);
const PluginsPage = lazy(
  withChunkReload(() =>
    import("@/features/settings/PluginsPage").then((m) => ({ default: m.PluginsPage })),
  ),
);
const M365Page = lazy(
  withChunkReload(() => import("@/features/m365/M365Page").then((m) => ({ default: m.M365Page }))),
);
const SourcesPage = lazy(
  withChunkReload(() =>
    import("@/features/sources/SourcesPage").then((m) => ({ default: m.SourcesPage })),
  ),
);
const TemplatesPage = lazy(
  withChunkReload(() =>
    import("@/features/templates/TemplatesPage").then((m) => ({ default: m.TemplatesPage })),
  ),
);
const UsersPage = lazy(
  withChunkReload(() =>
    import("@/features/users/UsersPage").then((m) => ({ default: m.UsersPage })),
  ),
);
const AccountPage = lazy(
  withChunkReload(() =>
    import("@/features/account/AccountPage").then((m) => ({ default: m.AccountPage })),
  ),
);
const SavedSearchesPage = lazy(
  withChunkReload(() =>
    import("@/features/saved/SavedSearchesPage").then((m) => ({ default: m.SavedSearchesPage })),
  ),
);
const ProvidersPage = lazy(
  withChunkReload(() =>
    import("@/features/providers/ProvidersPage").then((m) => ({ default: m.ProvidersPage })),
  ),
);
const RulesPage = lazy(
  withChunkReload(() =>
    import("@/features/detect/RulesPage").then((m) => ({ default: m.RulesPage })),
  ),
);
const DashboardPage = lazy(
  withChunkReload(() =>
    import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
  ),
);
const AlertsPage = lazy(
  withChunkReload(() =>
    import("@/features/alerts/AlertsPage").then((m) => ({ default: m.AlertsPage })),
  ),
);
const AlertTargetsPage = lazy(
  withChunkReload(() =>
    import("@/features/alerts/AlertTargetsPage").then((m) => ({ default: m.AlertTargetsPage })),
  ),
);
const AboutPage = lazy(
  withChunkReload(() =>
    import("@/features/settings/AboutPage").then((m) => ({ default: m.AboutPage })),
  ),
);
const AuditLogPage = lazy(
  withChunkReload(() =>
    import("@/features/audit/AuditLogPage").then((m) => ({ default: m.AuditLogPage })),
  ),
);
const AiUsagePage = lazy(
  withChunkReload(() =>
    import("@/features/ai/AiUsagePage").then((m) => ({ default: m.AiUsagePage })),
  ),
);
const InvestigatePage = lazy(
  withChunkReload(() =>
    import("@/features/investigate/InvestigatePage").then((m) => ({ default: m.InvestigatePage })),
  ),
);
const IdentitiesPage = lazy(
  withChunkReload(() =>
    import("@/features/identities/IdentitiesPage").then((m) => ({ default: m.IdentitiesPage })),
  ),
);
const EnrichmentPage = lazy(
  withChunkReload(() =>
    import("@/features/settings/EnrichmentPage").then((m) => ({ default: m.EnrichmentPage })),
  ),
);
const McpPage = lazy(
  withChunkReload(() =>
    import("@/features/settings/McpPage").then((m) => ({ default: m.McpPage })),
  ),
);
const SetupPage = lazy(
  withChunkReload(() =>
    import("@/features/setup/SetupPage").then((m) => ({ default: m.SetupPage })),
  ),
);
const AiSettings = lazy(
  withChunkReload(() =>
    import("@/features/ai/AiSettings").then((m) => ({ default: m.AiSettings })),
  ),
);
const HealthPage = lazy(
  withChunkReload(() =>
    import("@/features/health/HealthPage").then((m) => ({ default: m.HealthPage })),
  ),
);

interface ForAdministratorsProps {
  title: string;
  detail: string;
}

/** An administrators' page opened by someone else (an old address, a shared link): says so
 * in place, and never shows another page under that address. */
function ForAdministrators({ title, detail }: ForAdministratorsProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title={title} />
      <EmptyState kind="restricted" title="For administrators" detail={detail} />
    </div>
  );
}

/** One fetch per endpoint per page load (owner, 2026-10-31): data stays fresh for 30 s, so
 * a second component mounting a moment later reuses it instead of asking again, and a
 * request the server answered (an error included: a busy server says so) is not sent a
 * second time; only a network failure is retried once. Mutations still refresh what they
 * change, and polling cards keep their own intervals. */
export function newQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) => count < 1 && !(error instanceof ApiError),
      },
    },
  });
}

interface AppProps {
  initialTheme: Theme;
  queryClient?: QueryClient;
}

export function App({ initialTheme, queryClient }: AppProps) {
  const [client] = useState(() => queryClient ?? newQueryClient());
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const page = usePage();
  const tab = useTab();
  const fragment = useSection();
  // Old paths and `#tab` links (alert messages, bookmarks) settle on the ADR-0038 address.
  useEffect(() => {
    const to = canonical();
    if (to) window.history.replaceState(null, "", to);
  }, [page, tab, fragment]);
  const [palette, setPalette] = useState(false);
  // Narrow screens: the side nav is hidden behind a Menu button; any navigation closes it.
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [page]);
  // A handoff into Logs or Saved searches remounts that page so it takes the handoff.
  const searchKey = useSyncExternalStore(subscribeSeed, seedVersion);
  // Back and Forward on Logs, and New search, rebuild the page from its address (D90).
  const searchNav = useSyncExternalStore(subscribeSearchNav, searchNavVersion);
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
            <ViewerProvider user={user}>
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
                <OfflineBanner />
                <SqlOnly fallback={null}>
                  <ErrorBoundary label="Ask AI">
                    <AskSlideOver isAdmin={!user || user.role === "admin"} />
                  </ErrorBoundary>
                </SqlOnly>
                {palette ? (
                  <CommandPalette
                    page={page}
                    isAdmin={!user || user.role === "admin"}
                    canAudit={!user || user.role !== "analyst"}
                    theme={theme}
                    onToggleTheme={toggleTheme}
                    onClose={() => setPalette(false)}
                  />
                ) : null}
                <div className="flex min-h-0 flex-1 flex-wrap">
                  <SideNav
                    active={page}
                    activeTab={tab}
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
                    <PageBoundary key={page}>
                      <Suspense fallback={<div className="flex-1" aria-busy="true" />}>
                        {page === "rules" ? (
                          <RulesPage
                            isAdmin={!user || user.role === "admin"}
                            canRun={!user || user.role !== "auditor"}
                          />
                        ) : page === "targets" && (!user || user.role === "admin") ? (
                          <AlertTargetsPage />
                        ) : page === "alerts" ? (
                          <AlertsPage
                            canClose={!user || user.role !== "auditor"}
                            isAdmin={!user || user.role === "admin"}
                          />
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
                        ) : page === "about" ? (
                          <AboutPage />
                        ) : page === "sso" && (!user || user.role === "admin") ? (
                          <SsoPage />
                        ) : page === "plugins" && (!user || user.role === "admin") ? (
                          <PluginsPage />
                        ) : page === "m365" ? (
                          <M365Page />
                        ) : page === "ai" || page === "agents" ? (
                          <AiUsagePage
                            isAdmin={!user || user.role === "admin"}
                            canExport={!user || user.role !== "auditor"}
                            area={page}
                          />
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
                        ) : page === "aisettings" && (!user || user.role === "admin") ? (
                          <AiSettings />
                        ) : page === "system" && (!user || user.role === "admin") ? (
                          <HealthPage isAdmin scope="system" />
                        ) : page === "system" ? (
                          // Backups, Page rollups, and Speed were Health tabs everyone saw:
                          // an old address says why it no longer opens for this person.
                          <ForAdministrators
                            title="System"
                            detail="Backups, page rollups, and page speed are shown to administrators. A failed backup raises an alert that everyone sees."
                          />
                        ) : page === "aisettings" ? (
                          <ForAdministrators
                            title="AI watch and catalog"
                            detail="What AI Watch alerts on, the MCP server rules, and the service catalog are set by administrators. The review status of each service is on AI usage."
                          />
                        ) : page === "investigate" ? (
                          <InvestigatePage />
                        ) : page === "overview" ? (
                          <ToHealth />
                        ) : page === "home" ? (
                          <HomeRedirect />
                        ) : page === "ask" ? (
                          <SqlOnly fallback={<ToLogs />}>
                            <AskPage isAdmin={!user || user.role === "admin"} />
                          </SqlOnly>
                        ) : page === "sources" ? (
                          // Open mode (no accounts) is the local admin.
                          <SourcesPage canManage={!user || user.role === "admin"} />
                        ) : (
                          // Logs (D206).
                          <SqlOnly fallback={<SqlOffNotice />}>
                            <SearchPage
                              key={`logs:${searchKey}:${searchNav}`}
                              canSave={!user || user.role !== "auditor"}
                            />
                          </SqlOnly>
                        )}
                      </Suspense>
                    </PageBoundary>
                  </main>
                </div>
              </div>
            </ViewerProvider>
          )}
        </AuthGate>
      )}
    </QueryClientProvider>
  );
}

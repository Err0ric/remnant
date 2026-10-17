import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { CopyBlock } from "@/features/sources/OtlpSetup";
import { ApiError, api } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/branding";
import { navigate } from "@/lib/route";

/** Settings > MCP server (ADR-0003): let AI assistants run read-only queries. */
export function McpPage() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["mcp-settings"], queryFn: api.mcpSettings });
  const [enabled, setEnabled] = useState(false);
  const [local, setLocal] = useState(false);
  useEffect(() => {
    if (settings.data) {
      setEnabled(settings.data.enabled);
      setLocal(settings.data.endpoint_local);
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () => api.saveMcpSettings({ enabled, endpoint_local: local }),
    onSuccess: (data) => client.setQueryData(["mcp-settings"], data),
  });
  const changed =
    settings.data !== undefined &&
    (settings.data.enabled !== enabled || settings.data.endpoint_local !== local);

  const name = PRODUCT_NAME.toLowerCase();
  const endpoint = `${window.location.origin}${settings.data?.path ?? "/api/mcp"}`;
  const claudeCode = `claude mcp add --transport http ${name} ${endpoint} --header "Authorization: Bearer YOUR_TOKEN"`;
  const desktop = JSON.stringify(
    { mcpServers: { [name]: { command: name, args: ["mcp"] } } },
    null,
    2,
  );

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "MCP server"]} title="MCP server" />
      <div className="flex max-w-4xl flex-col gap-4 px-5 py-3 text-sm">
        <p className="text-text-secondary">
          AI assistants that speak the Model Context Protocol (Claude Code, Claude Desktop, IDE
          agents) can read the schema and run read-only SQL over the logs. Each person connects with
          their own token and sees only the sources they can already read. Nothing can be changed
          through it.
        </p>

        <section
          aria-label="Access"
          className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">Access</h2>
          {settings.isError ? (
            <p role="alert" className="text-danger">
              {settings.error instanceof ApiError ? settings.error.message : "Could not load"}
            </p>
          ) : null}
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="font-semibold">Let AI assistants query logs</span>
              <span className="block text-text-secondary">
                Off by default. Turning it off refuses every client at once.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={local}
              disabled={!enabled}
              onChange={(e) => setLocal(e.target.checked)}
              aria-describedby="mcp-local-help"
              className="mt-0.5"
            />
            <span>
              <span className="font-semibold">Clients and their models run on our network</span>
              <span id="mcp-local-help" className="block text-text-secondary">
                {local
                  ? "Local-only sources are returned too. Only choose this when every client uses a model you host."
                  : `${PRODUCT_NAME} cannot see which model a client uses, so it assumes a cloud model: local-only sources are left out of every result.`}
              </span>
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={!changed || save.isPending}
              onClick={() => save.mutate()}
              className="h-8 rounded bg-accent px-4 font-semibold text-white hover:brightness-110 disabled:opacity-50"
            >
              {save.isPending ? "Saving" : "Save"}
            </button>
            {save.isSuccess && !changed ? <span className="text-ok">Saved</span> : null}
            {save.isError ? (
              <span role="alert" className="text-danger">
                {save.error instanceof ApiError ? save.error.message : "Could not save"}
              </span>
            ) : null}
          </div>
        </section>

        <section
          aria-label="Connect a client"
          className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">Connect a client</h2>
          <p className="text-text-secondary">
            Each person creates a token under{" "}
            <a
              href="/me"
              onClick={(e) => {
                e.preventDefault();
                navigate("me");
              }}
              className="text-accent-text"
            >
              Your account
            </a>{" "}
            and uses it in place of YOUR_TOKEN. Revoking the token disconnects that client.
          </p>
          <CopyBlock label="Address" text={endpoint} />
          <CopyBlock label="Claude Code" text={claudeCode} />
          <CopyBlock label="Claude Desktop (through the command-line tool)" text={desktop} />
          <p className="text-text-muted">
            The desktop entry runs <span className="font-mono">{name} mcp</span>, which uses the
            token saved by <span className="font-mono">{name} login</span>. With the generated
            self-signed certificate, Node-based clients also need{" "}
            <span className="font-mono">NODE_EXTRA_CA_CERTS</span> set to that certificate.
          </p>
        </section>

        <section
          aria-label="What clients can do"
          className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">What clients can do</h2>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-text-secondary">
            <li>
              Two tools: <span className="font-mono">get_schema</span> and{" "}
              <span className="font-mono">run_query</span> (one SELECT, the same guard as Search, at
              most 500 rows).
            </li>
            <li>
              Every result says that log values are data and may contain instructions that must not
              be followed.
            </li>
            <li>
              Every call is in the Audit log under <span className="font-mono">mcp.tool</span>, with
              the person, the client, and the SQL.
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}

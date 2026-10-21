# Outbound proxy

**Optional.** Only for networks where the server cannot reach the internet directly. Without these settings everything connects directly, as before. Design: [ADR-0018](../adr/ADR-0018-identity-and-proxy.md).

## What goes through the proxy

| Goes through the proxy | Stays direct |
|---|---|
| Microsoft 365 source (`login.microsoftonline.com`, `manage.office.com`, `graph.microsoft.com`, and the GCC and GCC High hosts) | Grafana Loki sources |
| Anthropic source (`api.anthropic.com`) | Generic webhook alerts |
| Teams and Slack alert targets | Email (SMTP) alerts |
| | AI providers (Ollama, other model servers) |

Only destinations with fixed public host names use the proxy. Everything else is usually inside your network, and connecting directly lets the server keep refusing link-local and metadata addresses. Proxy environment variables on the host (`HTTPS_PROXY` and the like) are never used.

## Settings

| Setting (compose `.env`) | Config key | Value |
|---|---|---|
| `HTTPS_PROXY_URL` | `network.https_proxy` | `http://proxy.corp.example:3128` (or `https://`). No user name or password in the URL |
| `PROXY_USERNAME`, `PROXY_PASSWORD` | `network.proxy_username`, `network.proxy_password` | Only if the proxy asks for basic authentication. Keep `.env` readable by root only |
| `PROXY_CA_BUNDLE` | `network.ca_bundle` | For a proxy that inspects TLS (Zscaler, Palo Alto decryption, Squid SSL bump): the proxy's CA certificate in PEM, placed in `./config` and named as `/srv/config/<file>.pem` |

Restart after changing them: `docker compose up -d`. A setting that does not make sense stops the server at start with a message saying which one, for example a proxy URL with a password in it.

## How it connects

- The server sends `CONNECT host:443` and lets the proxy resolve the name, so the server itself needs no external DNS.
- TLS still checks the service's certificate against its host name. With an inspecting proxy, that check passes only when its CA is in `PROXY_CA_BUNDLE`; without it, the source shows "Cannot reach".
- The CA bundle is also trusted for direct HTTPS from those sources and alerts, for networks that inspect TLS without an explicit proxy.

## Check it

1. **Settings > Sources and connectors > Add source**, choose Microsoft 365 or Anthropic, and use **Test connection**. Each feed should say **Works**.
2. **Settings > Alert targets**, use **Send test** on a Teams or Slack target.
3. In the proxy's log, the requests appear as `CONNECT login.microsoftonline.com:443` and so on.

## Security notes

- A proxy that inspects TLS sees connector traffic, including access tokens. Microsoft's tokens last about an hour and the app is read-only, but treat the proxy as part of the trust boundary.
- The proxy password is a secret: set it in `.env` (or the service environment), never in `config/app.yaml`.

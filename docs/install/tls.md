# HTTPS and certificates

| Bind address | Protocol |
|---|---|
| `127.0.0.1`, `::1`, `localhost` | Plain HTTP (local use only) |
| Anything else, including `0.0.0.0` in Docker | HTTPS, always |

There is no setting that serves plain HTTP on a network address.

## Default: generated self-signed certificate

On first start off loopback the server creates `data/tls/server.crt` and `data/tls/server.key` (mode 0600) and reuses them on every restart. The startup output prints the certificate's SHA-256 fingerprint:

```
Remnant listening on https://0.0.0.0:8080
Self-signed certificate: /srv/data/tls/server.crt
Verify in your browser: SHA-256 6A:3C:CD:...:D3:08
```

Compare it with the fingerprint your browser shows before accepting the warning. The certificate covers `localhost`, `127.0.0.1`, `::1`, and the machine's hostname. Add the names analysts actually type:

```
APP__SERVER__PUBLIC_NAMES=siem.corp.example,192.0.2.10
```

Names are only read when the certificate is created. To regenerate, stop the server, delete `data/tls/`, and start it again.

## Bring your own certificate

Use a certificate from your internal CA so browsers and the CLI trust it without warnings.

```yaml
# config/app.yaml
server:
  host: 0.0.0.0
  tls_cert: /srv/config/tls/siem.crt   # PEM, full chain
  tls_key: /srv/config/tls/siem.key    # PEM, readable only by the service account
```

Both must be set. If either file is missing the server refuses to start.

## Behind a reverse proxy

Run the proxy on the same host and bind the app to loopback, so the hop between them never leaves the machine:

```
APP__SERVER__HOST=127.0.0.1
```

```nginx
server {
    listen 443 ssl;
    server_name siem.corp.example;
    ssl_certificate     /etc/ssl/siem.crt;
    ssl_certificate_key /etc/ssl/siem.key;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

If the proxy runs on a different host, leave the app on its own HTTPS listener and point the proxy at `https://` with the app's certificate pinned or trusted.

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

### Proxy on a different host (SSL offload on an existing nginx)

Docker installs always serve HTTPS inside the container, so a proxy on another host re-encrypts to the app instead of sending plain HTTP. Users see the proxy's certificate; the app's self-signed certificate is only used on the hop between them.

```nginx
location / {
    proxy_pass https://192.0.2.20:8080;   # the app's address
    proxy_ssl_verify off;                 # self-signed backend; or proxy_ssl_trusted_certificate with data/tls/server.crt
    proxy_set_header Host $host;
}
```

```
APP_BIND=0.0.0.0
APP_PUBLIC_NAME=siem.corp.example
APP_PUBLIC_URL=https://siem.corp.example
```

Allow port 8080 on the app's host only from the proxy nodes. `APP_PUBLIC_URL` must be the address users type, because the setup link, alert links, and the SSO return address are built from it. The generated certificate is valid for 825 days; to renew it, stop the app, delete `data/tls/`, and start it again.

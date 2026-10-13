# Offline install (no internet on the server)

Use this when the server cannot reach Docker Hub, PyPI, and npm, or when a proxy that inspects TLS breaks `docker compose up --build` with certificate errors. You build once on a machine that has internet access, carry one folder over, and load it.

| Machine | Needs |
|---|---|
| Build machine (a homelab box, a laptop) | Docker with `buildx`, git, internet access, this repository |
| Server | Docker Engine with the Compose plugin; no internet access needed |

## 1. Build the bundle (build machine)

```bash
git clone https://github.com/Err0ric/remnant && cd remnant
scripts/offline-bundle.sh                  # add --with-ollama to carry the Ollama image too
```

It builds the image for `linux/amd64` (the usual server; use `--platform linux/arm64` for an ARM server), so an Apple Silicon Mac works as the build machine too. The result, `./offline-bundle/`:

| File | What |
|---|---|
| `app-image.tar.gz` | The app image, tagged `app:dev` as `docker-compose.yml` expects |
| `ollama-image.tar.gz` | Only with `--with-ollama` |
| `source.tar.gz` | The compose file, `.env.example`, docs, and scripts at the same commit |
| `SHA256SUMS` | Checksums for the three files |

## 2. Carry it over

Copy the folder by whatever your process allows (SCP from a jump host, a file share, removable media). The app image is a few hundred MB compressed.

## 3. Load and start (server)

```bash
cd offline-bundle
sha256sum -c SHA256SUMS                    # every line must say OK
sudo mkdir -p /opt/remnant && sudo tar -xzf source.tar.gz -C /opt/remnant
docker load < app-image.tar.gz             # prints: Loaded image: app:dev
# docker load < ollama-image.tar.gz        # if you brought it

cd /opt/remnant
cp .env.example .env                       # set APP_BIND, APP_PUBLIC_NAME, LOGS_DIR as in team-vm.md
docker compose up -d --no-build
docker compose logs app | grep -A1 "one-time link"
```

`--no-build` makes Compose use the loaded image instead of trying to build (which would need the internet). From here the install is the same as [team-vm.md](team-vm.md).

## Updating

Repeat steps 1 to 3 with the newer checkout. Before `docker load`, take a backup ([backup.md](backup.md)). Then:

```bash
docker load < app-image.tar.gz
cd /opt/remnant && sudo tar -xzf /path/to/offline-bundle/source.tar.gz
docker compose up -d --no-build --force-recreate app
```

`.env` and the data volume are not in the bundle, so they stay as they are.

## Local models offline

The Ollama image does not include models. Either point **AI providers** at an Ollama host on your network that already has the model, or pull the model on the build machine and copy Ollama's model folder (`~/.ollama/models`, or the `ollama-models` volume) into the server's `ollama-models` volume before starting it.

## Notes

- The demo log generator (`--profile demo`) uses a separate `python:3.12-slim` image that is not in the bundle; skip it offline or `docker save` that image too.
- Sigma rules: clone SigmaHQ on the build machine and carry the folder; set `RULES_DIR` in `.env`.
- Single sign-on still needs the server to reach your identity provider (Entra, Authelia) over HTTPS.

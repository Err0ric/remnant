#!/usr/bin/env bash
# Build everything on a machine with internet access and pack it for one that has none
# (or one whose proxy breaks the build). See docs/install/offline.md.
#
#   scripts/offline-bundle.sh [--platform linux/amd64] [--with-ollama] [--out DIR]
#
# Writes DIR/ (default ./offline-bundle):
#   app-image.tar.gz      the built app image (tag app:dev, what docker-compose.yml uses)
#   ollama-image.tar.gz   optional, with --with-ollama
#   source.tar.gz         this checkout (git archive of HEAD): compose file, docs, scripts
#   SHA256SUMS            checksums for all of the above
set -euo pipefail

platform="linux/amd64"
with_ollama=0
out="offline-bundle"
while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --with-ollama) with_ollama=1; shift ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."
if ! git diff --quiet HEAD -- 2>/dev/null; then
  echo "note: uncommitted changes are built into the image but not into source.tar.gz" >&2
fi
mkdir -p "$out"

echo "Building app:dev for $platform ..."
# --load keeps the result in the local image store so docker save can read it.
docker buildx build --platform "$platform" -t app:dev --load .
docker save app:dev | gzip > "$out/app-image.tar.gz"

if [ "$with_ollama" = 1 ]; then
  ollama_image=$(awk '/^  ollama:/{f=1} f && /image:/{print $2; exit}' docker-compose.yml)
  echo "Pulling $ollama_image for $platform ..."
  docker pull --platform "$platform" "$ollama_image"
  docker save "$ollama_image" | gzip > "$out/ollama-image.tar.gz"
fi

git archive --format=tar.gz -o "$out/source.tar.gz" HEAD
if command -v sha256sum >/dev/null; then sum="sha256sum"; else sum="shasum -a 256"; fi  # macOS
(cd "$out" && $sum ./*.tar.gz > SHA256SUMS)

echo
echo "Bundle in $out:"
ls -lh "$out"
echo "Copy the folder to the target machine and follow docs/install/offline.md."

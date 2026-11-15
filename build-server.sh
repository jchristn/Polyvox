#!/usr/bin/env bash
# Build and push the polyvox server image for the supplied version and latest.
# Usage: build-server.sh <tag> (initial release: v1.0.0)
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
    echo "Usage: $(basename "$0") <tag>"
    echo "Example: $(basename "$0") v1.0.0"
    exit 1
fi
if [[ ! "$1" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
    echo "Error: supply a valid Docker image tag."
    exit 1
fi

TAG="$1"
IMAGE="jchristn77/polyvox-server"
BUILDER="cloud-jchristn77-jchristn77"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use the same preconfigured Docker Build Cloud builder as Armada.
# Authenticate with docker login before invoking this publishing command.
docker buildx inspect "$BUILDER" >/dev/null
cd "$ROOT_DIR"
echo "Building and pushing ${IMAGE}:${TAG} and ${IMAGE}:latest..."
docker buildx build \
    --builder "$BUILDER" \
    --platform linux/amd64,linux/arm64/v8 \
    --provenance=false --sbom=false \
    --build-arg API_MODE=true \
    -f dockerfile-cpu \
    -t "${IMAGE}:${TAG}" \
    -t "${IMAGE}:latest" \
    --push .

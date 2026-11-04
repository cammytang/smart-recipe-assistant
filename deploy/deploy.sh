#!/usr/bin/env bash
# Invoked over SSH; never prints environment files or application logs.
set -euo pipefail
umask 077

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $# == 3 ]] || die "Usage: deploy.sh DEPLOY_DIR IMAGE_OWNER sha-FULL_COMMIT_SHA"
deploy_dir=$1
owner=$2
version=$3
[[ "$deploy_dir" =~ ^/[a-zA-Z0-9_./-]+$ ]] || die "Invalid deployment directory"
[[ "$owner" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "Invalid image owner"
[[ "$version" =~ ^sha-[a-f0-9]{40}$ ]] || die "Version must be sha- followed by a full commit SHA"
bundle_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$deploy_dir"
[[ -s backend.env ]] || die "backend.env missing or empty"
for directory in runtime/qdrant_data runtime/notes runtime/logs; do
    [[ -d "$directory" ]] || die "Required persistent directory missing: $directory"
done
command -v flock >/dev/null || die "flock is required"
command -v curl >/dev/null || die "curl is required"
exec 9>.deploy.lock
flock -n 9 || die "Another deployment is running"

docker_cmd=(sudo -n docker)
"${docker_cmd[@]}" info >/dev/null
"${docker_cmd[@]}" network inspect smart-recipe >/dev/null
"${docker_cmd[@]}" compose version >/dev/null

export BACKEND_IMAGE="ghcr.io/${owner}/smart-recipe-backend:${version}"
export FRONTEND_IMAGE="ghcr.io/${owner}/smart-recipe-frontend:${version}"
compose=("${docker_cmd[@]}" compose --project-name smart-recipe-app
    --project-directory "$deploy_dir" --env-file /dev/null -f "$bundle_dir/compose.yaml")
"${compose[@]}" config --quiet

# Pull BOTH images before interrupting any running application container.
"${compose[@]}" pull backend frontend
previous_backend=$("${docker_cmd[@]}" inspect --format '{{.Config.Image}}' smart-recipe-backend 2>/dev/null || true)
previous_frontend=$("${docker_cmd[@]}" inspect --format '{{.Config.Image}}' smart-recipe-frontend 2>/dev/null || true)

rollback() {
    local failed_status=$?
    trap - ERR
    echo "Deployment failed. Attempting to restore previous application images." >&2
    if [[ -n "$previous_backend" && -n "$previous_frontend" ]]; then
        export BACKEND_IMAGE="$previous_backend" FRONTEND_IMAGE="$previous_frontend"
        if "${compose[@]}" up -d --force-recreate --pull never --wait --wait-timeout 180 backend frontend; then
            echo "Previous images restored. Deployment remains FAILED." >&2
        else
            echo "ROLLBACK FAILED: inspect containers on the server." >&2
        fi
    else
        echo "No complete previous image pair available for rollback." >&2
    fi
    exit "$failed_status"
}
trap rollback ERR

# One-time adoption of containers started with docker run or another Compose project.
# Never remove volumes or touch database/gateway containers.
for container in smart-recipe-backend smart-recipe-frontend; do
    if "${docker_cmd[@]}" container inspect "$container" >/dev/null 2>&1; then
        project=$("${docker_cmd[@]}" inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")
        if [[ "$project" != smart-recipe-app ]]; then
            "${docker_cmd[@]}" stop "$container"
            "${docker_cmd[@]}" rm "$container"
        fi
    fi
done

"${compose[@]}" up -d --force-recreate --pull never --wait --wait-timeout 180 backend frontend
# Verify frontend-to-backend routing and the existing public HTTPS gateway.
"${docker_cmd[@]}" exec smart-recipe-frontend wget -q -T 15 -O /dev/null http://127.0.0.1/api/healthz
curl --fail --silent --show-error --max-time 20 --retry 2 --retry-delay 3 \
    https://chef-ai.club/api/healthz >/dev/null
trap - ERR

if [[ -f .deployed-version ]]; then
    cp .deployed-version .previous-version
fi
printf '%s\n' "$version" > .deployed-version
echo "Deployment healthy: $version"

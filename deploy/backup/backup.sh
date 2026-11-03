#!/usr/bin/env bash
# Nightly logical backup of the quizz database.
#   BACKUP_DIR  where dumps go (default /var/backups/quizz): keep it OUTSIDE the
#               Docker volume, ideally on another disk.
#   KEEP        how many dumps to keep (default 14)
# Restore: see docs/architecture/deploy.md.
set -euo pipefail
# Dumps contain password hashes: owner-readable only.
umask 077

cd "$(dirname "$0")/.."   # deploy/, where docker-compose.yml lives

BACKUP_DIR="${BACKUP_DIR:-/var/backups/quizz}"
KEEP="${KEEP:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$BACKUP_DIR/.quizz-$stamp.partial"
final="$BACKUP_DIR/quizz-$stamp.dump"

# A failed or interrupted dump must never look like a valid backup.
trap 'rm -f "$partial"' EXIT

docker compose exec -T db pg_dump -U quizz -d quizz --format=custom > "$partial"
[ -s "$partial" ] || { echo "backup is empty, aborting" >&2; exit 1; }
mv "$partial" "$final"
trap - EXIT

# Prune: newest $KEEP stay.
ls -1t "$BACKUP_DIR"/quizz-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "backup written: $final"

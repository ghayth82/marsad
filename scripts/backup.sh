#!/usr/bin/env bash
# نسخة احتياطية: قاعدة البيانات + مرآة للأرشيف. تُجدول يوميًا (cron) على الخادم.
set -euo pipefail
APP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$APP_HOME"
# المسارات تُحسب بنفس منطق start.sh (وتُنشأ إن نقصت)
out="$(./scripts/start.sh --prepare-only)"
DATA_ROOT="$(printf '%s\n' "$out" | sed -n 's/^مجلد البيانات: *//p')"
BACKUP_ROOT="$(printf '%s\n' "$out" | sed -n 's/^مجلد النسخ الاحتياطي: *//p')"
STAMP="$(date +%Y%m%d-%H%M%S)"
docker compose exec -T postgres pg_dump -U marsad -d marsad -Fc -f "/backups/db/marsad-$STAMP.dump"
echo "قاعدة البيانات -> $BACKUP_ROOT/db/marsad-$STAMP.dump"
# مرآة لملفات المحتوى (مجلدات الوظائف العربية وarchive) إن كان مجلد النسخ خارج مجلد البيانات
case "$BACKUP_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) rsync -a --delete --exclude=/db --exclude=/search --exclude=/logs --exclude=/tmp --exclude=/uploads --exclude=/models \
       "$DATA_ROOT/" "$BACKUP_ROOT/archive/"
     echo "ملفات المحتوى -> $BACKUP_ROOT/archive" ;;
esac
# الإبقاء على آخر 14 نسخة من قاعدة البيانات
ls -1t "$BACKUP_ROOT"/db/*.dump 2>/dev/null | tail -n +15 | xargs -r rm -f

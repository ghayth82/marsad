#!/usr/bin/env bash
# مرصد التحقق — التشغيل على لينكس/ماك/خادم.
#   ./scripts/start.sh               تجهيز المجلدات ثم تشغيل كل الخدمات
#   ./scripts/start.sh --prepare-only  تجهيز المجلدات فقط وطباعة أماكنها
set -euo pipefail

APP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_HOME"
PREPARE_ONLY=0; [[ "${1:-}" == "--prepare-only" ]] && PREPARE_ONLY=1

say()  { printf '%s\n' "$*"; }
warn() { printf 'تنبيه: %s\n' "$*" >&2; }
die()  { printf 'خطأ: %s\n' "$*" >&2; exit 1; }

# 1) ملف الإعدادات وتوليد الأسرار الناقصة
if [[ ! -f .env ]]; then cp .env.example .env; say "أُنشئ ملف .env من النموذج."; fi
for key in POSTGRES_PASSWORD MEILI_MASTER_KEY MARSAD_SECRET_KEY; do
  if grep -qE "^${key}=\s*$" .env || ! grep -qE "^${key}=" .env; then
    val="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40 || true)"
    if grep -qE "^${key}=" .env; then
      sed -i.bak "s|^${key}=.*|${key}=${val}|" .env && rm -f .env.bak
    else
      printf '%s=%s\n' "$key" "$val" >> .env
    fi
    say "وُلّد ${key} تلقائيًا."
  fi
done

# 2) تنفيذ أي «طلب تغيير مكان» من الواجهة، ثم إنشاء المجلدات الناقصة.
#    المنطق كله في backend/marsad/core/storage_config.py (مُختبر).
command -v python3 >/dev/null || die "Python 3 مطلوب على الخادم."
if grep -qE '"pending": *\{' config/storage.json 2>/dev/null && command -v docker >/dev/null; then
  say "يوجد طلب تغيير مكان التخزين: إيقاف الخدمات قبل النسخ..."
  docker compose --env-file .env stop >/dev/null 2>&1 || true
fi
OUT="$(PYTHONPATH="$APP_HOME/backend" MARSAD_HOME="$APP_HOME" python3 -m marsad.core.storage_config prepare)" \
  || die "تعذّر تجهيز مجلدات البيانات."
DATA_ROOT="$(printf '%s\n' "$OUT" | sed -n 's/^MARSAD_DATA_ROOT=//p')"
BACKUP_ROOT="$(printf '%s\n' "$OUT" | sed -n 's/^MARSAD_BACKUP_ROOT=//p')"

# 3) المساحة الفارغة
MIN_GB="$(grep -E '^MARSAD_MIN_FREE_GB=' .env | cut -d= -f2 | tr -d '\r')"; MIN_GB="${MIN_GB:-20}"
FREE_GB="$(df -Pk "$DATA_ROOT" | awk 'NR==2{print int($4/1048576)}')"
(( FREE_GB < MIN_GB )) && warn "المساحة الفارغة في قرص البيانات ${FREE_GB} غيغابايت فقط (المطلوب ${MIN_GB} على الأقل)."

export MARSAD_DATA_ROOT="$DATA_ROOT" MARSAD_BACKUP_ROOT="$BACKUP_ROOT"
say "مجلد البيانات:        $DATA_ROOT"
say "مجلد النسخ الاحتياطي: $BACKUP_ROOT"
say "المساحة الفارغة:      ${FREE_GB} غيغابايت"
(( PREPARE_ONLY )) && exit 0

# 4) التشغيل، مع استعادة تلقائية إن كان هذا جهازًا جديدًا ولدينا نسخة
command -v docker >/dev/null || die "Docker غير مثبّت."
FRESH=0; docker volume inspect marsad_pgdata >/dev/null 2>&1 || FRESH=1
docker compose --env-file .env up -d
say "انتظار قاعدة البيانات..."
for _ in $(seq 1 60); do
  docker compose exec -T postgres pg_isready -U marsad -d marsad >/dev/null 2>&1 && break; sleep 2
done
LATEST="$(ls -1t "$BACKUP_ROOT"/db/*.dump 2>/dev/null | head -n1 || true)"
if (( FRESH )) && [[ -n "$LATEST" ]]; then
  say "جهاز جديد: استعادة آخر نسخة $(basename "$LATEST")"
  docker compose exec -T postgres pg_restore -U marsad -d marsad --no-owner --clean --if-exists \
    "/backups/db/$(basename "$LATEST")" || warn "الاستعادة أنهت بتحذيرات، راجع السجل."
fi
say "مرصد التحقق يعمل."

#!/usr/bin/env bash
# مرصد التحقق — أمر التثبيت على خادم لينكس (Ubuntu 24.04)، محلي أو سحابي.
# يُشغَّل مرة واحدة: sudo bash install.sh
# يسأل ثلاثة أسئلة، ثم يثبّت كل شيء وحده. إعادة تشغيله آمنة: لا يمس بيانات موجودة.
set -euo pipefail

MARSAD_DIR="${MARSAD_DIR:-/srv/marsad}"
REPO_RAW="${MARSAD_REPO_RAW:-https://raw.githubusercontent.com/ghayth82/marsad/main/deploy/server}"
IMAGE="${MARSAD_IMAGE:-ghcr.io/ghayth82/marsad:latest}"
APP_UID=10001

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf 'خطأ: %s\n' "$*" >&2; exit 1; }
ask()  { local q="$1" def="${2:-}" a; read -r -p "$q${def:+ [$def]}: " a; printf '%s' "${a:-$def}"; }
secret() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40 || true; }

[[ $EUID -eq 0 ]] || die "شغّله بصلاحية المدير: sudo bash install.sh"
command -v apt-get >/dev/null || die "هذا الأمر مكتوب لـ Ubuntu أو Debian."

# ---------- الأسئلة ----------
say "مرصد التحقق — التثبيت على الخادم"
if [[ -f "$MARSAD_DIR/.env" ]]; then
  say "يوجد تثبيت سابق في $MARSAD_DIR: سأحدّثه دون المساس بالبيانات."
  # shellcheck disable=SC1091
  source <(grep -E '^(MARSAD_DOMAIN|MARSAD_TLS|GHCR_USER)=' "$MARSAD_DIR/.env")
  DOMAIN="$MARSAD_DOMAIN"; TLS="$MARSAD_TLS"
else
  echo "1) هل يُفتح البرنامج من الإنترنت باسم نطاق، أم من الشبكة الداخلية فقط؟"
  MODE="$(ask 'اكتب: نطاق أو داخلي' 'نطاق')"
  if [[ "$MODE" == داخلي* || "$MODE" == lan* ]]; then
    DOMAIN="$(ask '2) الاسم المحلي' 'marsad.local')"
    TLS="internal"
  else
    DOMAIN="$(ask '2) اسم النطاق (مثل marsad.example.com)')"
    [[ -n "$DOMAIN" ]] || die "اسم النطاق مطلوب."
    TLS="$(ask '3) بريدك لشهادة الأمان')"
    [[ "$TLS" == *@* ]] || die "البريد غير صحيح."
  fi
fi
GHCR_USER="${GHCR_USER:-$(ask 'حساب GitHub' 'ghayth82')}"
read -r -s -p "رمز القراءة من GitHub (read:packages) — لا يظهر أثناء الكتابة: " GHCR_TOKEN; echo
[[ -n "$GHCR_TOKEN" ]] || die "الرمز مطلوب لتنزيل البرنامج من المستودع الخاص."

# ---------- Docker والجدار الناري ----------
say "تثبيت Docker وتحديثات الأمان..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl ufw unattended-upgrades >/dev/null
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
fi
systemctl enable --now docker >/dev/null

say "الجدار الناري: الويب (80، 443) والدخول الإداري (22) فقط..."
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# ---------- المجلدات والإعدادات ----------
say "إنشاء المجلدات في $MARSAD_DIR..."
mkdir -p "$MARSAD_DIR"/{data,backups/db,backups/archive,config}
chown -R "$APP_UID" "$MARSAD_DIR"/{data,backups,config}
chmod 700 "$MARSAD_DIR"
for f in docker-compose.yml Caddyfile; do
  curl -fsSL -H "Authorization: Bearer $GHCR_TOKEN" "$REPO_RAW/$f" -o "$MARSAD_DIR/$f" \
    || [[ -f "$MARSAD_DIR/$f" ]] || die "تعذّر تنزيل $f (تأكد من الرمز)."
done

if [[ ! -f "$MARSAD_DIR/.env" ]]; then
  umask 077
  cat > "$MARSAD_DIR/.env" <<ENV
MARSAD_DOMAIN=$DOMAIN
MARSAD_TLS=$TLS
MARSAD_IMAGE=$IMAGE
GHCR_USER=$GHCR_USER
POSTGRES_PASSWORD=$(secret)
MEILI_MASTER_KEY=$(secret)
MARSAD_SECRET_KEY=$(secret)
ENV
fi

# ---------- التنزيل والتشغيل ----------
say "تنزيل البرنامج وتشغيله..."
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null
cd "$MARSAD_DIR"
docker compose pull -q
docker compose up -d

# ---------- أداة الإدارة والنسخ اليومي ----------
curl -fsSL -H "Authorization: Bearer $GHCR_TOKEN" "$REPO_RAW/marsad" -o /usr/local/bin/marsad \
  || die "تعذّر تنزيل أداة الإدارة."
chmod 755 /usr/local/bin/marsad
cat > /etc/cron.d/marsad <<'CRON'
# نسخة يومية 02:40، واختبار استعادة شهري (أول يوم 04:10)
40 2 * * * root /usr/local/bin/marsad backup >> /var/log/marsad-backup.log 2>&1
10 4 1 * * root /usr/local/bin/marsad restore-test >> /var/log/marsad-backup.log 2>&1
CRON

say "انتظار جاهزية البرنامج..."
for _ in $(seq 1 60); do
  docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" \
    >/dev/null 2>&1 && break
  sleep 3
done

say "مرصد التحقق يعمل على https://$DOMAIN"
[[ "$TLS" == internal ]] && echo "شبكة داخلية: يظهر للمتصفح تحذير الشهادة الداخلية أول مرة؛ يمكن تثبيت شهادتها على أجهزة المكتب (marsad cert)."
echo "افتح الرابط وأنشئ حساب المدير، أو استورد ملف النقل من جهازك."
echo "أوامر مفيدة: marsad status | marsad update | marsad backup | marsad logs"

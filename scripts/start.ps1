# مرصد التحقق — أداة تطوير مؤقتة على ويندوز (Docker Desktop).
# المستخدم النهائي لا يحتاجها: المُثبِّت Marsad-Setup.exe يحل محلها.
#   .\scripts\start.ps1               تجهيز المجلدات ثم تشغيل كل الخدمات
#   .\scripts\start.ps1 -PrepareOnly  تجهيز المجلدات فقط وطباعة أماكنها
# نفس منطق backend/marsad/core/storage_config.py (المرجع المُختبر)، لأن
# Python غير مضمون على جهاز ويندوز.
param([switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$AppHome = Split-Path -Parent $PSScriptRoot
Set-Location $AppHome
$ConfigDir = Join-Path $AppHome 'config'
$Utf8 = New-Object Text.UTF8Encoding $false
$Subdirs = 'archive','exports','reports','backups','logs','uploads','tmp'
$Marker = '.marsad-data'

function Say($m)  { Write-Host $m }
function Warn($m) { Write-Host "تنبيه: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "خطأ: $m" -ForegroundColor Red; exit 1 }
function Invoke-Quiet([scriptblock]$b) {
  # أوامر خارجية قد تكتب أخطاء (مثل Docker المتوقف) دون أن توقف السكربت
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $b 2>&1 | Out-Null } catch { } finally { $ErrorActionPreference = $old }
}
function Now()    { (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss+00:00') }

# ---------- 1) ملف الإعدادات والأسرار ----------
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Say 'أُنشئ ملف .env من النموذج.' }
$envLines = [Collections.Generic.List[string]]([IO.File]::ReadAllLines((Join-Path $AppHome '.env'), $Utf8))
$chars = [char[]]'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
function New-Secret { $b = New-Object byte[] 40; $rng.GetBytes($b); -join ($b | ForEach-Object { $chars[$_ % $chars.Length] }) }
foreach ($key in 'POSTGRES_PASSWORD','MEILI_MASTER_KEY','MARSAD_SECRET_KEY') {
  $i = $envLines.FindIndex({ param($l) $l -match "^$key=" })
  if ($i -lt 0) { $envLines.Add("$key=$(New-Secret)"); Say "وُلّد $key تلقائيًا." }
  elseif ($envLines[$i] -match "^$key=\s*$") { $envLines[$i] = "$key=$(New-Secret)"; Say "وُلّد $key تلقائيًا." }
}
[IO.File]::WriteAllLines((Join-Path $AppHome '.env'), $envLines, $Utf8)
function EnvGet($k) { $l = $envLines | Where-Object { $_ -match "^$k=" } | Select-Object -Last 1; if ($l) { $l.Substring($k.Length + 1).Trim().Trim('"') } }

# ---------- أدوات المسارات ----------
function Resolve-MarsadPath([string]$raw) {
  $p = [Environment]::ExpandEnvironmentVariables($raw.Trim().Trim('"').Trim("'"))
  if ($p.StartsWith('~')) { $p = Join-Path $HOME $p.Substring(1).TrimStart('\','/') }
  if (-not [IO.Path]::IsPathRooted($p)) { $p = Join-Path $AppHome $p }
  [IO.Path]::GetFullPath($p).TrimEnd('\')
}
function Test-DiskAvailable([string]$p) { (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path $p -Parent)) }
function Assert-Writable([string]$p) {
  New-Item -ItemType Directory -Force -Path $p | Out-Null
  $t = Join-Path $p ".write-test-$PID"; [IO.File]::WriteAllText($t, 'x'); Remove-Item -LiteralPath $t
}
function Test-Within([string]$a, [string]$b) { ($a + '\').StartsWith($b + '\', [StringComparison]::OrdinalIgnoreCase) }
function Get-TreeStats([string]$p) {
  $f = Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue
  @{ Files = @($f).Count; Size = [int64](($f | Measure-Object Length -Sum).Sum) }
}
function Get-FreeBytes([string]$p) { (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($p))).AvailableFreeSpace }

# ---------- 2) config/storage.json ----------
$StorageFile = Join-Path $ConfigDir 'storage.json'
$cfg = [ordered]@{ data_dir = './data'; backup_dir = ''; pending = $null; last_error = $null; history = @() }
if (Test-Path $StorageFile) {
  try {
    $j = [IO.File]::ReadAllText($StorageFile, $Utf8) | ConvertFrom-Json
    foreach ($p in $j.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
  } catch { Warn "تعذّرت قراءة $StorageFile؛ استُخدمت القيم الافتراضية." }
}
function Save-Config {
  New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
  $tmp = "$StorageFile.tmp"
  [IO.File]::WriteAllText($tmp, ($cfg | ConvertTo-Json -Depth 10), $Utf8)
  Move-Item -Force -LiteralPath $tmp -Destination $StorageFile
}

# ---------- 3) تنفيذ طلب تغيير المكان القادم من الواجهة ----------
$pending = $cfg.pending
if ($pending) {
  Say 'يوجد طلب تغيير مكان التخزين: إيقاف الخدمات قبل النسخ...'
  if (Get-Command docker -ErrorAction SilentlyContinue) { Invoke-Quiet { docker compose --env-file .env stop } }
  try {
    if ($pending.data_dir -and $pending.data_dir -ne $cfg.data_dir) {
      $old = Resolve-MarsadPath $cfg.data_dir
      $new = Resolve-MarsadPath $pending.data_dir
      if ((Test-Within $new $old) -or (Test-Within $old $new)) { throw 'لا يمكن أن يكون المكان الجديد داخل القديم أو العكس' }
      if (-not (Test-DiskAvailable $new)) { throw "القرص أو المجلد الأب غير موجود: $(Split-Path $new -Parent)" }
      Assert-Writable $new
      $foreign = Get-ChildItem -LiteralPath $new -Force | Where-Object { $_.Name -ne $Marker }
      if ($foreign -and -not (Test-Path -LiteralPath (Join-Path $new $Marker))) { throw "المجلد $new فيه ملفات ليست من مرصد؛ اختر مجلدًا فارغًا" }
      if ($pending.move_data -ne $false -and (Test-Path -LiteralPath $old)) {
        $src = Get-TreeStats $old
        if ($src.Size -gt (Get-FreeBytes $new) * 0.95) { throw ('المساحة غير كافية: البيانات {0:N1} غيغابايت' -f ($src.Size / 1GB)) }
        robocopy $old $new /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "فشل النسخ (robocopy $LASTEXITCODE)" }
        $dst = Get-TreeStats $new
        if ($dst.Files -lt $src.Files -or $dst.Size -lt $src.Size) { throw 'النسخ لم يكتمل؛ لم يُعتمد المكان الجديد' }
        Say "نُسخ $($src.Files) ملفًا. المجلد القديم $old باقٍ ولم يُحذف."
      }
    }
    if ($null -ne $pending.backup_dir -and $pending.backup_dir -ne $cfg.backup_dir -and $pending.backup_dir) {
      $b = Resolve-MarsadPath $pending.backup_dir
      if (-not (Test-DiskAvailable $b)) { throw "قرص النسخ الاحتياطي غير موصول: $(Split-Path $b -Parent)" }
      Assert-Writable $b
    }
    $toData = if ($pending.data_dir) { $pending.data_dir } else { $cfg.data_dir }
    $toBackup = if ($null -ne $pending.backup_dir) { $pending.backup_dir } else { $cfg.backup_dir }
    $cfg.history = @($cfg.history) + @([ordered]@{
      from = [ordered]@{ data_dir = $cfg.data_dir; backup_dir = $cfg.backup_dir }
      to   = [ordered]@{ data_dir = $toData; backup_dir = $toBackup }
      requested_by = $pending.requested_by; applied_at = (Now) })
    $cfg.data_dir = $toData; $cfg.backup_dir = $toBackup
    $cfg.pending = $null; $cfg.last_error = $null
    Save-Config
  } catch {
    $cfg.pending = $null
    $cfg.last_error = [ordered]@{ message = "$($_.Exception.Message)"; at = (Now); request = $pending }
    Save-Config
    Warn "لم يُطبَّق تغيير المكان: $($_.Exception.Message)"
  }
}

# ---------- 4) إنشاء المجلدات الناقصة ----------
$DataRoot = Resolve-MarsadPath $(if ($cfg.data_dir) { $cfg.data_dir } else { './data' })
try { Assert-Writable $DataRoot } catch { Die "لا يمكن إنشاء مجلد البيانات أو الكتابة فيه: $DataRoot" }
New-Item -ItemType File -Force -Path (Join-Path $DataRoot $Marker) | Out-Null
foreach ($d in $Subdirs) { New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $d) | Out-Null }

$BackupRoot = Join-Path $DataRoot 'backups'; $fallback = $false; $warnings = @()
if ($cfg.backup_dir) {
  $t = Resolve-MarsadPath $cfg.backup_dir
  if (Test-DiskAvailable $t) {
    try { Assert-Writable $t; $BackupRoot = $t } catch { $fallback = $true }
  } else { $fallback = $true }
  if ($fallback) { $warnings += "مجلد النسخ الاحتياطي $t غير متاح (القرص غير موصول؟)؛ استُخدم مؤقتًا $BackupRoot"; Warn $warnings[-1] }
}
foreach ($d in 'db','archive') { New-Item -ItemType Directory -Force -Path (Join-Path $BackupRoot $d) | Out-Null }

# ---------- 5) معلومات الأقراص للواجهة ----------
function DiskInfo([string]$p) { $di = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($p)); [ordered]@{ path = $p; free_gb = [math]::Round($di.AvailableFreeSpace / 1GB, 1); total_gb = [math]::Round($di.TotalSize / 1GB, 1) } }
$drives = [IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -in 'Fixed','Removable' } |
  ForEach-Object { [ordered]@{ path = $_.Name; label = $_.VolumeLabel; type = "$($_.DriveType)"; free_gb = [math]::Round($_.AvailableFreeSpace / 1GB, 1); total_gb = [math]::Round($_.TotalSize / 1GB, 1) } }
$info = [ordered]@{ generated_at = (Now); os = 'Windows'; data = (DiskInfo $DataRoot); backups = (DiskInfo $BackupRoot)
  backup_fallback = $fallback; warnings = $warnings; drives = @($drives) }
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
[IO.File]::WriteAllText((Join-Path $ConfigDir 'host-info.json'), ($info | ConvertTo-Json -Depth 6), $Utf8)

$minGb = [int]$(if (EnvGet 'MARSAD_MIN_FREE_GB') { EnvGet 'MARSAD_MIN_FREE_GB' } else { 20 })
if ($info.data.free_gb -lt $minGb) { Warn "المساحة الفارغة في قرص البيانات $($info.data.free_gb) غيغابايت فقط (المطلوب $minGb على الأقل)." }

$env:MARSAD_DATA_ROOT = $DataRoot; $env:MARSAD_BACKUP_ROOT = $BackupRoot
Say "مجلد البيانات:        $DataRoot"
Say "مجلد النسخ الاحتياطي: $BackupRoot"
Say "المساحة الفارغة:      $($info.data.free_gb) غيغابايت"
if ($PrepareOnly) { exit 0 }

# ---------- 6) التشغيل، مع استعادة تلقائية على جهاز جديد ----------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die 'Docker Desktop غير مثبّت أو غير مشغّل.' }
Invoke-Quiet { docker volume inspect marsad_pgdata }; $fresh = ($LASTEXITCODE -ne 0)
docker compose --env-file .env up -d
if ($LASTEXITCODE -ne 0) { Die 'فشل تشغيل الخدمات؛ تأكد أن Docker Desktop يعمل.' }
Say 'انتظار قاعدة البيانات...'
for ($i = 0; $i -lt 60; $i++) { Invoke-Quiet { docker compose exec -T postgres pg_isready -U marsad -d marsad }; if ($LASTEXITCODE -eq 0) { break }; Start-Sleep 2 }
$latest = Get-ChildItem (Join-Path $BackupRoot 'db') -Filter *.dump -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($fresh -and $latest) {
  Say "جهاز جديد: استعادة آخر نسخة $($latest.Name)"
  docker compose exec -T postgres pg_restore -U marsad -d marsad --no-owner --clean --if-exists "/backups/db/$($latest.Name)"
  if ($LASTEXITCODE -ne 0) { Warn 'الاستعادة أنهت بتحذيرات، راجع السجل.' }
}
Say 'مرصد التحقق يعمل.'

# نسخة احتياطية على ويندوز: قاعدة البيانات + مرآة للأرشيف.
# تُجدول يوميًا عبر Task Scheduler، أو تُشغَّل يدويًا.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$AppHome = Split-Path -Parent $PSScriptRoot
Set-Location $AppHome

# المسارات تُحسب بنفس منطق start.ps1 (وتُنشأ إن نقصت)
$out = & (Join-Path $PSScriptRoot 'start.ps1') -PrepareOnly
$DataRoot   = ($out | Where-Object { $_ -match '^مجلد البيانات:' }) -replace '^مجلد البيانات:\s*', ''
$BackupRoot = ($out | Where-Object { $_ -match '^مجلد النسخ الاحتياطي:' }) -replace '^مجلد النسخ الاحتياطي:\s*', ''
if (-not $BackupRoot) { $BackupRoot = $env:MARSAD_BACKUP_ROOT; $DataRoot = $env:MARSAD_DATA_ROOT }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
docker compose --env-file .env exec -T postgres pg_dump -U marsad -d marsad -Fc -f "/backups/db/marsad-$stamp.dump"
if ($LASTEXITCODE -ne 0) { Write-Host 'خطأ: فشل نسخ قاعدة البيانات (هل الخدمات تعمل؟)' -ForegroundColor Red; exit 1 }
Write-Host "قاعدة البيانات -> $BackupRoot\db\marsad-$stamp.dump"

if ($BackupRoot -ne (Join-Path $DataRoot 'backups')) {
  robocopy (Join-Path $DataRoot 'archive') (Join-Path $BackupRoot 'archive') /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host 'تنبيه: نسخ الأرشيف لم يكتمل' -ForegroundColor Yellow } else { Write-Host "الأرشيف -> $BackupRoot\archive" }
}
# الإبقاء على آخر 14 نسخة
Get-ChildItem (Join-Path $BackupRoot 'db') -Filter *.dump | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 | Remove-Item

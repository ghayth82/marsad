// مرصد التحقق — غلاف سطح المكتب.
// يشغّل المكوّنات المضمَّنة (PostgreSQL، Meilisearch، الخادم الداخلي)، ثم يفتح الواجهة في نافذة البرنامج.
// يبقى في الخلفية بأيقونة بجانب الساعة حين تُغلق النافذة، فيستمر الرصد.
//
// marsad.exe              تشغيل عادي
// marsad.exe --minimized  تشغيل مع ويندوز، دون إظهار النافذة
// marsad.exe --selftest   فحص آلي: تشغيل كل المكوّنات، التحقق من الخادم، ثم الإيقاف (للفحص في CI)

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use rand::RngCore;
use serde_json::{json, Value};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};
use tauri_plugin_autostart::ManagerExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const EXE: &str = if cfg!(windows) { ".exe" } else { "" };

// ---------- أماكن الملفات ----------

struct Layout {
    exe_dir: PathBuf,
    resources: PathBuf,
    home: PathBuf,
    config: PathBuf,
    portable: bool,
}

fn user_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn layout() -> Layout {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    let resources = exe_dir.join("resources");
    // النسخة المحمولة: ملف portable.txt بجانب البرنامج، وكل شيء داخل مجلدها
    let portable = exe_dir.join("portable.txt").exists();
    let home = if portable {
        exe_dir.clone()
    } else {
        std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| user_home().join(".config"))
            .join("Marsad")
    };
    let config = home.join("config");
    Layout { exe_dir, resources, home, config, portable }
}

fn writable(dir: &Path) -> bool {
    if fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".write-test");
    let ok = fs::write(&probe, b"x").is_ok();
    let _ = fs::remove_file(probe);
    ok
}

/// المكان الافتراضي لمجلد البيانات في أول تشغيل (يُغيَّر لاحقًا من الإدارة ← التخزين).
fn default_data_dir(l: &Layout) -> String {
    if l.portable {
        return "./data".into();
    }
    #[cfg(windows)]
    {
        let d = Path::new("D:\\Marsad");
        if Path::new("D:\\").exists() && writable(d) {
            return d.to_string_lossy().into_owned();
        }
    }
    user_home().join("Documents").join("Marsad").to_string_lossy().into_owned()
}

fn random_hex() -> String {
    let mut b = [0u8; 24];
    rand::thread_rng().fill_bytes(&mut b);
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn read_json(p: &Path) -> Option<Value> {
    fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(s.trim_start_matches('\u{feff}')).ok())
}

/// أسرار هذا الجهاز: كلمة مرور القاعدة ومفاتيح البحث والتشفير. تُولَّد مرة واحدة.
fn secrets(l: &Layout) -> Result<Value, String> {
    let p = l.config.join("secrets.json");
    if let Some(v) = read_json(&p) {
        return Ok(v);
    }
    let v = json!({"pg_password": random_hex(), "meili_key": random_hex(), "secret_key": random_hex()});
    fs::write(&p, serde_json::to_string_pretty(&v).unwrap()).map_err(|e| format!("تعذّر حفظ الإعدادات: {e}"))?;
    Ok(v)
}

fn first_run_files(l: &Layout) -> Result<bool, String> {
    fs::create_dir_all(&l.config).map_err(|e| format!("تعذّر إنشاء مجلد الإعدادات {}: {e}", l.config.display()))?;
    let storage = l.config.join("storage.json");
    if storage.exists() {
        return Ok(false);
    }
    let v = json!({"data_dir": default_data_dir(l), "backup_dir": "", "pending": null, "last_error": null, "history": []});
    fs::write(&storage, serde_json::to_string_pretty(&v).unwrap()).map_err(|e| e.to_string())?;
    Ok(true)
}

// ---------- تشغيل المكوّنات ----------

struct Running {
    children: Vec<Child>,
    pg_ctl: PathBuf,
    pg_data: PathBuf,
    url: String,
}

fn hidden(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: لا نوافذ سوداء
    cmd
}

/// تشغيل أمر دون التقاط مخرجاته (لا يعلق إن ورثها عملية أخرى)، ويعيد هل نجح.
fn quiet_status(cmd: &mut Command) -> bool {
    hidden(cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()))
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn free_port(preferred: u16) -> u16 {
    if TcpListener::bind(("127.0.0.1", preferred)).is_ok() {
        return preferred;
    }
    TcpListener::bind(("127.0.0.1", 0)).and_then(|l| l.local_addr()).map(|a| a.port()).unwrap_or(preferred)
}

fn log_file(dir: &Path, name: &str) -> Stdio {
    match OpenOptions::new().create(true).append(true).open(dir.join(name)) {
        Ok(f) => Stdio::from(f),
        Err(_) => Stdio::null(),
    }
}

fn run_quiet(cmd: &mut Command, what: &str) -> Result<String, String> {
    let out = hidden(cmd).output().map_err(|e| format!("تعذّر تشغيل {what}: {e}"))?;
    let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
    if out.status.success() {
        Ok(text)
    } else {
        Err(format!("{what} فشل:\n{}", text.trim()))
    }
}

fn wait_health(url: &str, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if let Ok(r) = ureq::get(&format!("{url}api/health")).timeout(Duration::from_secs(3)).call() {
            if r.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn start(l: &Layout, report: &dyn Fn(&str)) -> Result<Running, String> {
    let sec = secrets(l)?;
    let s = |k: &str| sec[k].as_str().unwrap_or_default().to_string();
    let mode = if l.portable { "portable" } else { "desktop" };
    let server = l.resources.join("marsad-server").join(format!("marsad-server{EXE}"));
    let base_env = |cmd: &mut Command| {
        cmd.env("MARSAD_HOME", &l.home).env("MARSAD_CONFIG_DIR", &l.config).env("MARSAD_MODE", mode);
    };

    // 1) طلب تغيير المكان (إن وُجد) وإنشاء المجلدات الناقصة
    report("تجهيز مجلدات البيانات…");
    let mut prep = Command::new(&server);
    prep.arg("prepare");
    base_env(&mut prep);
    let out = hidden(&mut prep).output().map_err(|e| format!("تعذّر تشغيل الخادم الداخلي: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    let data_root = stdout
        .lines()
        .find_map(|x| x.strip_prefix("MARSAD_DATA_ROOT=").map(|v| PathBuf::from(v.trim())))
        .ok_or("لم يُحدَّد مجلد البيانات")?;
    let logs = data_root.join("logs");
    let _ = fs::create_dir_all(&logs);

    // 2) قاعدة البيانات المضمَّنة
    report("تشغيل قاعدة البيانات…");
    let pgbin = l.resources.join("pgsql").join("bin");
    let pg_ctl = pgbin.join(format!("pg_ctl{EXE}"));
    let pg_data = data_root.join("db");
    if !pg_data.join("PG_VERSION").exists() {
        report("إنشاء قاعدة البيانات أول مرة…");
        let pwfile = l.config.join(".pw-init");
        fs::write(&pwfile, s("pg_password")).map_err(|e| e.to_string())?;
        let r = run_quiet(
            Command::new(pgbin.join(format!("initdb{EXE}")))
                .arg("-D").arg(&pg_data)
                .args(["-U", "marsad", "-A", "scram-sha-256", "-E", "UTF8", "--locale=C"])
                .arg(format!("--pwfile={}", pwfile.display())),
            "initdb",
        );
        let _ = fs::remove_file(&pwfile);
        r?;
    }
    // نسخة سابقة لم تُغلق بشكل صحيح؟ أوقفها أولًا
    if quiet_status(Command::new(&pg_ctl).arg("status").arg("-D").arg(&pg_data)) {
        quiet_status(Command::new(&pg_ctl).arg("stop").arg("-D").arg(&pg_data).args(["-m", "fast", "-w"]));
    }
    let pg_port = free_port(54329);
    // لا نلتقط مخرجات pg_ctl: خادم القاعدة يرث الأنبوب ويبقيه مفتوحًا فيعلق الانتظار.
    // سجله في postgres.log.
    let started = hidden(
        Command::new(&pg_ctl)
            .arg("start").arg("-D").arg(&pg_data)
            .arg("-o").arg(format!("-p {pg_port} -h 127.0.0.1"))
            .arg("-l").arg(logs.join("postgres.log"))
            .args(["-w", "-t", "90"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null()),
    )
    .status()
    .map_err(|e| format!("تعذّر تشغيل PostgreSQL: {e}"))?;
    if !started.success() {
        let tail = fs::read_to_string(logs.join("postgres.log")).unwrap_or_default();
        let last: Vec<&str> = tail.lines().rev().take(15).collect();
        return Err(format!("تعذّر تشغيل قاعدة البيانات:\n{}", last.into_iter().rev().collect::<Vec<_>>().join("\n")));
    }
    let created = hidden(
        Command::new(pgbin.join(format!("createdb{EXE}")))
            .args(["-h", "127.0.0.1", "-p", &pg_port.to_string(), "-U", "marsad", "marsad"])
            .env("PGPASSWORD", s("pg_password")),
    )
    .output();
    if let Ok(o) = &created {
        let err = String::from_utf8_lossy(&o.stderr);
        if !o.status.success() && !err.contains("already exists") {
            return Err(format!("تعذّر إنشاء القاعدة: {err}"));
        }
    }

    let mut children = Vec::new();

    // 3) محرك البحث
    report("تشغيل محرك البحث…");
    let meili_port = free_port(7701);
    let meili_url = format!("http://127.0.0.1:{meili_port}");
    let search_dir = data_root.join("search");
    let _ = fs::create_dir_all(&search_dir);
    let meili = l.resources.join(format!("meilisearch{EXE}"));
    if meili.exists() {
        let child = hidden(
            Command::new(&meili)
                .arg("--db-path").arg(search_dir.join("data.ms"))
                .arg("--dump-dir").arg(search_dir.join("dumps"))
                .arg("--http-addr").arg(format!("127.0.0.1:{meili_port}"))
                .arg("--master-key").arg(s("meili_key"))
                .args(["--no-analytics", "--env", "production"])
                .current_dir(&search_dir)
                .stdout(log_file(&logs, "meilisearch.log"))
                .stderr(log_file(&logs, "meilisearch.log")),
        )
        .spawn()
        .map_err(|e| format!("تعذّر تشغيل محرك البحث: {e}"))?;
        children.push(child);
    }

    // 4) الخادم الداخلي (الواجهة والعامل في عملية واحدة)
    report("تشغيل الخادم…");
    let port = free_port(8080);
    let url = format!("http://127.0.0.1:{port}/");
    let mut cmd = Command::new(&server);
    cmd.args(["serve", "--port", &port.to_string()]);
    base_env(&mut cmd);
    cmd.env(
        "MARSAD_DATABASE_URL",
        format!("postgresql+psycopg://marsad:{}@127.0.0.1:{pg_port}/marsad", s("pg_password")),
    )
    .env("MARSAD_STATIC_DIR", l.resources.join("web"))
    .env("MARSAD_MEILI_URL", &meili_url)
    .env("MARSAD_MEILI_KEY", s("meili_key"))
    .env("MARSAD_SECRET_KEY", s("secret_key"))
    .stdout(log_file(&logs, "server.log"))
    .stderr(log_file(&logs, "server.log"));
    children.push(hidden(&mut cmd).spawn().map_err(|e| format!("تعذّر تشغيل الخادم: {e}"))?);

    let running = Running { children, pg_ctl, pg_data, url: url.clone() };
    report("انتظار جاهزية البرنامج…");
    if !wait_health(&url, Duration::from_secs(120)) {
        stop(running);
        return Err(format!("لم يستجب الخادم. السجلات في:\n{}", logs.display()));
    }
    Ok(running)
}

fn stop(mut r: Running) {
    for c in r.children.iter_mut() {
        let _ = c.kill();
        let _ = c.wait();
    }
    quiet_status(Command::new(&r.pg_ctl).arg("stop").arg("-D").arg(&r.pg_data).args(["-m", "fast", "-w"]));
}

// ---------- حالة البرنامج والنافذة ----------

struct AppState {
    running: Mutex<Option<Running>>,
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn splash(app: &AppHandle, func: &str, text: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.eval(&format!("window.{func} && window.{func}({})", serde_json::to_string(text).unwrap()));
    }
}

fn boot(app: AppHandle) {
    let l = layout();
    let report = |t: &str| splash(&app, "marsadStatus", t);
    match start(&l, &report) {
        Ok(r) => {
            let url = r.url.clone();
            *app.state::<AppState>().running.lock().unwrap() = Some(r);
            if let Some(w) = app.get_webview_window("main") {
                if let Ok(u) = url.parse() {
                    let _ = w.navigate(u);
                }
            }
        }
        Err(e) => splash(&app, "marsadError", &e),
    }
}

fn shutdown(app: &AppHandle) {
    if let Some(r) = app.state::<AppState>().running.lock().unwrap().take() {
        stop(r);
    }
}

fn current_url(app: &AppHandle) -> Option<String> {
    app.state::<AppState>().running.lock().unwrap().as_ref().map(|r| r.url.clone())
}

fn open_browser(url: &str) {
    #[cfg(windows)]
    let _ = hidden(Command::new("cmd").args(["/C", "start", "", url])).spawn();
    #[cfg(not(windows))]
    let _ = Command::new("xdg-open").arg(url).spawn();
}

fn restart(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.navigate("tauri://localhost/index.html".parse().unwrap());
    }
    shutdown(&app);
    boot(app);
}

// ---------- أوامر تستدعيها الواجهة ----------

#[tauri::command]
async fn pick_folder(app: AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    app.dialog()
        .file()
        .set_title("اختر مجلد البيانات")
        .blocking_pick_folder()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
async fn restart_services(app: AppHandle) {
    std::thread::spawn(move || restart(app));
}

#[tauri::command]
fn desktop_info() -> Value {
    let l = layout();
    json!({"portable": l.portable, "config": l.config, "exe_dir": l.exe_dir})
}

// ---------- الفحص الآلي ----------

fn selftest() -> i32 {
    let l = layout();
    if let Err(e) = first_run_files(&l) {
        eprintln!("{e}");
        return 1;
    }
    match start(&l, &|t| println!("{t}")) {
        Ok(r) => {
            let body = ureq::get(&format!("{}api/setup", r.url)).call().ok().and_then(|x| x.into_string().ok());
            let page = ureq::get(&r.url).call().ok().and_then(|x| x.into_string().ok()).unwrap_or_default();
            stop(r);
            let ok = body.as_deref().map(|b| b.contains("needs_setup")).unwrap_or(false) && page.contains("مرصد التحقق");
            println!("{}", if ok { "SELFTEST OK" } else { "SELFTEST FAILED" });
            if ok { 0 } else { 1 }
        }
        Err(e) => {
            eprintln!("SELFTEST FAILED: {e}");
            1
        }
    }
}

// ---------- البداية ----------

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--selftest") {
        std::process::exit(selftest());
    }
    let minimized = args.iter().any(|a| a == "--minimized");

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .manage(AppState { running: Mutex::new(None) })
        .invoke_handler(tauri::generate_handler![pick_folder, restart_services, desktop_info])
        .setup(move |app| {
            let l = layout();
            let first = first_run_files(&l).unwrap_or(false);
            if first && !l.portable {
                let _ = app.autolaunch().enable(); // يبدأ مع ويندوز ليستمر الرصد
            }
            let handle = app.handle().clone();
            let open = MenuItem::with_id(&handle, "open", "فتح مرصد التحقق", true, None::<&str>)?;
            let browser = MenuItem::with_id(&handle, "browser", "فتح في المتصفح", true, None::<&str>)?;
            let auto = CheckMenuItem::with_id(
                &handle, "autostart", "التشغيل مع ويندوز", true,
                app.autolaunch().is_enabled().unwrap_or(false), None::<&str>,
            )?;
            let restart_i = MenuItem::with_id(&handle, "restart", "إعادة التشغيل", true, None::<&str>)?;
            let quit = MenuItem::with_id(&handle, "quit", "إيقاف البرنامج والخروج", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(&handle)?;
            let menu = Menu::with_items(&handle, &[&open, &browser, &auto, &sep, &restart_i, &quit])?;
            let auto_item = auto.clone();
            TrayIconBuilder::with_id("marsad")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("مرصد التحقق")
                .menu(&menu)
                .on_menu_event(move |app, ev| match ev.id().as_ref() {
                    "open" => show_main(app),
                    "browser" => {
                        if let Some(u) = current_url(app) {
                            open_browser(&u);
                        }
                    }
                    "autostart" => {
                        let al = app.autolaunch();
                        let on = al.is_enabled().unwrap_or(false);
                        let _ = if on { al.disable() } else { al.enable() };
                        let _ = auto_item.set_checked(!on);
                    }
                    "restart" => {
                        let a = app.clone();
                        std::thread::spawn(move || restart(a));
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            if minimized {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
            std::thread::spawn(move || boot(handle));
            Ok(())
        })
        .on_window_event(|w, e| {
            // إغلاق النافذة يخفيها فقط: يبقى الرصد يعمل، والخروج من أيقونة الساعة
            if let WindowEvent::CloseRequested { api, .. } = e {
                api.prevent_close();
                let _ = w.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("تعذّر تشغيل مرصد التحقق")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                shutdown(app);
            }
        });
}

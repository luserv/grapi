use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Port the Python sidecar listens on. Must match NEXT_PUBLIC_API_BASE's default.
const SIDECAR_PORT: u16 = 8765;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);

/// Holds the sidecar child so it can be killed on exit.
struct Sidecar(Mutex<Option<CommandChild>>);

/// Issues a real `GET /api/health` over TCP and checks for a 200 response.
fn health_ok(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let req = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = String::new();
    let _ = stream.read_to_string(&mut buf);
    buf.starts_with("HTTP/1.1 200")
}

/// Polls the health endpoint until it answers or the timeout elapses.
fn wait_for_health(port: u16, timeout: Duration) -> Result<(), String> {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if health_ok(port) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err(format!("sidecar did not answer /api/health within {timeout:?}"))
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar(Mutex::new(None)))
        .setup(|app| {
            let data_dir = app.path().app_data_dir()?;
            let downloads = data_dir.join("downloads");
            let sessions = data_dir.join("sessions");
            std::fs::create_dir_all(&downloads)?;
            std::fs::create_dir_all(&sessions)?;

            let (_rx, child) = app
                .shell()
                .sidecar("grapi-api")?
                .env("GRAPI_PORT", SIDECAR_PORT.to_string())
                .env("DOWNLOADS_DIR", downloads.to_string_lossy().to_string())
                .env("SESSIONS_DIR", sessions.to_string_lossy().to_string())
                .spawn()?;
            // Keep _rx alive is not required: dropping the receiver does not stop the child.
            *app.state::<Sidecar>().0.lock().unwrap() = Some(child);

            wait_for_health(SIDECAR_PORT, HEALTH_TIMEOUT)?;

            if let Some(window) = app.get_webview_window("main") {
                window.show()?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building grapi");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(child) = handle.state::<Sidecar>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}

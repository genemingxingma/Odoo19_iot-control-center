use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::post;
use axum::{Json, Router};
use base64::Engine as _;
use reqwest::Client;
use rumqttc::{AsyncClient, Event, EventLoop, Incoming, MqttOptions, QoS};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tokio::fs;
use tokio::io::AsyncReadExt;
use tokio::net::{TcpListener, TcpStream};
use tokio::process::Command;
use tracing::{error, info, warn};

#[derive(Clone)]
struct AppState {
    mqtt_client: AsyncClient,
    mqtt_topic_root: String,
}

#[derive(Clone)]
struct Forwarder {
    http: Client,
    odoo_base_url: String,
    token: String,
}

#[derive(Debug, Clone)]
struct Config {
    api_listen: String,
    th_tcp_listen: String,
    mqtt_host: String,
    mqtt_port: u16,
    mqtt_username: Option<String>,
    mqtt_password: Option<String>,
    mqtt_keepalive_sec: u64,
    mqtt_topic_root: String,
    odoo_base_url: String,
    middleware_token: String,
    openwrt_ssh_key_path: Option<String>,
}

impl Config {
    fn from_env() -> anyhow::Result<Self> {
        let api_listen = env_or("IOT_BRIDGE_API_LISTEN", "0.0.0.0:8099");
        let th_tcp_listen = env_or("IOT_BRIDGE_TH_TCP_LISTEN", "0.0.0.0:9910");
        let mqtt_host = env_or("IOT_BRIDGE_MQTT_HOST", "127.0.0.1");
        let mqtt_port = env_or("IOT_BRIDGE_MQTT_PORT", "1883")
            .parse::<u16>()
            .context("IOT_BRIDGE_MQTT_PORT must be a valid u16")?;
        let mqtt_username = env_opt("IOT_BRIDGE_MQTT_USERNAME");
        let mqtt_password = env_opt("IOT_BRIDGE_MQTT_PASSWORD");
        let mqtt_keepalive_sec = env_or("IOT_BRIDGE_MQTT_KEEPALIVE", "60")
            .parse::<u64>()
            .context("IOT_BRIDGE_MQTT_KEEPALIVE must be a valid integer")?;
        let mqtt_topic_root = env_or("IOT_BRIDGE_MQTT_TOPIC_ROOT", "iot/relay");
        let odoo_base_url = env_or("IOT_BRIDGE_ODOO_BASE_URL", "http://127.0.0.1:8069");
        let middleware_token = env_or("IOT_BRIDGE_TOKEN", "imytest-middleware-token");
        let openwrt_ssh_key_path = env_opt("IOT_BRIDGE_OPENWRT_SSH_KEY_PATH");

        Ok(Self {
            api_listen,
            th_tcp_listen,
            mqtt_host,
            mqtt_port,
            mqtt_username,
            mqtt_password,
            mqtt_keepalive_sec,
            mqtt_topic_root,
            odoo_base_url,
            middleware_token,
            openwrt_ssh_key_path,
        })
    }
}

#[derive(Debug, Deserialize)]
struct CommandRequest {
    command: String,
    #[serde(default)]
    payload: Option<Value>,
    #[serde(default)]
    retain: bool,
}

#[derive(Debug, Serialize)]
struct ApiResponse {
    ok: bool,
    message: String,
}

#[derive(Debug, Deserialize)]
struct OpenwrtBaseRequest {
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OpenwrtTemplateRequest {
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
    template: Value,
}

#[derive(Debug, Deserialize)]
struct OpenwrtUpgradeRequest {
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
    firmware_url: String,
    filename: String,
}

#[derive(Debug, Serialize)]
struct OpenwrtActionResponse {
    ok: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    facts: Option<Value>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let cfg = Config::from_env()?;
    info!(
        "starting iot_bridge api={} th_tcp={} mqtt={}:{} root={}",
        cfg.api_listen, cfg.th_tcp_listen, cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_topic_root
    );

    let mut mqtt_options = MqttOptions::new("iot_bridge", cfg.mqtt_host.clone(), cfg.mqtt_port);
    mqtt_options.set_keep_alive(Duration::from_secs(cfg.mqtt_keepalive_sec));
    if let Some(user) = cfg.mqtt_username.as_deref() {
        mqtt_options.set_credentials(user, cfg.mqtt_password.as_deref().unwrap_or(""));
    }

    let (mqtt_client, event_loop) = AsyncClient::new(mqtt_options, 2000);
    let state = AppState {
        mqtt_client: mqtt_client.clone(),
        mqtt_topic_root: cfg.mqtt_topic_root.clone(),
    };
    let forwarder = Arc::new(Forwarder {
        http: Client::builder().timeout(Duration::from_secs(8)).build()?,
        odoo_base_url: cfg.odoo_base_url.clone().trim_end_matches('/').to_string(),
        token: cfg.middleware_token.clone(),
    });

    let mqtt_topic_root = cfg.mqtt_topic_root.clone();
    let mqtt_forwarder = forwarder.clone();
    let mqtt_subscriber_client = mqtt_client.clone();
    tokio::spawn(async move {
        run_mqtt_loop(
            mqtt_subscriber_client,
            event_loop,
            mqtt_topic_root,
            mqtt_forwarder,
        )
        .await;
    });

    let th_tcp_listen = cfg.th_tcp_listen.clone();
    let th_forwarder = forwarder.clone();
    tokio::spawn(async move {
        if let Err(err) = run_th_tcp_server(&th_tcp_listen, th_forwarder).await {
            error!("th tcp server exited: {err:#}");
        }
    });

    let app = Router::new()
        .route("/healthz", post(healthz))
        .route("/v1/switch/:serial/command", post(switch_command))
        .route("/v1/openwrt/probe", post(openwrt_probe))
        .route("/v1/openwrt/apply_template", post(openwrt_apply_template))
        .route("/v1/openwrt/reboot", post(openwrt_reboot))
        .route("/v1/openwrt/upgrade", post(openwrt_upgrade))
        .with_state(state);

    let api_addr: SocketAddr = cfg
        .api_listen
        .parse()
        .with_context(|| format!("invalid IOT_BRIDGE_API_LISTEN: {}", cfg.api_listen))?;
    let listener = TcpListener::bind(api_addr).await?;
    info!("api listening on {}", api_addr);
    axum::serve(listener, app).await?;
    Ok(())
}

async fn healthz() -> Json<ApiResponse> {
    Json(ApiResponse {
        ok: true,
        message: "ok".to_string(),
    })
}

async fn switch_command(
    State(state): State<AppState>,
    Path(serial): Path<String>,
    Json(req): Json<CommandRequest>,
) -> Result<Json<ApiResponse>, (StatusCode, Json<ApiResponse>)> {
    let mut body = Map::<String, Value>::new();
    body.insert("command".to_string(), Value::String(req.command));
    if let Some(payload) = req.payload {
        match payload {
            Value::Object(obj) => {
                for (k, v) in obj {
                    body.insert(k, v);
                }
            }
            other => {
                body.insert("payload".to_string(), other);
            }
        }
    }
    let topic = format!("{}/{}/command", state.mqtt_topic_root, serial);
    let raw = serde_json::to_vec(&Value::Object(body)).map_err(internal_err)?;
    state
        .mqtt_client
        .publish(topic, QoS::AtLeastOnce, req.retain, raw)
        .await
        .map_err(internal_err)?;
    Ok(Json(ApiResponse {
        ok: true,
        message: "command published".to_string(),
    }))
}

async fn openwrt_probe(
    State(_state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtBaseRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    let board_raw = run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        "ubus call system board",
    )
    .await
    .map_err(openwrt_internal_err)?;
    let hostname = run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        "uci -q get system.@system[0].hostname || cat /proc/sys/kernel/hostname",
    )
    .await
    .map_err(openwrt_internal_err)?;
    let mut facts: Value = serde_json::from_str(&board_raw).map_err(openwrt_internal_err)?;
    if let Some(obj) = facts.as_object_mut() {
        obj.insert(
            "hostname".to_string(),
            Value::String(hostname.trim().to_string()),
        );
    }
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "probe completed".to_string(),
        facts: Some(facts),
    }))
}

async fn openwrt_apply_template(
    State(_state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtTemplateRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    let script = build_apply_template_script(&req.template).map_err(openwrt_bad_request)?;
    run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &format!("sh -s <<'IOT_OPENWRT_EOF'\n{}\nIOT_OPENWRT_EOF", script),
    )
    .await
    .map_err(openwrt_internal_err)?;
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "template applied".to_string(),
        facts: None,
    }))
}

async fn openwrt_reboot(
    State(_state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtBaseRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        "(nohup sh -c 'sleep 1; reboot' >/dev/null 2>&1 &) || reboot",
    )
    .await
    .map_err(openwrt_internal_err)?;
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "reboot requested".to_string(),
        facts: None,
    }))
}

async fn openwrt_upgrade(
    State(_state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtUpgradeRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    let filename = sanitize_filename(&req.filename);
    let temp_path = std::env::temp_dir().join(format!("iot_openwrt_{}", filename));
    let mut request_builder = Client::builder()
        .timeout(Duration::from_secs(120))
        .build()
        .map_err(openwrt_internal_err)?
        .get(&req.firmware_url);
    if !cfg.middleware_token.is_empty() {
        request_builder =
            request_builder.header("X-IoT-Middleware-Token", cfg.middleware_token.clone());
    }
    let bytes = request_builder
        .send()
        .await
        .map_err(openwrt_internal_err)?
        .error_for_status()
        .map_err(openwrt_internal_err)?
        .bytes()
        .await
        .map_err(openwrt_internal_err)?;
    fs::write(&temp_path, &bytes)
        .await
        .map_err(openwrt_internal_err)?;
    let remote_path = format!("/tmp/{}", filename);
    scp_to_remote(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &temp_path,
        &remote_path,
    )
    .await
    .map_err(openwrt_internal_err)?;
    run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &format!(
            "(nohup sh -c 'sleep 1; sysupgrade {}' >/dev/null 2>&1 &) || sysupgrade {}",
            shell_escape(&remote_path),
            shell_escape(&remote_path)
        ),
    )
    .await
    .map_err(openwrt_internal_err)?;
    let _ = fs::remove_file(&temp_path).await;
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "firmware uploaded and sysupgrade started".to_string(),
        facts: None,
    }))
}

async fn run_mqtt_loop(
    mqtt_client: AsyncClient,
    mut event_loop: EventLoop,
    topic_root: String,
    forwarder: Arc<Forwarder>,
) {
    let status_pattern = format!("{}/+/status", topic_root);
    let telemetry_pattern = format!("{}/+/telemetry", topic_root);

    loop {
        match event_loop.poll().await {
            Ok(Event::Incoming(Incoming::ConnAck(_))) => {
                info!("mqtt connected");
                if let Err(err) = mqtt_client
                    .subscribe(status_pattern.clone(), QoS::AtLeastOnce)
                    .await
                {
                    error!("mqtt subscribe status failed: {err}");
                }
                if let Err(err) = mqtt_client
                    .subscribe(telemetry_pattern.clone(), QoS::AtLeastOnce)
                    .await
                {
                    error!("mqtt subscribe telemetry failed: {err}");
                }
            }
            Ok(Event::Incoming(Incoming::Publish(p))) => {
                let payload = String::from_utf8_lossy(&p.payload).to_string();
                let body = serde_json::json!({
                    "topic": p.topic,
                    "payload": payload,
                });
                if let Err(err) = forwarder
                    .post_json("/iot_control_center/internal/mqtt_ingest", &body)
                    .await
                {
                    warn!("forward mqtt message failed: {err}");
                }
            }
            Ok(_) => {}
            Err(err) => {
                warn!("mqtt event loop error: {err}; retrying");
                tokio::time::sleep(Duration::from_millis(800)).await;
            }
        }
    }
}

async fn run_th_tcp_server(listen: &str, forwarder: Arc<Forwarder>) -> anyhow::Result<()> {
    let listener = TcpListener::bind(listen).await?;
    info!("th tcp listening on {}", listen);
    loop {
        let (socket, remote) = listener.accept().await?;
        let forwarder_clone = forwarder.clone();
        tokio::spawn(async move {
            if let Err(err) = handle_th_socket(socket, remote, forwarder_clone).await {
                warn!("th connection {} error: {err:#}", remote);
            }
        });
    }
}

async fn handle_th_socket(
    mut socket: TcpStream,
    remote: SocketAddr,
    forwarder: Arc<Forwarder>,
) -> anyhow::Result<()> {
    let mut buf = vec![0_u8; 4096];
    let mut frame_buf = Vec::<u8>::new();

    loop {
        let n = socket.read(&mut buf).await?;
        if n == 0 {
            break;
        }
        frame_buf.extend_from_slice(&buf[..n]);
        process_mixed_buffer(&mut frame_buf, remote, &forwarder).await?;
    }
    Ok(())
}

async fn process_mixed_buffer(
    buffer: &mut Vec<u8>,
    remote: SocketAddr,
    forwarder: &Forwarder,
) -> anyhow::Result<()> {
    loop {
        if buffer.is_empty() {
            return Ok(());
        }

        // JSON line frame.
        if buffer[0] == b'{' || buffer[0] == b'[' {
            if let Some(pos) = buffer.iter().position(|b| *b == b'\n') {
                let line = String::from_utf8_lossy(&buffer[..pos]).trim().to_string();
                buffer.drain(..=pos);
                if !line.is_empty() {
                    let body = serde_json::json!({
                        "payload_text": line,
                        "source_ip": remote.ip().to_string(),
                        "source_port": remote.port(),
                    });
                    let _ = forwarder
                        .post_json("/iot_control_center/internal/th_ingest_json", &body)
                        .await;
                }
                continue;
            }
            return Ok(());
        }

        // Binary frame: 0xFA 0xCE ... checksum
        let idx = buffer
            .windows(2)
            .position(|w| w == [0xFA, 0xCE])
            .unwrap_or(usize::MAX);
        if idx == usize::MAX {
            if buffer.len() > 1 {
                let keep = *buffer.last().unwrap_or(&0_u8);
                buffer.clear();
                buffer.push(keep);
            }
            return Ok(());
        }

        if idx > 0 {
            buffer.drain(..idx);
        }

        if buffer.len() < 9 {
            return Ok(());
        }
        let data_count = buffer[7] as usize;
        let frame_len = 9 + data_count * 2;
        if buffer.len() < frame_len {
            return Ok(());
        }
        let frame = buffer[..frame_len].to_vec();
        buffer.drain(..frame_len);

        let body = serde_json::json!({
            "frame_b64": base64::engine::general_purpose::STANDARD.encode(frame),
            "source_ip": remote.ip().to_string(),
            "source_port": remote.port(),
        });
        let _ = forwarder
            .post_json("/iot_control_center/internal/th_ingest_binary", &body)
            .await;
    }
}

impl Forwarder {
    async fn post_json(&self, path: &str, body: &Value) -> anyhow::Result<()> {
        let url = format!("{}{}", self.odoo_base_url, path);
        let mut headers = HeaderMap::new();
        if !self.token.is_empty() {
            headers.insert(
                "X-IoT-Middleware-Token",
                self.token
                    .parse()
                    .context("invalid middleware token header")?,
            );
        }
        let mut last_err = None;
        for _ in 0..2 {
            match self
                .http
                .post(&url)
                .headers(headers.clone())
                .json(body)
                .send()
                .await
            {
                Ok(resp) if resp.status().is_success() => return Ok(()),
                Ok(resp) => {
                    last_err = Some(anyhow::anyhow!("status {}", resp.status()));
                }
                Err(err) => {
                    last_err = Some(anyhow::anyhow!(err));
                }
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        Err(last_err.unwrap_or_else(|| anyhow::anyhow!("unknown post_json error")))
    }
}

fn internal_err<E: std::fmt::Display>(err: E) -> (StatusCode, Json<ApiResponse>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(ApiResponse {
            ok: false,
            message: err.to_string(),
        }),
    )
}

fn openwrt_internal_err<E: std::fmt::Display>(err: E) -> (StatusCode, Json<OpenwrtActionResponse>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(OpenwrtActionResponse {
            ok: false,
            message: err.to_string(),
            facts: None,
        }),
    )
}

fn openwrt_bad_request<E: std::fmt::Display>(err: E) -> (StatusCode, Json<OpenwrtActionResponse>) {
    (
        StatusCode::BAD_REQUEST,
        Json(OpenwrtActionResponse {
            ok: false,
            message: err.to_string(),
            facts: None,
        }),
    )
}

fn ensure_api_token(headers: &HeaderMap) -> Result<(), (StatusCode, Json<OpenwrtActionResponse>)> {
    let expected = env_or("IOT_BRIDGE_TOKEN", "imytest-middleware-token");
    let provided = headers
        .get("X-IoT-Middleware-Token")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .trim()
        .to_string();
    if expected.is_empty() || provided == expected {
        Ok(())
    } else {
        Err((
            StatusCode::UNAUTHORIZED,
            Json(OpenwrtActionResponse {
                ok: false,
                message: "unauthorized".to_string(),
                facts: None,
            }),
        ))
    }
}

fn resolve_key_path(
    request_key: Option<String>,
    default_key: Option<String>,
) -> anyhow::Result<String> {
    let chosen = request_key
        .and_then(|v| {
            let t = v.trim().to_string();
            if t.is_empty() {
                None
            } else {
                Some(t)
            }
        })
        .or(default_key)
        .ok_or_else(|| anyhow::anyhow!("OpenWrt SSH key path is empty"))?;
    Ok(chosen)
}

async fn run_ssh_command(
    host: &str,
    port: u16,
    username: &str,
    key_path: &str,
    command: &str,
) -> anyhow::Result<String> {
    let output = Command::new("ssh")
        .arg("-i")
        .arg(key_path)
        .arg("-o")
        .arg("BatchMode=yes")
        .arg("-o")
        .arg("StrictHostKeyChecking=no")
        .arg("-p")
        .arg(port.to_string())
        .arg(format!("{}@{}", username, host))
        .arg(command)
        .output()
        .await
        .context("failed to spawn ssh command")?;
    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "ssh command failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

async fn scp_to_remote(
    host: &str,
    port: u16,
    username: &str,
    key_path: &str,
    local_path: &PathBuf,
    remote_path: &str,
) -> anyhow::Result<()> {
    let output = Command::new("scp")
        .arg("-i")
        .arg(key_path)
        .arg("-o")
        .arg("BatchMode=yes")
        .arg("-o")
        .arg("StrictHostKeyChecking=no")
        .arg("-P")
        .arg(port.to_string())
        .arg(local_path)
        .arg(format!("{}@{}:{}", username, host, remote_path))
        .output()
        .await
        .context("failed to spawn scp command")?;
    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "scp failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

fn shell_escape(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

fn sanitize_filename(filename: &str) -> String {
    let trimmed = filename.trim();
    let fallback = "openwrt_firmware.bin";
    if trimmed.is_empty() {
        return fallback.to_string();
    }
    trimmed
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '.' || ch == '_' || ch == '-' {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn json_string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(|v| v.as_str())
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn build_apply_template_script(template: &Value) -> anyhow::Result<String> {
    let mut lines = vec![
        "set -e".to_string(),
        "find_device_by_band() {".to_string(),
        "  desired=\"$1\"".to_string(),
        "  for dev in $(uci -q show wireless | sed -n \"s/^wireless\\.\\([^.=]*\\)=wifi-device$/\\1/p\"); do".to_string(),
        "    band=$(uci -q get wireless.$dev.band || true)".to_string(),
        "    hwmode=$(uci -q get wireless.$dev.hwmode || true)".to_string(),
        "    case \"$desired\" in".to_string(),
        "      2g) [ \"$band\" = \"2g\" ] || [ \"$hwmode\" = \"11g\" ] || [ \"$hwmode\" = \"11ng\" ] && { echo \"$dev\"; return 0; } ;;".to_string(),
        "      5g) [ \"$band\" = \"5g\" ] || [ \"$hwmode\" = \"11a\" ] || [ \"$hwmode\" = \"11na\" ] || [ \"$hwmode\" = \"11ac\" ] && { echo \"$dev\"; return 0; } ;;".to_string(),
        "    esac".to_string(),
        "  done".to_string(),
        "  return 1".to_string(),
        "}".to_string(),
        "find_iface_for_device() {".to_string(),
        "  dev=\"$1\"".to_string(),
        "  for iface in $(uci -q show wireless | sed -n \"s/^wireless\\.\\([^.=]*\\)=wifi-iface$/\\1/p\"); do".to_string(),
        "    current_dev=$(uci -q get wireless.$iface.device || true)".to_string(),
        "    if [ \"$current_dev\" = \"$dev\" ]; then".to_string(),
        "      echo \"$iface\"".to_string(),
        "      return 0".to_string(),
        "    fi".to_string(),
        "  done".to_string(),
        "  return 1".to_string(),
        "}".to_string(),
    ];

    if let Some(country) = json_string(template, "country_code") {
        lines.push("for dev in $(uci -q show wireless | sed -n \"s/^wireless\\.\\([^.=]*\\)=wifi-device$/\\1/p\"); do".to_string());
        lines.push(format!(
            "  uci set wireless.$dev.country={}",
            shell_escape(&country)
        ));
        lines.push("done".to_string());
    }
    if let Some(hostname) = json_string(template, "system_hostname") {
        lines.push(format!(
            "uci set system.@system[0].hostname={}",
            shell_escape(&hostname)
        ));
    }
    if let Some(timezone_name) = json_string(template, "timezone_name") {
        lines.push(format!(
            "uci set system.@system[0].zonename={}",
            shell_escape(&timezone_name)
        ));
    }

    if let Some(obj) = template.get("wifi24").and_then(|v| v.as_object()) {
        append_wifi_apply_lines(&mut lines, "2g", obj)?;
    }
    if let Some(obj) = template.get("wifi5").and_then(|v| v.as_object()) {
        append_wifi_apply_lines(&mut lines, "5g", obj)?;
    }

    lines.push("uci commit wireless".to_string());
    lines.push("uci commit system || true".to_string());
    lines.push("wifi reload || wifi".to_string());
    Ok(lines.join("\n"))
}

fn append_wifi_apply_lines(
    lines: &mut Vec<String>,
    band: &str,
    obj: &serde_json::Map<String, Value>,
) -> anyhow::Result<()> {
    let prefix = if band == "2g" { "wifi24" } else { "wifi5" };
    let dev_var = format!("{}_dev", prefix);
    let iface_var = format!("{}_iface", prefix);
    lines.push(format!("{dev_var}=$(find_device_by_band {band} || true)"));
    lines.push(format!("if [ -n \"${{{dev_var}}}\" ]; then"));
    lines.push(format!(
        "  {iface_var}=$(find_iface_for_device ${{{dev_var}}} || true)"
    ));
    lines.push(format!("  if [ -n \"${{{iface_var}}}\" ]; then"));
    if let Some(enabled) = obj.get("enabled").and_then(|v| v.as_bool()) {
        lines.push(format!(
            "    uci set wireless.${{{iface_var}}}.disabled='{}'",
            if enabled { "0" } else { "1" }
        ));
    }
    if let Some(ssid) = obj
        .get("ssid")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        lines.push(format!(
            "    uci set wireless.${{{iface_var}}}.ssid={}",
            shell_escape(ssid)
        ));
    }
    if let Some(enc) = obj
        .get("encryption")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        lines.push(format!(
            "    uci set wireless.${{{iface_var}}}.encryption={}",
            shell_escape(enc)
        ));
    }
    if let Some(key) = obj
        .get("key")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        lines.push(format!(
            "    uci set wireless.${{{iface_var}}}.key={}",
            shell_escape(key)
        ));
    }
    if let Some(hidden) = obj.get("hidden").and_then(|v| v.as_bool()) {
        lines.push(format!(
            "    uci set wireless.${{{iface_var}}}.hidden='{}'",
            if hidden { "1" } else { "0" }
        ));
    }
    if let Some(channel) = obj
        .get("channel")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        lines.push(format!(
            "    uci set wireless.${{{dev_var}}}.channel={}",
            shell_escape(channel)
        ));
    }
    lines.push("  fi".to_string());
    lines.push("fi".to_string());
    Ok(())
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_opt(key: &str) -> Option<String> {
    std::env::var(key).ok().and_then(|v| {
        let vv = v.trim().to_string();
        if vv.is_empty() {
            None
        } else {
            Some(vv)
        }
    })
}

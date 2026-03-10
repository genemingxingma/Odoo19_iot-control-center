use std::net::SocketAddr;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::post;
use axum::{Json, Router};
use base64::Engine as _;
use sha2::{Digest, Sha256};
use reqwest::Client;
use rumqttc::{AsyncClient, Event, EventLoop, Incoming, MqttOptions, QoS};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::process::Command;
use tokio::sync::RwLock;
use tracing::{error, info, warn};

#[derive(Clone)]
struct AppState {
    mqtt_client: AsyncClient,
    mqtt_topic_root: String,
    openwrt_cache: Arc<RwLock<HashMap<String, CachedOpenwrtTelemetry>>>,
}

#[derive(Clone)]
struct Forwarder {
    http: Client,
    odoo_base_url: String,
    token: String,
}

#[derive(Debug, Deserialize)]
struct OpenwrtInventoryResponse {
    ok: bool,
    #[serde(default)]
    items: Vec<OpenwrtInventoryItem>,
    #[serde(default)]
    heartbeat_interval_sec: Option<u64>,
    #[serde(default)]
    full_probe_every: Option<u32>,
    #[serde(default)]
    offline_failure_threshold: Option<u32>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct OpenwrtInventoryItem {
    id: i64,
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
    auth_token: String,
}

#[derive(Debug, Serialize)]
struct OpenwrtHeartbeatPayload {
    id: i64,
    auth_token: String,
    ok: bool,
    mode: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    facts: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CachedOpenwrtTelemetry {
    #[serde(default)]
    facts: Option<Value>,
    #[serde(default)]
    clients: Vec<Value>,
    #[serde(default)]
    summary: Value,
}

#[derive(Debug, Deserialize)]
struct OpenwrtCacheBulkRequest {
    #[serde(default)]
    items: Vec<OpenwrtCacheItem>,
}

#[derive(Debug, Deserialize)]
struct OpenwrtRefreshBulkRequest {
    #[serde(default)]
    items: Vec<OpenwrtRefreshItem>,
}

#[derive(Debug, Deserialize)]
struct OpenwrtCacheItem {
    id: i64,
    host: String,
    port: u16,
    username: String,
}

#[derive(Debug, Deserialize)]
struct OpenwrtRefreshItem {
    id: i64,
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
    auth_token: String,
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
    #[serde(default)]
    firmware_url: Option<String>,
    #[serde(default)]
    firmware_id: Option<i64>,
    filename: String,
    #[serde(default)]
    checksum_sha256: Option<String>,
}

#[derive(Debug, Deserialize)]
struct OpenwrtLocateRequest {
    host: String,
    port: u16,
    username: String,
    #[serde(default)]
    key_path: Option<String>,
    #[serde(default = "default_true")]
    enable: bool,
    #[serde(default = "default_locate_duration_sec")]
    duration_sec: u32,
}

#[derive(Debug, Serialize)]
struct OpenwrtActionResponse {
    ok: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    facts: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    clients: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    summary: Option<Value>,
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
    let openwrt_cache = Arc::new(RwLock::new(HashMap::new()));
    let state = AppState {
        mqtt_client: mqtt_client.clone(),
        mqtt_topic_root: cfg.mqtt_topic_root.clone(),
        openwrt_cache: openwrt_cache.clone(),
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

    let openwrt_forwarder = forwarder.clone();
    let openwrt_key_path = cfg.openwrt_ssh_key_path.clone();
    let openwrt_cache_for_loop = openwrt_cache.clone();
    tokio::spawn(async move {
        run_openwrt_heartbeat_loop(openwrt_forwarder, openwrt_key_path, openwrt_cache_for_loop).await;
    });

    let app = Router::new()
        .route("/healthz", post(healthz))
        .route("/v1/switch/:serial/command", post(switch_command))
        .route("/v1/openwrt/probe", post(openwrt_probe))
        .route("/v1/openwrt/cache_bulk", post(openwrt_cache_bulk))
        .route("/v1/openwrt/refresh_bulk", post(openwrt_refresh_bulk))
        .route("/v1/openwrt/apply_template", post(openwrt_apply_template))
        .route("/v1/openwrt/locate", post(openwrt_locate))
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
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtBaseRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    let response = perform_openwrt_probe(&req.host, req.port, &req.username, &key_path)
        .await
        .map_err(openwrt_internal_err)?;
    cache_openwrt_probe(&state.openwrt_cache, &req.host, req.port, &req.username, &response).await;
    Ok(Json(response))
}

async fn openwrt_cache_bulk(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtCacheBulkRequest>,
) -> Result<Json<Value>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cache = state.openwrt_cache.read().await;
    let items: Vec<Value> = req
        .items
        .into_iter()
        .map(|item| {
            let key = openwrt_cache_key(&item.host, item.port, &item.username);
            let cached = cache.get(&key).cloned();
            serde_json::json!({
                "id": item.id,
                "facts": cached.as_ref().and_then(|v| v.facts.clone()),
                "summary": cached.as_ref().map(|v| v.summary.clone()).unwrap_or_else(|| serde_json::json!({})),
                "clients": cached.as_ref().map(|v| v.clients.clone()).unwrap_or_default(),
            })
        })
        .collect();
    Ok(Json(serde_json::json!({
        "ok": true,
        "items": items,
    })))
}

async fn openwrt_refresh_bulk(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtRefreshBulkRequest>,
) -> Result<Json<Value>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let mut refreshed = 0_u64;
    let mut failed = 0_u64;
    for item in req.items {
        let key_path = match resolve_key_path(item.key_path, cfg.openwrt_ssh_key_path.clone()) {
            Ok(v) => v,
            Err(err) => {
                failed += 1;
                let _ = state_for_heartbeat_writeback(
                    &state,
                    &OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: false,
                        mode: "probe".to_string(),
                        error: Some(err.to_string()),
                        facts: None,
                    },
                )
                .await;
                continue;
            }
        };
        match perform_openwrt_probe(&item.host, item.port, &item.username, &key_path).await {
            Ok(result) => {
                cache_openwrt_probe(&state.openwrt_cache, &item.host, item.port, &item.username, &result).await;
                let _ = state_for_heartbeat_writeback(
                    &state,
                    &OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: true,
                        mode: "probe".to_string(),
                        error: None,
                        facts: result.facts.clone(),
                    },
                )
                .await;
                refreshed += 1;
            }
            Err(err) => {
                let _ = state_for_heartbeat_writeback(
                    &state,
                    &OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: false,
                        mode: "probe".to_string(),
                        error: Some(err.to_string()),
                        facts: None,
                    },
                )
                .await;
                failed += 1;
            }
        }
    }
    Ok(Json(serde_json::json!({
        "ok": true,
        "refreshed": refreshed,
        "failed": failed,
    })))
}

async fn perform_openwrt_probe(
    host: &str,
    port: u16,
    username: &str,
    key_path: &str,
) -> anyhow::Result<OpenwrtActionResponse> {
    let board_raw = run_ssh_command(host, port, username, key_path, "ubus call system board").await?;
    let hostname = run_ssh_command(
        host,
        port,
        username,
        key_path,
        "uci -q get system.@system[0].hostname || cat /proc/sys/kernel/hostname",
    )
    .await?;
    let wireless_status_raw = run_ssh_command(host, port, username, key_path, "ubus call network.wireless status")
        .await
        .unwrap_or_else(|_| "{}".to_string());
    let hostapd_list_raw = run_ssh_command(
        host,
        port,
        username,
        key_path,
        "ubus list 'hostapd.*' 2>/dev/null | sed -n 's/^hostapd\\.//p'",
    )
    .await
    .unwrap_or_default();
    let ip_neigh_raw = run_ssh_command(host, port, username, key_path, "ip neigh show 2>/dev/null || true")
        .await
        .unwrap_or_default();
    let dhcp_leases_raw = run_ssh_command(host, port, username, key_path, "cat /tmp/dhcp.leases 2>/dev/null || true")
        .await
        .unwrap_or_default();
    let mut facts: Value = serde_json::from_str(&board_raw)?;
    if let Some(obj) = facts.as_object_mut() {
        obj.insert("hostname".to_string(), Value::String(hostname.trim().to_string()));
    }
    let iface_bands = parse_wireless_interface_bands(&wireless_status_raw);
    let ip_map = parse_ip_neigh(&ip_neigh_raw);
    let lease_map = parse_dhcp_leases(&dhcp_leases_raw);
    let hostapd_ifaces: Vec<String> = hostapd_list_raw
        .lines()
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .collect();
    let clients = collect_openwrt_clients(host, port, username, key_path, &hostapd_ifaces, &iface_bands, &ip_map, &lease_map).await?;
    let summary = summarize_clients(&clients);
    Ok(OpenwrtActionResponse {
        ok: true,
        message: "probe completed".to_string(),
        facts: Some(facts),
        clients: Some(Value::Array(clients)),
        summary: Some(summary),
    })
}

fn openwrt_cache_key(host: &str, port: u16, username: &str) -> String {
    format!("{}:{}:{}", host.trim(), port, username.trim())
}

async fn cache_openwrt_probe(
    cache: &Arc<RwLock<HashMap<String, CachedOpenwrtTelemetry>>>,
    host: &str,
    port: u16,
    username: &str,
    response: &OpenwrtActionResponse,
) {
    let key = openwrt_cache_key(host, port, username);
    let mut guard = cache.write().await;
    guard.insert(
        key,
        CachedOpenwrtTelemetry {
            facts: response.facts.clone(),
            clients: match response.clients.clone() {
                Some(Value::Array(items)) => items,
                _ => Vec::new(),
            },
            summary: response.summary.clone().unwrap_or_else(|| serde_json::json!({})),
        },
    );
}

async fn state_for_heartbeat_writeback(
    _state: &AppState,
    payload: &OpenwrtHeartbeatPayload,
) -> anyhow::Result<()> {
    let forwarder = Arc::new(Forwarder {
        http: Client::builder().timeout(Duration::from_secs(8)).build()?,
        odoo_base_url: env_or("IOT_BRIDGE_ODOO_BASE_URL", "http://127.0.0.1:8069")
            .trim_end_matches('/')
            .to_string(),
        token: env_or("IOT_BRIDGE_TOKEN", "imytest-middleware-token"),
    });
    forwarder
        .post_json(
            "/iot_control_center/internal/openwrt_heartbeat",
            &serde_json::to_value(payload)?,
        )
        .await
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
        clients: None,
        summary: None,
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
        "setsid sh -c 'sleep 1; reboot' </dev/null >/dev/null 2>&1 &",
    )
    .await
    .map_err(openwrt_internal_err)?;
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "reboot requested".to_string(),
        facts: None,
        clients: None,
        summary: None,
    }))
}

async fn openwrt_locate(
    State(_state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<OpenwrtLocateRequest>,
) -> Result<Json<OpenwrtActionResponse>, (StatusCode, Json<OpenwrtActionResponse>)> {
    ensure_api_token(&headers)?;
    let cfg = Config::from_env().map_err(openwrt_internal_err)?;
    let key_path =
        resolve_key_path(req.key_path, cfg.openwrt_ssh_key_path).map_err(openwrt_bad_request)?;
    let script =
        build_locate_script(req.enable, req.duration_sec.max(30)).map_err(openwrt_bad_request)?;
    let output = run_ssh_command(
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
        message: output.trim().to_string(),
        facts: None,
        clients: None,
        summary: None,
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
    let firmware_url = if let Some(firmware_id) = req.firmware_id {
        format!(
            "{}/iot_control_center/openwrt/firmware/{}/download",
            cfg.odoo_base_url.trim_end_matches('/'),
            firmware_id
        )
    } else {
        req.firmware_url
            .clone()
            .filter(|value| !value.trim().is_empty())
            .ok_or_else(|| openwrt_bad_request("firmware_url or firmware_id is required"))?
    };
    let mut request_builder = Client::builder()
        .timeout(Duration::from_secs(120))
        .build()
        .map_err(openwrt_internal_err)?
        .get(&firmware_url);
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
    if let Some(expected_hash) = req
        .checksum_sha256
        .as_ref()
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| !value.is_empty())
    {
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let actual_hash = format!("{:x}", hasher.finalize());
        if actual_hash != expected_hash {
            return Err(openwrt_internal_err(format!(
                "firmware checksum mismatch: expected {}, got {}",
                expected_hash, actual_hash
            )));
        }
    }
    let remote_path = format!("/tmp/{}", filename);
    upload_to_remote(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &bytes,
        &remote_path,
    )
    .await
    .map_err(openwrt_internal_err)?;
    run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &format!("sysupgrade -T {}", shell_escape(&remote_path)),
    )
    .await
    .map_err(openwrt_internal_err)?;
    run_ssh_command(
        &req.host,
        req.port,
        &req.username,
        &key_path,
        &format!(
            "setsid sh -c 'sleep 1; /sbin/sysupgrade {}' </dev/null >/tmp/codex_sysupgrade.log 2>&1 &",
            shell_escape(&remote_path)
        ),
    )
    .await
    .map_err(openwrt_internal_err)?;
    Ok(Json(OpenwrtActionResponse {
        ok: true,
        message: "firmware uploaded and sysupgrade started".to_string(),
        facts: None,
        clients: None,
        summary: None,
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

async fn run_openwrt_heartbeat_loop(
    forwarder: Arc<Forwarder>,
    default_key_path: Option<String>,
    cache: Arc<RwLock<HashMap<String, CachedOpenwrtTelemetry>>>,
) {
    let mut probe_counters: HashMap<i64, u32> = HashMap::new();
    let mut sleep_sec = 300_u64;
    loop {
        let inventory = match forwarder
            .post_json_read::<OpenwrtInventoryResponse>(
                "/iot_control_center/internal/openwrt_inventory",
                &serde_json::json!({}),
            )
            .await
        {
            Ok(data) if data.ok => data,
            Ok(_) => {
                warn!("openwrt heartbeat inventory returned ok=false");
                tokio::time::sleep(Duration::from_secs(sleep_sec)).await;
                continue;
            }
            Err(err) => {
                warn!("openwrt heartbeat inventory failed: {err}");
                tokio::time::sleep(Duration::from_secs(sleep_sec)).await;
                continue;
            }
        };
        sleep_sec = inventory.heartbeat_interval_sec.unwrap_or(300).max(60);
        let full_probe_every = inventory.full_probe_every.unwrap_or(6).max(1);
        let _offline_failure_threshold = inventory.offline_failure_threshold.unwrap_or(2).max(1);

        for item in inventory.items {
            let counter = probe_counters.entry(item.id).or_insert(0);
            *counter = counter.saturating_add(1);
            let full_probe = *counter == 1 || (*counter % full_probe_every == 0);
            let key_path = match resolve_key_path(item.key_path.clone(), default_key_path.clone()) {
                Ok(path) => path,
                Err(err) => {
                    let _ = forwarder
                        .post_json(
                            "/iot_control_center/internal/openwrt_heartbeat",
                            &serde_json::json!(OpenwrtHeartbeatPayload {
                                id: item.id,
                                auth_token: item.auth_token.clone(),
                                ok: false,
                                mode: if full_probe { "probe".to_string() } else { "heartbeat".to_string() },
                                error: Some(err.to_string()),
                                facts: None,
                            }),
                        )
                        .await;
                    continue;
                }
            };

            let payload = if full_probe {
                match perform_openwrt_probe(&item.host, item.port, &item.username, &key_path).await {
                    Ok(result) => {
                        cache_openwrt_probe(&cache, &item.host, item.port, &item.username, &result).await;
                        OpenwrtHeartbeatPayload {
                            id: item.id,
                            auth_token: item.auth_token.clone(),
                            ok: true,
                            mode: "probe".to_string(),
                            error: None,
                            facts: result.facts,
                        }
                    }
                    Err(err) => OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: false,
                        mode: "probe".to_string(),
                        error: Some(err.to_string()),
                        facts: None,
                    },
                }
            } else {
                match run_ssh_command(&item.host, item.port, &item.username, &key_path, "true").await {
                    Ok(_) => OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: true,
                        mode: "heartbeat".to_string(),
                        error: None,
                        facts: None,
                    },
                    Err(err) => OpenwrtHeartbeatPayload {
                        id: item.id,
                        auth_token: item.auth_token.clone(),
                        ok: false,
                        mode: "heartbeat".to_string(),
                        error: Some(err.to_string()),
                        facts: None,
                    },
                }
            };

            if let Err(err) = forwarder
                .post_json(
                    "/iot_control_center/internal/openwrt_heartbeat",
                    &serde_json::to_value(payload).unwrap_or_else(|_| serde_json::json!({})),
                )
                .await
            {
                warn!("openwrt heartbeat writeback failed for ap {}: {err}", item.id);
            }
        }

        tokio::time::sleep(Duration::from_secs(sleep_sec)).await;
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

    async fn post_json_read<T>(&self, path: &str, body: &Value) -> anyhow::Result<T>
    where
        T: serde::de::DeserializeOwned,
    {
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
        let resp = self
            .http
            .post(&url)
            .headers(headers)
            .json(body)
            .send()
            .await
            .context("post_json_read request failed")?
            .error_for_status()
            .context("post_json_read status failed")?;
        resp.json::<T>().await.context("post_json_read decode failed")
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
            clients: None,
            summary: None,
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
            clients: None,
            summary: None,
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
                clients: None,
                summary: None,
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

async fn upload_to_remote(
    host: &str,
    port: u16,
    username: &str,
    key_path: &str,
    content: &[u8],
    remote_path: &str,
) -> anyhow::Result<()> {
    let mut child = Command::new("ssh")
        .arg("-i")
        .arg(key_path)
        .arg("-o")
        .arg("BatchMode=yes")
        .arg("-o")
        .arg("StrictHostKeyChecking=no")
        .arg("-p")
        .arg(port.to_string())
        .arg(format!("{}@{}", username, host))
        .arg(format!(
            "cat > {} && chmod 600 {}",
            shell_escape(remote_path),
            shell_escape(remote_path)
        ))
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .context("failed to spawn ssh upload command")?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(content)
            .await
            .context("failed to stream firmware bytes to ssh")?;
        stdin.shutdown().await.ok();
    }
    let output = child
        .wait_with_output()
        .await
        .context("failed to wait for ssh upload command")?;
    if !output.status.success() {
        return Err(anyhow::anyhow!(
            "firmware upload failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

fn shell_escape(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

fn parse_wireless_interface_bands(raw: &str) -> HashMap<String, String> {
    let mut bands = HashMap::new();
    let parsed: Value = serde_json::from_str(raw).unwrap_or(Value::Null);
    let root = match parsed.as_object() {
        Some(obj) => obj,
        None => return bands,
    };
    for radio in root.values() {
        let band = radio
            .get("config")
            .and_then(|v| v.get("band"))
            .and_then(Value::as_str)
            .map(normalize_band_label)
            .or_else(|| {
                radio.get("config")
                    .and_then(|v| v.get("channel"))
                    .and_then(Value::as_u64)
                    .map(|channel| if channel <= 14 { "2.4g".to_string() } else { "5g".to_string() })
            })
            .unwrap_or_else(|| "other".to_string());
        if let Some(interfaces) = radio.get("interfaces").and_then(Value::as_array) {
            for iface in interfaces {
                if let Some(name) = iface.get("ifname").and_then(Value::as_str) {
                    bands.insert(name.trim().to_string(), band.clone());
                }
                if let Some(name) = iface.get("section").and_then(Value::as_str) {
                    bands.insert(name.trim().to_string(), band.clone());
                }
                if let Some(name) = iface
                    .get("config")
                    .and_then(|v| v.get("ifname"))
                    .and_then(Value::as_str)
                {
                    bands.insert(name.trim().to_string(), band.clone());
                }
            }
        }
    }
    bands
}

fn parse_ip_neigh(raw: &str) -> HashMap<String, String> {
    let mut ip_map = HashMap::new();
    for line in raw.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 5 {
            continue;
        }
        let ip = parts[0].trim().to_string();
        let mut mac = None;
        for window in parts.windows(2) {
            if window[0] == "lladdr" {
                mac = Some(window[1].trim().to_ascii_uppercase());
                break;
            }
        }
        if let Some(mac_value) = mac {
            ip_map.insert(mac_value, ip);
        }
    }
    ip_map
}

fn parse_dhcp_leases(raw: &str) -> HashMap<String, (String, String)> {
    let mut leases = HashMap::new();
    for line in raw.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 4 {
            continue;
        }
        let mac = parts[1].trim().to_ascii_uppercase();
        let ip = parts[2].trim().to_string();
        let hostname = if parts[3] == "*" {
            String::new()
        } else {
            parts[3].trim().to_string()
        };
        leases.insert(mac, (ip, hostname));
    }
    leases
}

fn normalize_band_label(raw: &str) -> String {
    match raw.trim().to_ascii_lowercase().as_str() {
        "2g" | "2.4g" | "2ghz" => "2.4g".to_string(),
        "5g" | "5ghz" => "5g".to_string(),
        _ => "other".to_string(),
    }
}

fn read_nested_u64(value: &Value, parent_key: &str, child_key: &str) -> u64 {
    value
        .get(parent_key)
        .and_then(Value::as_object)
        .and_then(|obj| obj.get(child_key))
        .and_then(Value::as_u64)
        .unwrap_or(0)
}

fn read_nested_rate_mbps(value: &Value, parent_key: &str, child_key: &str) -> f64 {
    let raw = value
        .get(parent_key)
        .and_then(Value::as_object)
        .and_then(|obj| obj.get(child_key))
        .and_then(Value::as_f64)
        .unwrap_or(0.0);
    if raw > 1000.0 {
        raw / 1_000_000.0
    } else {
        raw
    }
}

fn safe_hostapd_iface_name(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-')
    {
        Some(trimmed.to_string())
    } else {
        None
    }
}

async fn collect_openwrt_clients(
    host: &str,
    port: u16,
    username: &str,
    key_path: &str,
    hostapd_ifaces: &[String],
    iface_bands: &HashMap<String, String>,
    ip_map: &HashMap<String, String>,
    lease_map: &HashMap<String, (String, String)>,
) -> anyhow::Result<Vec<Value>> {
    let mut clients = Vec::new();
    for iface in hostapd_ifaces {
        let Some(iface_name) = safe_hostapd_iface_name(iface) else {
            warn!("openwrt client probe skipped unsafe iface name {}", iface);
            continue;
        };
        let raw = match run_ssh_command(
            host,
            port,
            username,
            key_path,
            &format!("ubus call hostapd.{} get_clients", iface_name),
        )
        .await
        {
            Ok(output) => output,
            Err(err) => {
                warn!("openwrt client probe skipped iface {}: {err}", iface);
                continue;
            }
        };
        let payload: Value = serde_json::from_str(&raw)?;
        let stations = payload
            .get("clients")
            .and_then(Value::as_object)
            .or_else(|| payload.as_object());
        let Some(stations) = stations else {
            continue;
        };
        let band = iface_bands
            .get(iface)
            .cloned()
            .unwrap_or_else(|| "other".to_string());
        for (mac, station) in stations {
            let mac_upper = mac.trim().to_ascii_uppercase();
            let lease = lease_map.get(&mac_upper);
            let ip = ip_map
                .get(&mac_upper)
                .cloned()
                .or_else(|| lease.map(|item| item.0.clone()))
                .unwrap_or_default();
            let hostname = lease
                .map(|item| item.1.clone())
                .filter(|value| !value.is_empty())
                .unwrap_or_default();
            let client_upload_bytes = read_nested_u64(station, "bytes", "rx");
            let client_download_bytes = read_nested_u64(station, "bytes", "tx");
            let signal_dbm = station
                .get("signal")
                .and_then(Value::as_i64)
                .map(|v| v as i32)
                .unwrap_or(0);
            let connected_seconds = station
                .get("connected_time")
                .and_then(Value::as_u64)
                .map(|v| v as u32)
                .unwrap_or(0);
            clients.push(serde_json::json!({
                "iface": iface,
                "band": band,
                "mac": mac_upper,
                "ip": ip,
                "hostname": hostname,
                "signal_dbm": signal_dbm,
                "upload_rate_mbps": read_nested_rate_mbps(station, "rate", "rx"),
                "download_rate_mbps": read_nested_rate_mbps(station, "rate", "tx"),
                "upload_bytes_total": client_upload_bytes,
                "download_bytes_total": client_download_bytes,
                "connected_seconds": connected_seconds
            }));
        }
    }
    clients.sort_by(|left, right| {
        left.get("band")
            .and_then(Value::as_str)
            .unwrap_or("")
            .cmp(right.get("band").and_then(Value::as_str).unwrap_or(""))
            .then_with(|| {
                left.get("ip")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .cmp(right.get("ip").and_then(Value::as_str).unwrap_or(""))
            })
            .then_with(|| {
                left.get("mac")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .cmp(right.get("mac").and_then(Value::as_str).unwrap_or(""))
            })
    });
    Ok(clients)
}

fn summarize_clients(clients: &[Value]) -> Value {
    let mut count_24 = 0_u64;
    let mut count_5 = 0_u64;
    let mut upload_rate = 0.0_f64;
    let mut download_rate = 0.0_f64;
    let mut upload_bytes = 0.0_f64;
    let mut download_bytes = 0.0_f64;
    for client in clients {
        match client.get("band").and_then(Value::as_str).unwrap_or("other") {
            "2.4g" => count_24 += 1,
            "5g" => count_5 += 1,
            _ => {}
        }
        upload_rate += client
            .get("upload_rate_mbps")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        download_rate += client
            .get("download_rate_mbps")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        upload_bytes += client
            .get("upload_bytes_total")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        download_bytes += client
            .get("download_bytes_total")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
    }
    serde_json::json!({
        "client_count_total": clients.len(),
        "client_count_24g": count_24,
        "client_count_5g": count_5,
        "upload_rate_mbps": upload_rate,
        "download_rate_mbps": download_rate,
        "upload_bytes_total": upload_bytes,
        "download_bytes_total": download_bytes
    })
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

fn default_true() -> bool {
    true
}

fn default_locate_duration_sec() -> u32 {
    300
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
        "clear_wifi_ifaces() {".to_string(),
        "  for iface in $(uci -q show wireless | sed -n \"s/^wireless\\.\\([^.=]*\\)=wifi-iface$/\\1/p\"); do".to_string(),
        "    uci -q delete wireless.$iface || true".to_string(),
        "  done".to_string(),
        "}".to_string(),
    ];

    lines.push("clear_wifi_ifaces".to_string());

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

fn build_locate_script(enable: bool, duration_sec: u32) -> anyhow::Result<String> {
    if !enable {
        return Ok(
            r#"#!/bin/sh
STATE_DIR=/tmp/iot_cc_locate
PID_FILE="$STATE_DIR/blink.pid"
STATE_FILE="$STATE_DIR/state"
restore_leds() {
  [ -f "$STATE_FILE" ] || return 0
  while IFS='|' read -r led_name trigger brightness; do
    led="/sys/class/leds/$led_name"
    [ -d "$led" ] || continue
    [ -n "$trigger" ] && echo "$trigger" > "$led/trigger" 2>/dev/null || true
    [ -n "$brightness" ] && echo "$brightness" > "$led/brightness" 2>/dev/null || true
  done < "$STATE_FILE"
}
if [ -f "$PID_FILE" ]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
restore_leds
rm -f "$STATE_FILE" "$STATE_DIR/restore.sh"
echo stopped
"#
            .to_string(),
        );
    }

    Ok(format!(
        r#"#!/bin/sh
STATE_DIR=/tmp/iot_cc_locate
PID_FILE="$STATE_DIR/blink.pid"
STATE_FILE="$STATE_DIR/state"
RESTORE_SCRIPT="$STATE_DIR/restore.sh"
mkdir -p "$STATE_DIR"
restore_leds() {{
  [ -f "$STATE_FILE" ] || return 0
  while IFS='|' read -r led_name trigger brightness; do
    led="/sys/class/leds/$led_name"
    [ -d "$led" ] || continue
    [ -n "$trigger" ] && echo "$trigger" > "$led/trigger" 2>/dev/null || true
    [ -n "$brightness" ] && echo "$brightness" > "$led/brightness" 2>/dev/null || true
  done < "$STATE_FILE"
}}
if [ -f "$PID_FILE" ]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
restore_leds
: > "$STATE_FILE"
count=0
for led in /sys/class/leds/*; do
  [ -d "$led" ] || continue
  led_name="$(basename "$led")"
  trigger="$(sed -n 's/.*\[\([^]]*\)\].*/\1/p' "$led/trigger" 2>/dev/null)"
  brightness="$(cat "$led/brightness" 2>/dev/null || echo 0)"
  echo "$led_name|$trigger|$brightness" >> "$STATE_FILE"
  count=$((count + 1))
done
[ "$count" -gt 0 ] || {{ echo no-leds; exit 4; }}
cat > "$RESTORE_SCRIPT" <<'EOF'
#!/bin/sh
STATE_DIR=/tmp/iot_cc_locate
PID_FILE="$STATE_DIR/blink.pid"
STATE_FILE="$STATE_DIR/state"
if [ -f "$PID_FILE" ]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
if [ -f "$STATE_FILE" ]; then
  while IFS='|' read -r led_name trigger brightness; do
    led="/sys/class/leds/$led_name"
    [ -d "$led" ] || continue
    [ -n "$trigger" ] && echo "$trigger" > "$led/trigger" 2>/dev/null || true
    [ -n "$brightness" ] && echo "$brightness" > "$led/brightness" 2>/dev/null || true
  done < "$STATE_FILE"
fi
rm -f "$STATE_FILE" "$0"
EOF
chmod +x "$RESTORE_SCRIPT"
(
  while true; do
    for led in /sys/class/leds/*; do
      [ -d "$led" ] || continue
      max="$(cat "$led/max_brightness" 2>/dev/null || echo 1)"
      echo none > "$led/trigger" 2>/dev/null || true
      echo "$max" > "$led/brightness" 2>/dev/null || true
    done
    sleep 0.2
    for led in /sys/class/leds/*; do
      [ -d "$led" ] || continue
      echo none > "$led/trigger" 2>/dev/null || true
      echo 0 > "$led/brightness" 2>/dev/null || true
    done
    sleep 0.2
  done
) >/dev/null 2>&1 &
echo $! > "$PID_FILE"
(nohup sh -c "sleep {duration}; '$RESTORE_SCRIPT'" >/dev/null 2>&1 &)
echo started:{duration}s
"#,
        duration = duration_sec
    ))
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
    let entries = obj
        .get("entries")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if entries.is_empty() {
        append_wifi_entry_lines(lines, &iface_var, obj)?;
    } else {
        for entry in entries {
            if let Some(entry_obj) = entry.as_object() {
                lines.push(format!("  {iface_var}=$(uci add wireless wifi-iface)"));
                lines.push(format!("  uci set wireless.${{{iface_var}}}.device=${{{dev_var}}}"));
                lines.push("  uci set wireless.${wifi_iface}.mode='ap'".replace("${wifi_iface}", &format!("${{{iface_var}}}")));
                lines.push("  uci set wireless.${wifi_iface}.network='lan'".replace("${wifi_iface}", &format!("${{{iface_var}}}")));
                append_wifi_entry_lines(lines, &iface_var, entry_obj)?;
            }
        }
    }
    if let Some(channel) = obj
        .get("channel")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        lines.push(format!(
            "  uci set wireless.${{{dev_var}}}.channel={}",
            shell_escape(channel)
        ));
    }
    lines.push("fi".to_string());
    Ok(())
}

fn append_wifi_entry_lines(
    lines: &mut Vec<String>,
    iface_var: &str,
    obj: &serde_json::Map<String, Value>,
) -> anyhow::Result<()> {
    lines.push(format!("  {iface_var}=$(uci -q get wireless.${{{iface_var}}} 2>/dev/null || echo ${{{iface_var}}})"));
    if let Some(enabled) = obj.get("enabled").and_then(|v| v.as_bool()) {
        lines.push(format!(
            "  uci set wireless.${{{iface_var}}}.disabled='{}'",
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
            "  uci set wireless.${{{iface_var}}}.ssid={}",
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
            "  uci set wireless.${{{iface_var}}}.encryption={}",
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
            "  uci set wireless.${{{iface_var}}}.key={}",
            shell_escape(key)
        ));
    } else if obj
        .get("encryption")
        .and_then(|v| v.as_str())
        .map(|s| s.trim())
        == Some("none")
    {
        lines.push(format!("  uci -q delete wireless.${{{iface_var}}}.key || true"));
    }
    if let Some(hidden) = obj.get("hidden").and_then(|v| v.as_bool()) {
        lines.push(format!(
            "  uci set wireless.${{{iface_var}}}.hidden='{}'",
            if hidden { "1" } else { "0" }
        ));
    }
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

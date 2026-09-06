//! One durable file per receipt; reading is non-destructive and only ACK deletes.
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::fs;
use tokio::io::AsyncWriteExt;
use tokio::sync::Mutex;

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueuedPost {
    pub id: String,
    pub path: String,
    pub body: Value,
}

#[derive(Clone)]
pub struct DurableQueue {
    root: PathBuf,
    scan: std::sync::Arc<Mutex<Option<fs::ReadDir>>>,
}

impl DurableQueue {
    pub async fn new(root: PathBuf) -> Result<Self> {
        // V1 JSONL is deliberately not consumed: its messages have no stable
        // receipt identity or trustworthy receipt time. Archive it at cutover.
        anyhow::ensure!(
            !root.is_file(),
            "V2 requires an outbox directory, not a V1 JSONL file"
        );
        fs::create_dir_all(root.join("pending")).await?;
        fs::create_dir_all(root.join("rejected")).await?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            for dir in [&root, &root.join("pending"), &root.join("rejected")] {
                fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700)).await?;
            }
        }
        Ok(Self {
            root,
            scan: Default::default(),
        })
    }

    pub fn prepare(path: &str, body: &Value) -> Result<QueuedPost> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?;
        let entropy = format!(
            "{}:{}:{}",
            now.as_nanos(),
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        let id = format!("{:x}", Sha256::digest(entropy.as_bytes()));
        let mut body = body.clone();
        let object = body
            .as_object_mut()
            .context("event body must be an object")?;
        object.insert("protocol_version".into(), 2.into());
        object.insert("event_id".into(), id.clone().into());
        object.insert("received_at_ms".into(), (now.as_millis() as u64).into());
        Ok(QueuedPost {
            id,
            path: path.into(),
            body,
        })
    }

    #[cfg(test)]
    pub async fn enqueue(&self, path: &str, body: &Value) -> Result<String> {
        let item = Self::prepare(path, body)?;
        self.persist(&item).await?;
        Ok(item.id)
    }

    pub async fn persist(&self, item: &QueuedPost) -> Result<()> {
        let id = &item.id;
        let bytes = serde_json::to_vec(item)?;
        anyhow::ensure!(bytes.len() <= 2 * 1024 * 1024, "event too large");
        let destination = self.pending(id)?;
        if destination.exists() {
            anyhow::ensure!(
                fs::read(&destination).await? == bytes,
                "event identity collision"
            );
            return self.sync_directory("pending").await;
        }
        let temp = self.root.join("pending").join(format!("{id}.tmp"));
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        options.mode(0o600);
        let mut file = options.open(&temp).await?;
        file.write_all(&bytes).await?;
        // Tokio's sync_all waits for pending writes but can retain their error
        // for a later flush. Check it before treating an empty file as durable.
        file.flush().await?;
        file.sync_all().await?;
        drop(file);
        fs::rename(temp, self.pending(&id)?).await?;
        self.sync_directory("pending").await?;
        Ok(())
    }

    fn pending(&self, id: &str) -> Result<PathBuf> {
        anyhow::ensure!(
            id.len() == 64 && id.bytes().all(|c| c.is_ascii_hexdigit()),
            "invalid event identity"
        );
        Ok(self.root.join("pending").join(format!("{id}.json")))
    }

    async fn sync_directory(&self, name: &str) -> Result<()> {
        #[cfg(unix)]
        fs::File::open(self.root.join(name))
            .await?
            .sync_all()
            .await?;
        #[cfg(not(unix))]
        let _ = name;
        Ok(())
    }

    pub async fn batch(&self, limit: usize) -> Result<Vec<QueuedPost>> {
        // Continue the directory scan between batches so a retrying prefix
        // cannot starve other gateways. A restart safely begins a new scan.
        let mut scan = self.scan.lock().await;
        if scan.is_none() {
            *scan = Some(fs::read_dir(self.root.join("pending")).await?);
        }
        let mut result = Vec::new();
        while result.len() < limit {
            let Some(entry) = scan.as_mut().unwrap().next_entry().await? else {
                *scan = None;
                break;
            };
            if entry.path().extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let bytes = match fs::read(entry.path()).await {
                Ok(bytes) => bytes,
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
                Err(err) => {
                    *scan = None;
                    return Err(err.into());
                }
            };
            match serde_json::from_slice::<QueuedPost>(&bytes) {
                Ok(item)
                    if self
                        .pending(&item.id)
                        .is_ok_and(|path| path == entry.path())
                        && item.body.get("event_id").and_then(Value::as_str) == Some(&item.id)
                        && item.body.get("protocol_version").and_then(Value::as_u64) == Some(2) =>
                {
                    result.push(item)
                }
                _ => {
                    // Preserve corrupt payloads for diagnosis instead of dropping them.
                    fs::rename(
                        entry.path(),
                        self.root.join("rejected").join(entry.file_name()),
                    )
                    .await?;
                    self.sync_directory("rejected").await?;
                    self.sync_directory("pending").await?;
                }
            }
        }
        Ok(result)
    }

    pub async fn ack(&self, id: &str) -> Result<()> {
        fs::remove_file(self.pending(id)?).await?;
        self.sync_directory("pending").await
    }

    pub async fn reject(&self, id: &str) -> Result<()> {
        fs::rename(
            self.pending(id)?,
            self.root.join("rejected").join(format!("{id}.json")),
        )
        .await?;
        self.sync_directory("rejected").await?;
        self.sync_directory("pending").await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn test_queue(label: &str) -> Result<(PathBuf, DurableQueue)> {
        let path = std::env::temp_dir().join(format!(
            "iot-{label}-{}-{}",
            std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ));
        let queue = DurableQueue::new(path.clone()).await?;
        Ok((path, queue))
    }

    #[tokio::test]
    async fn malformed_records_are_quarantined_without_blocking_valid_events() -> Result<()> {
        let (path, queue) = test_queue("corrupt").await?;
        let valid = queue.enqueue("/test", &serde_json::json!({})).await?;
        let mut invalid = DurableQueue::prepare("/test", &serde_json::json!({}))?;
        invalid.id = "../bad".into();
        fs::write(
            path.join("pending/bad-id.json"),
            serde_json::to_vec(&invalid)?,
        )
        .await?;
        fs::write(path.join("pending/truncated.json"), b"{\"id\":").await?;
        let mut mismatched = DurableQueue::prepare("/test", &serde_json::json!({}))?;
        mismatched.body["event_id"] = "wrong".into();
        queue.persist(&mismatched).await?;
        let batch = queue.batch(20).await?;
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].id, valid);
        assert!(path.join("rejected/bad-id.json").exists());
        assert!(path.join("rejected/truncated.json").exists());
        assert!(path
            .join("rejected")
            .join(format!("{}.json", mismatched.id))
            .exists());
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[tokio::test]
    async fn retrying_batch_does_not_starve_later_events() -> Result<()> {
        let (path, queue) = test_queue("fair").await?;
        for n in 0..9 {
            queue.enqueue("/test", &serde_json::json!({"n": n})).await?;
        }
        let mut seen = std::collections::HashSet::new();
        for _ in 0..3 {
            let items = queue.batch(3).await?;
            assert_eq!(items.len(), 3);
            for item in items {
                assert!(seen.insert(item.id));
            }
        }
        assert_eq!(seen.len(), 9);
        // Finish the current pass; unacknowledged events return on the next pass.
        assert!(queue.batch(3).await?.is_empty());
        assert_eq!(queue.batch(3).await?.len(), 3);
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[tokio::test]
    async fn persistence_failure_leaves_identity_retryable() -> Result<()> {
        let (path, queue) = test_queue("write-fail").await?;
        let item = DurableQueue::prepare("/test", &serde_json::json!({"n": 1}))?;
        fs::remove_dir(path.join("pending")).await?;
        fs::write(path.join("pending"), b"unavailable storage").await?;
        assert!(queue.persist(&item).await.is_err());
        fs::remove_file(path.join("pending")).await?;
        fs::create_dir(path.join("pending")).await?;
        queue.persist(&item).await?;
        assert_eq!(queue.batch(10).await?[0].id, item.id);
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn asynchronous_write_failure_never_publishes_empty_receipt() -> Result<()> {
        let (path, queue) = test_queue("async-write-fail").await?;
        let item = DurableQueue::prepare("/test", &serde_json::json!({"n": 1}))?;
        let temp = path.join("pending").join(format!("{}.tmp", item.id));
        fs::symlink("/dev/full", &temp).await?;
        assert!(queue.persist(&item).await.is_err());
        assert!(!queue.pending(&item.id)?.exists());
        fs::remove_file(temp).await?;
        queue.persist(&item).await?;
        assert_eq!(queue.batch(10).await?[0].id, item.id);
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn persisted_events_and_directories_are_private() -> Result<()> {
        use std::os::unix::fs::PermissionsExt;
        let (path, queue) = test_queue("permissions").await?;
        let id = queue.enqueue("/test", &serde_json::json!({})).await?;
        for dir in [&path, &path.join("pending"), &path.join("rejected")] {
            assert_eq!(fs::metadata(dir).await?.permissions().mode() & 0o777, 0o700);
        }
        assert_eq!(
            fs::metadata(queue.pending(&id)?)
                .await?
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[tokio::test]
    async fn receipt_survives_read_and_restart_until_ack() -> Result<()> {
        let path = std::env::temp_dir().join(format!(
            "iot-outbox-test-{}",
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ));
        let queue = DurableQueue::new(path.clone()).await?;
        let id = queue
            .enqueue("/test", &serde_json::json!({"value": 1}))
            .await?;
        let first = queue.batch(1).await?;
        assert_eq!(first[0].id, id);
        drop(queue);
        let queue = DurableQueue::new(path.clone()).await?;
        let second = queue.batch(1).await?;
        assert_eq!(first[0].body, second[0].body);
        queue.ack(&id).await?;
        assert!(queue.batch(1).await?.is_empty());
        fs::remove_dir_all(path).await?;
        Ok(())
    }

    #[tokio::test]
    async fn permanent_rejections_are_preserved() -> Result<()> {
        let path = std::env::temp_dir().join(format!(
            "iot-reject-test-{}",
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
        ));
        let queue = DurableQueue::new(path.clone()).await?;
        let id = queue.enqueue("/test", &serde_json::json!({})).await?;
        assert!(queue.ack("../bad").await.is_err());
        queue.reject(&id).await?;
        assert!(queue.batch(1).await?.is_empty());
        assert!(path.join("rejected").join(format!("{id}.json")).exists());
        fs::remove_dir_all(path).await?;
        Ok(())
    }
}

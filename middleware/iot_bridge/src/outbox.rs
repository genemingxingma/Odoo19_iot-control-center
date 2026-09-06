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
        Ok(Self { root })
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
        let mut entries = fs::read_dir(self.root.join("pending")).await?;
        let mut result = Vec::new();
        while let Some(entry) = entries.next_entry().await? {
            if result.len() >= limit {
                break;
            }
            if entry.path().extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let bytes = fs::read(entry.path()).await?;
            match serde_json::from_slice::<QueuedPost>(&bytes) {
                Ok(item) if self.pending(&item.id)? == entry.path() => result.push(item),
                _ => {
                    // Preserve corrupt payloads for diagnosis instead of dropping them.
                    fs::rename(
                        entry.path(),
                        self.root.join("rejected").join(entry.file_name()),
                    )
                    .await?;
                    self.sync_directory("rejected").await?;
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

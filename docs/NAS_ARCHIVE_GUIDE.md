# NAS Archive Guide

> How to set up TrueNAS for vigil archive sync, access encrypted footage, and extract training data.

---

## Overview

The pipeline:

1. **Archiver** (hourly) — encrypts labeled JPEG frames older than 24h with `age`, writes `.age` files to `dataset/archive/`
2. **NAS Sync** (nightly 3am) — rsyncs `.age` files and log files to TrueNAS over Tailscale, then deletes local `.age` copies
3. **SMB share** — makes the TrueNAS archive browsable from your Mac
4. **Decryption** — pull files to Mac and decrypt with private key from 1Password

---

## TrueNAS Setup

### 1. Install Tailscale on TrueNAS

Apps → Discover Apps → Tailscale → Install. After install, open TrueNAS shell and run `tailscale up`. Note the Tailscale IP from the admin console.

### 2. Create the archive dataset

Storage → your pool → Add Dataset:

| Setting | Value |
|---------|-------|
| Name | `vigil-archive` |
| Preset | `Generic` |
| ACL Type | `POSIX` |

### 3. Create the `vigil-sync` user

Credentials → Local Users → Add:

| Setting | Value |
|---------|-------|
| Username | `vigil-sync` |
| Shell | `/usr/bin/sh` |
| Home Directory | `/mnt/<pool>/vigil-archive` |

### 4. Set dataset permissions

Storage → `vigil-archive` → Edit Permissions → set ACL:

| Entry | Permissions |
|-------|-------------|
| User Obj – vigil-sync | Read, Write, Execute |
| Group Obj – vigil-sync | Read, Write, Execute |
| Other | Read, Execute (no Write — SSH StrictModes requirement) |

Check **Apply recursively** and **Apply to child datasets** → Save.

### 5. Enable SSH service

System → Services → SSH → Enable, set to start automatically.

### 6. Add the Pi's SSH key to TrueNAS

On the Pi, generate a dedicated key:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/vigil_nas
```

Add the SSH config entry on the Pi:

```
Host vigil-nas
    HostName <truenas-tailscale-ip>
    User vigil-sync
    IdentityFile ~/.ssh/vigil_nas
```

To authorize the key on TrueNAS, write it using the `vigil-sync` user (TrueNAS SCALE ignores filesystem writes from other users — `ssh-copy-id` won't work):

```bash
# From TrueNAS shell
mkdir -p /mnt/<pool>/vigil-archive/.ssh
sudo -u vigil-sync chmod 700 /mnt/<pool>/vigil-archive/.ssh
echo "ssh-ed25519 AAAA..." | sudo -u vigil-sync tee /mnt/<pool>/vigil-archive/.ssh/authorized_keys
sudo -u vigil-sync chmod 600 /mnt/<pool>/vigil-archive/.ssh/authorized_keys
```

Test from the Pi:

```bash
ssh vigil-nas echo ok
```

Expected: `ok`

### 7. Create the SMB share

Shares → Windows (SMB) Shares → Add:

| Setting | Value |
|---------|-------|
| Path | `/mnt/<pool>/vigil-archive` |
| Name | `vigil-archive` |
| Export Read Only | Checked |
| Access Based Share Enumeration | Checked |

**Important:** After saving the SMB share, go back to the dataset's Edit Permissions and verify the ACL type is still POSIX — enabling a share with ACL support can reset it to NFSv4. If it changed, strip ACLs and re-apply the POSIX permissions above.

Create a separate local TrueNAS user for SMB access (not `vigil-sync`). Edit that user → check **Samba Authentication** → set a password. Add read access for that user in the dataset ACL.

### 8. Configure the Pi

In `config.yaml`:

```yaml
security:
  nas_sync_enabled: true
  nas_rsync_target: "vigil-nas:/mnt/<pool>/vigil-archive"
```

Ensure `log.jsonl` is readable on the Pi so it arrives with correct permissions on TrueNAS:

```bash
chmod 644 ~/projects/grandma-watcher/dataset/log.jsonl
```

### 9. Verify timers

```bash
systemctl list-timers archiver.timer nas_sync.timer
```

Both should show next trigger times.

---

## Accessing Files from Your Mac

### Mount the SMB share

Finder → `Cmd+K` → enter:

```
smb://<truenas-ip>/vigil-archive
```

Log in with your TrueNAS SMB user credentials. The share mounts as a drive in Finder.

### Files in the share

| File | Contents |
|------|----------|
| `*.age` | Encrypted JPEG frames |
| `log.jsonl` | VLM assessments with labels |
| `checkins.jsonl` | Health check pings (not needed for training) |

---

## Decrypting Files

The age private key is stored in 1Password (Secure Note → password field). The `op` CLI reads it without writing to disk.

**Install age and 1Password CLI** (one-time):

```bash
brew install age 1password-cli
```

**Single file:**

```bash
op read "op://Personal/vigil age private key/private key" | age -d -i - file.age > file.jpg
```

**Whole folder:**

```bash
KEY=$(op read "op://Personal/vigil age private key/private key")
for f in ~/Downloads/vigil-archive/*.age; do
  echo "$KEY" | age -d -i - "$f" > "${f%.age}"
done
unset KEY
```

**Clean up when done** (decrypted frames are plain unencrypted patient footage):

```bash
rm ~/Downloads/vigil-archive/*.jpg
```

---

## Extracting Training Data from log.jsonl

Each line in `log.jsonl` is a JSON object with one VLM assessment.

**View all entries (timestamp, label, image filename):**

```bash
python3 - <<'EOF'
import json
rows = [json.loads(l) for l in open("log.jsonl")]
for r in rows:
    print(r.get("timestamp", ""), r.get("label", ""), r.get("image_path", "").split("/")[-1])
EOF
```

**Filter unsafe events only:**

```bash
python3 - <<'EOF'
import json
rows = [json.loads(l) for l in open("log.jsonl")]
for r in rows:
    if "unsafe" in str(r.get("label", "")).lower():
        print(r.get("timestamp", ""), r.get("label", ""), r.get("image_path", "").split("/")[-1])
EOF
```

**Export labeled rows to CSV:**

```bash
python3 - <<'EOF'
import json, csv, sys
rows = [json.loads(l) for l in open("log.jsonl")]
labeled = [r for r in rows if r.get("label") and r.get("image_path")]
writer = csv.DictWriter(sys.stdout, fieldnames=["timestamp", "label", "image_path"])
writer.writeheader()
for r in labeled:
    writer.writerow({k: r.get(k, "") for k in writer.fieldnames})
EOF
```

**Match log entries to decrypted images:**

The `image_path` field in `log.jsonl` contains the original filename (e.g., `2026-04-10_14-43-37.jpg`). The corresponding archive file is `2026-04-10_14-43-37.jpg.age`. After decryption, filenames match directly.

---

*Last updated: 2026-04-13*

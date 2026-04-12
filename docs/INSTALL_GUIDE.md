# Raspberry Pi Setup Guide

> Step-by-step guide for setting up a headless Raspberry Pi 5 for Vigil. This guide assumes you're using a Mac and want key-based SSH from first boot.

---

## Prerequisites (Mac)

Before touching the Pi, ensure you have:

- [ ] **macOS** with admin access
- [ ] **Raspberry Pi 5** with power supply
- [ ] **microSD card** (32GB+ recommended, Class 10 or better)
- [ ] **microSD card reader** (USB-C or USB-A adapter)
- [ ] **Wi-Fi network credentials** (SSID and password)
- [ ] **1Password** installed and unlocked (for SSH key storage)
- [ ] **Homebrew** installed (`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` if needed)

---

## Step 1: Install Raspberry Pi Imager

```bash
brew install --cask raspberry-pi-imager
```

Or download manually from [raspberrypi.com/software](https://www.raspberrypi.com/software/).

---

## Step 2: Generate a Dedicated SSH Keypair

Create an ed25519 keypair specifically for this Pi:

```bash
# Create SSH directory if it doesn't exist
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Generate the key (replace 'pi5' with your desired hostname)
ssh-keygen -t ed25519 -C "pi5-$(date +%Y-%m-%d)" -f ~/.ssh/id_ed25519_pi5

# Set correct permissions
chmod 600 ~/.ssh/id_ed25519_pi5
chmod 644 ~/.ssh/id_ed25519_pi5.pub
```

**Output:** Two files created:
- `~/.ssh/id_ed25519_pi5` — **private key** (keep secure)
- `~/.ssh/id_ed25519_pi5.pub` — **public key** (safe to share)

---

## Step 3: Store Private Key in 1Password

1. Open **1Password** → Click the **+** button → Select **SSH Key**
2. Title: `Raspberry Pi 5 - vigil`
3. Account/Username: `pi` (or your chosen username)
4. Click **Add Private Key**
5. Select **Choose File** and pick `~/.ssh/id_ed25519_pi5`
6. Save the item

> **Security note:** The private key is now in 1Password. You can delete the local file if desired, but keeping it in `~/.ssh/` is fine for SSH agent use.

---

## Step 4: Copy the Public Key

```bash
# Display the public key for copying
cat ~/.ssh/id_ed25519_pi5.pub
```

Select and copy the entire output (it looks like `ssh-ed25519 AAAAC3NzaC... comment`).

---

## Step 5: Flash Raspberry Pi OS

1. **Insert the microSD card** into your Mac
2. **Open Raspberry Pi Imager**
3. Click **CHOOSE DEVICE** → Select **RASPBERRY PI 5**
4. Click **CHOOSE OS** → Select **Raspberry Pi OS (64-bit)** → **Raspberry Pi OS Lite (64-bit)**
5. Click **CHOOSE STORAGE** → Select your microSD card
6. Click the **gear icon** (⚙️) or press **Cmd+Shift+X** to open **Advanced Options**:

### Advanced Options Configuration

| Setting | Value |
|---------|-------|
| **Set hostname** | `pi5.local` (or your preference) |
| **Enable SSH** | ☑️ Checked → **Allow public-key authentication only** |
| **Set authorized_keys** | Paste your **public key** from Step 4 |
| **Set username and password** | Username: `pi` (or your choice), Password: *(strong password, for fallback only)* |
| **Configure wireless LAN** | ☑️ Checked → Enter your **SSID** and **password** |
| **Set locale settings** | Select your **Time zone** and **Keyboard layout** |

7. Click **SAVE** to apply advanced options
8. Click **WRITE** and confirm to flash the SD card
9. Wait for verification to complete, then eject the card

---

## Step 6: First Boot

1. **Insert the microSD card** into the Raspberry Pi
2. **Connect power** — the Pi will boot automatically
3. Wait **60-90 seconds** for first boot and Wi-Fi connection

---

## Step 7: Find the Pi on Your Network

### Option A: Using hostname (preferred)

```bash
# The hostname set in Imager should resolve
ping pi5.local
```

### Option B: Scan your network

```bash
# Install arp-scan if needed
brew install arp-scan

# Find the Pi (look for "Raspberry Pi" or the MAC vendor)
sudo arp-scan --localnet | grep -i raspberry

# Or use nmap
nmap -sn 192.168.1.0/24 | grep -B 2 raspberry
```

Note the IP address (e.g., `192.168.1.XXX`).

---

## Step 8: SSH Login from Mac

### Configure SSH client (one-time)

Add to `~/.ssh/config`:

```bash
# Create or edit SSH config
nano ~/.ssh/config
```

Add this entry:

```
Host pi5
    HostName pi5.local
    User pi
    IdentityFile ~/.ssh/id_ed25519_pi5
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Set permissions:

```bash
chmod 600 ~/.ssh/config
```

### First SSH connection

```bash
# Connect using the configured alias
ssh pi5
```

**Expected:** You should connect **without a password** using key authentication.

**First-time prompt:** Type `yes` to accept the host fingerprint.

---

## Step 9: Update the Pi

Once logged in, update the system:

```bash
# Update package lists
sudo apt update

# Upgrade installed packages
sudo apt upgrade -y

# Install essential tools
sudo apt install -y git vim htop curl wget

# Clean up
sudo apt autoremove -y
```

---

## Step 10: Clone the vigil Repo

```bash
# Create projects directory
mkdir -p ~/projects && cd ~/projects

# Clone the repository
git clone https://github.com/YOUR_USERNAME/vigil.git

# Or if using SSH:
git clone git@github.com:YOUR_USERNAME/vigil.git

cd vigil
```

---

## Step 11: Configure the Application

```bash
# Create config from scratch (config.yaml is in .gitignore — never committed)
nano config.yaml
```

**Minimum required keys:**
- `api.openrouter_api_key` — Your OpenRouter API key
- `alerts.pushover_api_key` — Your Pushover app token
- `alerts.pushover_user_key` — Your Pushover user key

See `config.py` for the full schema and all available settings.

---

## Step 12: Prepare for Camera Setup (Optional)

The camera hardware setup is covered separately. To prepare:

1. **Enable camera interface** (for CSI camera):

```bash
sudo raspi-config
# Navigate to: Interface Options → Camera → Enable → Finish
```

2. **Install go2rtc** (for video streaming):

```bash
# Handled by setup/install.sh — review go2rtc.yaml for camera settings
cd ~/projects/vigil
bash setup/install.sh
```

3. **Note the CSI camera ribbon cable** — connect after full system setup is verified

---

## Troubleshooting

### Cannot resolve pi5.local

```bash
# Use IP address directly
ssh pi@192.168.1.XXX
```

## Dataset Encryption and NAS Sync Setup

This section configures `age` encryption for archived frames and nightly rsync to TrueNAS.

### 1. Generate an age key pair

Run this on your **builder machine** (not the Pi):

```bash
age-keygen -o ~/vigil-key.txt
```

This writes a key file containing two lines:
```
# created: ...
# public key: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AGE-SECRET-KEY-1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Keep `~/vigil-key.txt` off the Pi.** Only the public key goes on the Pi.

### 2. Copy the public key to config.yaml

Copy the `public key:` line value (starts with `age1`) into `config.yaml` on the Pi:

```yaml
security:
  age_public_key: "age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 3. Create a `vigil-sync` user on TrueNAS

In TrueNAS -> Credentials -> Local Users, create a user named `vigil-sync` with:
- Shell: `/bin/sh`
- Home directory: `/mnt/pool/vigil-archive` (or your chosen dataset path)
- Appropriate dataset permissions (read/write on the archive dataset only)

### 4. Generate an SSH key on the Pi

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/vigil_nas
```

### 5. Authorize the Pi's key on TrueNAS

```bash
ssh-copy-id -i ~/.ssh/vigil_nas.pub vigil-sync@<tailscale-ip>
```

Replace `<tailscale-ip>` with the TrueNAS Tailscale IP (visible in the Tailscale admin console).

Test the connection:

```bash
ssh -i ~/.ssh/vigil_nas vigil-sync@<tailscale-ip> echo ok
```

Expected: `ok`

### 5b. Add an SSH config entry

This ensures rsync uses the correct key (the Pi may have multiple SSH keys; without this entry, rsync picks one arbitrarily):

```bash
cat >> ~/.ssh/config <<'EOF'

Host vigil-nas
    HostName <tailscale-ip>
    User vigil-sync
    IdentityFile ~/.ssh/vigil_nas
EOF
```

Verify the alias works:

```bash
ssh vigil-nas echo ok
```

Expected: `ok`

### 6. Configure NAS sync in config.yaml

```yaml
security:
  nas_sync_enabled: true
  nas_rsync_target: "vigil-nas:/mnt/pool/vigil-archive"
```

### 7. Test with a dry-run

```bash
rsync -avz --dry-run dataset/archive/ vigil-nas:/mnt/pool/vigil-archive/
```

Expected: rsync output showing files that would be transferred (no actual transfer).

### 8. Verify timers are running

```bash
systemctl list-timers archiver.timer nas_sync.timer
```

Expected: both timers listed with next trigger times.

### Security notes

- The `age` public key in `config.yaml` can only encrypt, not decrypt. It is safe to store there.
- A stolen Pi contains only encrypted `.age` blobs - unreadable without the private key at `~/vigil-key.txt`.
- The Pi should be kept physically secured during the 24-hour active window when frames are still unencrypted.
- All rsync traffic travels over the Tailscale encrypted tunnel - no additional firewall rules required.

### Permission denied (publickey)

1. Verify the public key was pasted correctly in Imager
2. Check the key file permissions on Mac:
   ```bash
   ls -la ~/.ssh/id_ed25519_pi5*
   ```
3. Try explicit key:
   ```bash
   ssh -i ~/.ssh/id_ed25519_pi5 pi@pi5.local
   ```

### Wi-Fi not connecting

- Re-image with correct SSID/password
- Ensure 2.4GHz network (Pi may not connect to 5GHz depending on model)
- Check router for connected devices

---

## What's Next?

| Status | Task | Location |
|--------|------|----------|
| ⬜ | Run full system setup | `setup/install.sh` |
| ⬜ | Configure Tailscale for remote access | `setup/tailscale_setup.sh` |
| ⬜ | Configure Cloudflare Tunnel | `setup/cloudflare_setup.sh` |
| ⬜ | Review go2rtc camera settings | `go2rtc.yaml` |
| ⬜ | Test monitoring loop | `python monitor.py` |

---

## Security Checklist

- [ ] Private key stored in 1Password
- [ ] Password authentication disabled (done via Imager advanced options)
- [ ] Strong fallback password set
- [ ] SSH config uses `IdentitiesOnly yes`
- [ ] `config.yaml` with API keys is in `.gitignore`
- [ ] UFW firewall enabled (after full setup)

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `ssh pi5` | Connect to Pi |
| `sudo shutdown now` | Graceful shutdown |
| `sudo reboot` | Restart Pi |
| `journalctl -u monitor -f` | View monitor logs |
| `htop` | System resource monitor |

---

*Last updated: 2026-04-11*

# Server Setup Guide — Docker, Nginx, PostgreSQL

Complete guide to setting up a production server for the SaaS platform.

---

## Requirements

- **OS:** Ubuntu 22.04 LTS or 24.04 LTS (recommended)
- **RAM:** Minimum 4GB, recommended 16GB+
- **Disk:** SSD, minimum 50GB, recommended 200GB+
- **CPU:** Minimum 2 cores, recommended 4+
- **Network:** Static IP, ports 80/443 open

---

## Step 1: Initial Server Setup

### 1.1 Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.2 Set timezone

```bash
sudo timedatectl set-timezone UTC
```

### 1.3 Create the SaaS user

The platform connects via SSH using this user. It needs `sudo` privileges for Docker, Nginx, and PostgreSQL commands.

```bash
sudo adduser --system --group --home /home/saas --shell /bin/bash saas
sudo usermod -aG sudo saas

# Allow passwordless sudo (required — the platform runs commands via SSH)
echo "saas ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/saas
```

### 1.4 Setup SSH keys

On your **management server** (where the Odoo SaaS Manager module runs):

```bash
# Generate a key pair if you don't have one
ssh-keygen -t ed25519 -C "saas-platform" -f ~/.ssh/saas_deploy

# Copy public key to the Docker host
ssh-copy-id -i ~/.ssh/saas_deploy.pub saas@your-server-ip
```

Test the connection:
```bash
ssh -i ~/.ssh/saas_deploy saas@your-server-ip "echo OK"
```

---

## Step 2: Install Docker

### 2.1 Install Docker Engine

```bash
# Remove old versions
sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null

# Install prerequisites
sudo apt install -y ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 2.2 Configure Docker

```bash
# Add saas user to docker group
sudo usermod -aG docker saas

# Enable Docker to start on boot
sudo systemctl enable docker
sudo systemctl start docker
```

### 2.3 Configure Docker daemon

```bash
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "live-restore": true,
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 65536,
      "Soft": 65536
    }
  }
}
EOF

sudo systemctl restart docker
```

### 2.4 Verify

```bash
docker --version
docker compose version
docker run --rm hello-world
```

---

## Step 3: Install PostgreSQL

The platform creates databases and roles via SSH using `sudo -u postgres psql`. No special admin role is needed — just a working PostgreSQL installation accessible from Docker containers.

### 3.1 Install PostgreSQL 16

```bash
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16
```

### 3.2 Allow connections from Docker containers and remote servers

Docker containers and remote Docker host servers need to connect to PostgreSQL.

```bash
# Allow listening on all interfaces (required for remote connections)
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/16/main/postgresql.conf

# Verify the change took effect (should NOT show 127.0.0.1 after restart):
#   ss -tlnp | grep 5432
# Expected: 0.0.0.0:5432 (listening on all interfaces)

# Allow all hosts to connect with password authentication.
# For PostgreSQL 16+, use scram-sha-256 (md5 may be rejected).
# In production, restrict 0.0.0.0/0 to your private subnet (e.g. 10.135.0.0/16).
sudo tee -a /etc/postgresql/16/main/pg_hba.conf << 'EOF'

# Docker container networks (172.16.0.0/12 covers all Docker bridge subnets)
host    all    all    172.16.0.0/12    scram-sha-256
# Remote Docker host servers (private network)
host    all    all    0.0.0.0/0        scram-sha-256
EOF

sudo systemctl restart postgresql
```

### 3.3 Performance tuning

Create a tuning file (adjust values based on your server RAM):

```bash
sudo tee /etc/postgresql/16/main/conf.d/saas.conf << 'EOF'
# For 16GB RAM server — adjust proportionally
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 16MB
maintenance_work_mem = 1GB
max_connections = 500
wal_buffers = 64MB
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
default_statistics_target = 100
log_min_duration_statement = 1000
log_checkpoints = on
EOF
```

### 3.4 Restart PostgreSQL

```bash
sudo systemctl restart postgresql
sudo systemctl enable postgresql
```

### 3.5 Verify

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check it's listening
sudo -u postgres psql -c "SELECT version();"
```

---

## Step 4: Install Nginx

The platform writes Nginx configs to `/etc/nginx/sites-enabled/` and reloads Nginx via SSH for each instance.

### 4.1 Install Nginx

```bash
sudo apt install -y nginx
```

### 4.2 Remove default site

```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

### 4.3 Global Nginx optimization

```bash
sudo tee /etc/nginx/conf.d/optimization.conf << 'EOF'
proxy_connect_timeout 720s;
proxy_read_timeout 720s;
proxy_send_timeout 720s;
proxy_buffers 16 64k;
proxy_buffer_size 128k;

gzip on;
gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;
gzip_min_length 1000;
gzip_comp_level 6;

add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;

client_max_body_size 200M;

map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
EOF
```

### 4.4 Restart Nginx

```bash
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## Step 5: Install Certbot (SSL)

The platform runs `certbot certonly --nginx` via SSH for each new instance.

```bash
sudo apt install -y certbot python3-certbot-nginx
```

Verify auto-renewal is enabled:
```bash
sudo systemctl status certbot.timer
```

---

## Step 6: Setup Odoo Source (Shared)

One copy of Odoo source per version, shared by all containers. See [README.md](README.md) for details.

```bash
chmod +x setup-source.sh
sudo ./setup-source.sh
```

Or manually:
```bash
sudo mkdir -p /opt/odoo-source/18.0
cd /opt/odoo-source/18.0
sudo git clone --depth 1 --branch 18.0 https://github.com/odoo/odoo.git .
sudo chmod -R a+rX /opt/odoo-source/
```

---

## Step 7: Load Docker Images

Build locally or pull from your registry. See [README.md](README.md) for details.

```bash
chmod +x build-all.sh
./build-all.sh
```

---

## Step 8: Create Instance Directory

```bash
sudo mkdir -p /home/saas/instances
sudo chown saas:saas /home/saas/instances
```

---

## Step 9: Configure DNS

Create a **wildcard DNS record** for each base domain:

```
Type: A
Name: *.saas.yourcompany.com
Value: YOUR_SERVER_IP
TTL: 300
```

Verify:
```bash
dig +short anything.saas.yourcompany.com
# Should return your server IP
```

---

## Step 10: Configure the SaaS Platform

In your Odoo backend (**SaaS Manager** module):

### 10.1 Add the server

**SaaS Manager > Configuration > Servers:**

| Field | Value |
|-------|-------|
| Name | Production Server 1 |
| Hostname / IP | your server IP |
| SSH Port | 22 |
| SSH User | `saas` |
| Is Docker Host | Yes |
| Is DB Server | Yes |
| Instance Base Path | `/home/saas/instances` |

Configure the SSH private key on the server record.

### 10.2 Add base domains

**SaaS Manager > Configuration > Base Domains:**

| Field | Value |
|-------|-------|
| Name | `saas.yourcompany.com` |

### 10.3 Add Odoo versions

**SaaS Manager > Configuration > Odoo Versions:**

| Version | Docker Image | Image Tag | Nginx Template | Hosting Version |
|---------|-------------|-----------|----------------|-----------------|
| 14.0 | odoo-light | 14.0 | Old (≤15) | Yes |
| 15.0 | odoo-light | 15.0 | Old (≤15) | Yes |
| 16.0 | odoo-light | 16.0 | New (16+) | Yes |
| 17.0 | odoo-light | 17.0 | New (16+) | Yes |
| 18.0 | odoo-light | 18.0 | New (16+) | Yes |
| 19.0 | odoo-light | 19.0 | New (16+) | Yes |

Check **Hosting Version** for versions available to hosting customers.

### 10.4 Configure pricing

**Settings > SaaS > Custom Plan Builder** (services) and **Hosting Plan Builder** (hosting).

### 10.5 Test SSH connection

On the server record, click **Test Connection** to verify the platform can reach the server.

---

## Step 11: Test

1. Go to your website `/services` or `/hosting`
2. Create a test instance
3. Wait for provisioning
4. Verify the instance URL works with HTTPS

On the server:
```bash
docker ps | grep odoo_
docker logs odoo_testsubdomain --tail 20
```

---

## Firewall

```bash
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 80/tcp      # HTTP
sudo ufw allow 443/tcp     # HTTPS
sudo ufw deny 5432/tcp     # Block PostgreSQL from internet
sudo ufw enable
```

---

## Security Checklist

- [ ] SSH key authentication only (disable password login)
- [ ] Firewall enabled (ports 22, 80, 443 only)
- [ ] PostgreSQL not exposed to internet
- [ ] Odoo source mounted read-only
- [ ] `saas` user has passwordless sudo
- [ ] Unattended security updates enabled
- [ ] Fail2ban installed

```bash
# Enable unattended upgrades
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Install Fail2ban
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
```

---

## Quick Reference

| Component | Config Location | Restart Command |
|-----------|----------------|-----------------|
| Docker | `/etc/docker/daemon.json` | `sudo systemctl restart docker` |
| PostgreSQL | `/etc/postgresql/16/main/` | `sudo systemctl restart postgresql` |
| Nginx | `/etc/nginx/sites-enabled/` | `sudo systemctl reload nginx` |
| Instance configs | `/home/saas/instances/<name>/` | `cd <dir> && docker compose restart` |
| Odoo source | `/opt/odoo-source/<version>/` | `git pull` + restart containers |

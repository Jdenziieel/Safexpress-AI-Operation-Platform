# Production Deployment Guide with HTTPS/TLS

## Overview
This guide covers deploying your FastAPI application to production with proper security measures, including HTTPS/TLS encryption.

---

## Deployment Options

### ✅ **Recommended: Reverse Proxy (Nginx/Caddy)**

Using a reverse proxy is the **industry standard** and **most secure** approach for production deployments.

#### Why Use a Reverse Proxy?

1. **Automatic HTTPS**: Free Let's Encrypt certificates with auto-renewal
2. **Better Performance**: Static file serving, caching, gzip compression
3. **Load Balancing**: Distribute traffic across multiple FastAPI instances
4. **Security**: DDoS protection, rate limiting at network level
5. **Zero Downtime Deploys**: Update backend without dropping connections
6. **Logging & Monitoring**: Centralized access logs

---

## Option 1: Nginx + Let's Encrypt (Ubuntu/Debian)

### Step 1: Install Nginx and Certbot

```bash
sudo apt update
sudo apt install nginx certbot python3-certbot-nginx
```

### Step 2: Configure Nginx

Create `/etc/nginx/sites-available/knowledge-base`:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name yourdomain.com www.yourdomain.com;
    
    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    # Redirect all other HTTP to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS Server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;
    
    # SSL certificates (managed by Certbot)
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    
    # SSL configuration (Mozilla Intermediate)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # HSTS (31536000 seconds = 1 year)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Request size limit (10MB for PDF uploads)
    client_max_body_size 10M;
    
    # Proxy settings
    location / {
        proxy_pass http://127.0.0.1:8009;
        proxy_http_version 1.1;
        
        # WebSocket support (if needed for future features)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Forward client information
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Health check endpoint (optional)
    location /health {
        access_log off;
        proxy_pass http://127.0.0.1:8009/health;
    }
}
```

### Step 3: Enable Site and Obtain SSL Certificate

```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/knowledge-base /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Obtain SSL certificate
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Restart Nginx
sudo systemctl restart nginx
```

### Step 4: Auto-Renewal Setup

Certbot automatically sets up a cron job. Test renewal:

```bash
sudo certbot renew --dry-run
```

---

## Option 2: Caddy (Simpler Alternative)

Caddy automatically handles HTTPS with Let's Encrypt - **no manual configuration needed!**

### Step 1: Install Caddy

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### Step 2: Configure Caddy

Create `/etc/caddy/Caddyfile`:

```caddy
# Automatic HTTPS - Caddy handles everything!
yourdomain.com, www.yourdomain.com {
    # Reverse proxy to FastAPI
    reverse_proxy localhost:8009
    
    # Request size limit
    request_body {
        max_size 10MB
    }
    
    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        X-XSS-Protection "1; mode=block"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
    
    # Gzip compression
    encode gzip
    
    # Access logging
    log {
        output file /var/log/caddy/access.log
    }
}
```

### Step 3: Start Caddy

```bash
sudo systemctl restart caddy
sudo systemctl enable caddy
```

**That's it!** Caddy automatically obtains and renews SSL certificates.

---

## Option 3: Direct HTTPS in FastAPI (Not Recommended)

Only use this for testing or very simple deployments.

### Step 1: Generate Self-Signed Certificate (Testing Only)

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes
```

### Step 2: Update `.env`

```bash
USE_HTTPS=true
SSL_CERTFILE=/path/to/cert.pem
SSL_KEYFILE=/path/to/key.pem
```

### Step 3: Production Certificates

For production, use Let's Encrypt:

```bash
# Install certbot
sudo apt install certbot

# Obtain certificate (standalone mode)
sudo certbot certonly --standalone -d yourdomain.com

# Certificates will be at:
# /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

**⚠️ Limitations:**
- No automatic renewal
- Single process (no load balancing)
- Manual SSL management
- Limited performance

---

## Complete Production Setup

### 1. System Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install python3.11 python3.11-venv python3-pip git

# Create application user
sudo useradd -m -s /bin/bash appuser
sudo su - appuser
```

### 2. Deploy Application

```bash
# Clone repository
git clone https://github.com/yourusername/Knowledge-Base.git
cd Knowledge-Base/backend

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Create production .env
cp .env.example .env
nano .env

# Update values:
ENVIRONMENT=production
DEBUG=false
JWT_SECRET_KEY=<generate-strong-random-key-here>
ALLOWED_ORIGINS=https://yourdomain.com
RATE_LIMIT_ENABLED=true
```

### 4. Create Systemd Service

Create `/etc/systemd/system/knowledge-base.service`:

```ini
[Unit]
Description=Knowledge Base FastAPI Application
After=network.target

[Service]
Type=simple
User=appuser
Group=appuser
WorkingDirectory=/home/appuser/Knowledge-Base/backend
Environment="PATH=/home/appuser/Knowledge-Base/backend/.venv/bin"
ExecStart=/home/appuser/Knowledge-Base/backend/.venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledge-base
sudo systemctl start knowledge-base
sudo systemctl status knowledge-base
```

### 5. Setup Reverse Proxy (Choose Nginx or Caddy)

Follow steps from Option 1 or Option 2 above.

### 6. Configure Firewall

```bash
# Allow SSH, HTTP, HTTPS
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

### 7. Setup Monitoring (Optional but Recommended)

```bash
# Install monitoring tools
sudo apt install htop nethogs

# View logs
sudo journalctl -u knowledge-base -f

# Monitor Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## Security Checklist

Before going live:

- [ ] HTTPS enabled via reverse proxy
- [ ] SSL certificate valid and auto-renewing
- [ ] `ENVIRONMENT=production` in .env
- [ ] `DEBUG=false` in .env
- [ ] Strong `JWT_SECRET_KEY` (32+ characters)
- [ ] `ALLOWED_ORIGINS` set to actual domain
- [ ] Rate limiting enabled
- [ ] Firewall configured (ports 22, 80, 443 only)
- [ ] Database backups configured
- [ ] Monitoring and logging enabled
- [ ] Error messages sanitized (no stack traces)
- [ ] Dependencies audited (`pip-audit`)
- [ ] Secrets in environment variables (not hardcoded)
- [ ] Regular security updates scheduled

---

## Testing HTTPS

After deployment, verify:

```bash
# Test SSL configuration
curl -I https://yourdomain.com

# Check SSL rating
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=yourdomain.com

# Test security headers
curl -I https://yourdomain.com | grep -E "(Strict-Transport|X-Frame|X-Content-Type)"
```

---

## Maintenance

### Update Application

```bash
sudo su - appuser
cd Knowledge-Base/backend
git pull
source .venv/bin/activate
pip install -r requirements.txt
exit

sudo systemctl restart knowledge-base
```

### View Logs

```bash
# Application logs
sudo journalctl -u knowledge-base -n 100

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Caddy logs
sudo journalctl -u caddy -n 100
```

### Backup Database

```bash
# SQLite database
cp /home/appuser/Knowledge-Base/backend/chat_sessions.db /backups/chat_sessions_$(date +%Y%m%d).db

# Weaviate backup (use Weaviate backup tools)
```

---

## Troubleshooting

### Issue: 502 Bad Gateway

**Solution:**
```bash
# Check if FastAPI is running
sudo systemctl status knowledge-base

# Check logs
sudo journalctl -u knowledge-base -n 50

# Verify port 8009 is listening
sudo netstat -tlnp | grep 8009
```

### Issue: SSL Certificate Errors

**Solution:**
```bash
# Renew certificate manually
sudo certbot renew

# Check certificate validity
sudo certbot certificates
```

### Issue: Rate Limiting Too Strict

**Solution:**
Edit `backend/middleware/security_middleware.py` and adjust `RATE_LIMITS` dictionary.

---

## Cloud Deployment (Quick Reference)

### Azure App Service
```bash
az webapp up --name your-app-name --resource-group your-rg --runtime "PYTHON:3.11"
```

### AWS Elastic Beanstalk
```bash
eb init -p python-3.11 knowledge-base
eb create production
eb deploy
```

### Google Cloud Run
```bash
gcloud run deploy knowledge-base --source . --platform managed
```

**Note:** Cloud platforms handle HTTPS automatically!

---

## Resources

- **Nginx SSL Config Generator**: https://ssl-config.mozilla.org/
- **Let's Encrypt**: https://letsencrypt.org/
- **Caddy Documentation**: https://caddyserver.com/docs/
- **FastAPI Deployment**: https://fastapi.tiangolo.com/deployment/

---

**Last Updated**: November 20, 2025

# 🔒 API Security Quick Reference

## What's Been Implemented

### ✅ Rate Limiting
- **Status**: Active
- **Limits**: 20 req/min (chat), 100 req/min (general), 10 req/hour (uploads)
- **Control**: `RATE_LIMIT_ENABLED=true` in .env
- **Response**: 429 Too Many Requests with Retry-After header

### ✅ Input Validation
- **Max Message**: 10,000 characters
- **Max File Size**: 10 MB
- **Allowed Files**: PDF only
- **Protection**: XSS, SQL injection, directory traversal

### ✅ Security Headers
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'
```

### ✅ HTTPS/TLS (Production Ready)
- **Development**: HTTP (localhost is secure)
- **Production**: Use Nginx or Caddy reverse proxy
- **Certificates**: Let's Encrypt (free, auto-renewing)

### ✅ CORS
- **Development**: localhost:5173, localhost:3000
- **Production**: Configure via `ALLOWED_ORIGINS` in .env

### ✅ File Upload Security
- Extension validation
- Size limits (10 MB)
- Filename sanitization
- Empty file rejection

---

## Configuration (.env)

```bash
# Development (Current)
ENVIRONMENT=development
DEBUG=true
RATE_LIMIT_ENABLED=true
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Production (Before Deployment)
ENVIRONMENT=production
DEBUG=false
RATE_LIMIT_ENABLED=true
ALLOWED_ORIGINS=https://yourdomain.com
JWT_SECRET_KEY=<32+ char random string>
```

---

## Quick Commands

### Test Security
```bash
python test_security.py
```

### Check Dependencies
```bash
pip install pip-audit
pip-audit
```

### Start Server (Development)
```bash
python app.py
```

### Start Server (Production)
```bash
# Use systemd service (see PRODUCTION_DEPLOYMENT_GUIDE.md)
sudo systemctl start knowledge-base
```

---

## Security Limits Reference

| Item | Limit | Location |
|------|-------|----------|
| Message Length | 10,000 chars | security_middleware.py |
| Session Title | 200 chars | security_middleware.py |
| Query Length | 5,000 chars | security_middleware.py |
| Filename Length | 255 chars | security_middleware.py |
| File Size | 10 MB | security_middleware.py |
| Request Body | 10 MB | app.py |
| Chat Requests | 20/min | security_middleware.py |
| Upload Requests | 10/hour | security_middleware.py |

---

## Testing Checklist

Before production:
- [ ] Run `python test_security.py`
- [ ] Test with invalid inputs
- [ ] Verify rate limiting works
- [ ] Check security headers
- [ ] Test file uploads
- [ ] Verify CORS configuration
- [ ] Run `pip-audit` for vulnerabilities
- [ ] Test with expired JWT token

---

## Common Issues & Solutions

### Rate Limited?
Adjust in `security_middleware.py` → `RATE_LIMITS` dict

### CORS Error?
Add your domain to `ALLOWED_ORIGINS` in .env

### File Rejected?
Check: file type (.pdf), size (<10MB), not empty

### Input Too Long?
Increase limits in `security_middleware.py`

---

## Documentation Files

1. **SECURITY_IMPLEMENTATION_SUMMARY.md** - This summary
2. **API_SECURITY_RECOMMENDATIONS.md** - All security options
3. **PRODUCTION_DEPLOYMENT_GUIDE.md** - HTTPS setup & deployment
4. **.env.example** - Configuration template

---

## Production Deployment (Quick)

### Option 1: Nginx (Most Common)
```bash
sudo apt install nginx certbot python3-certbot-nginx
# Edit /etc/nginx/sites-available/knowledge-base
sudo certbot --nginx -d yourdomain.com
sudo systemctl restart nginx
```

### Option 2: Caddy (Simplest)
```bash
sudo apt install caddy
# Edit /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

See **PRODUCTION_DEPLOYMENT_GUIDE.md** for details.

---

## Emergency Contacts

- **Disable Rate Limiting**: Set `RATE_LIMIT_ENABLED=false` in .env
- **Debug Mode**: Set `DEBUG=true` in .env
- **View Logs**: `sudo journalctl -u knowledge-base -f`
- **Restart Server**: `sudo systemctl restart knowledge-base`

---

## Security Review Schedule

- **Weekly**: Check logs for suspicious activity
- **Monthly**: Run `pip-audit` for vulnerabilities
- **Quarterly**: Full security review
- **Before Major Release**: Penetration testing

---

**Quick Start**: Everything works out of the box for development!
**Production**: Read PRODUCTION_DEPLOYMENT_GUIDE.md before deploying.

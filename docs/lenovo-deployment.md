# Lenovo M920x — Always-On Agent Deployment

Run your Personal AI Agent 24/7 on the Lenovo so you can chat via web and Telegram anytime.

---

## Prerequisites

- Lenovo M920x with **Ubuntu 22.04+** (or similar Linux)
- Python 3.10+
- Your config and secrets from your Mac

---

## 1. Clone and Install

```bash
# Clone (or copy the project via USB/scp)
git clone https://github.com/yourusername/ml-from-scratch.git
cd ml-from-scratch

# One-time setup
bash scripts/install.sh
```

During install, add your API keys when prompted (or edit `credentials/.secrets.env` after).

---

## 2. Copy Config from Mac

Copy these from your Mac to the Lenovo (same paths):

- `.env` — app settings, MODEL_PROVIDER, etc.
- `credentials/.secrets.env` — API keys (ANTHROPIC, GROQ, TELEGRAM_BOT_TOKEN)
- `my_data/` — your documents, resume
- `config.yaml` — optional overrides

```bash
# From your Mac (replace lenovo-ip with the Lenovo's IP)
scp -r .env credentials/.secrets.env my_data config.yaml user@lenovo-ip:~/ml-from-scratch/
```

Or use a USB drive, then copy into the project folder.

---

## 3. Index Documents (one-time)

```bash
cd ~/ml-from-scratch
source .venv/bin/activate
python load_documents.py
```

---

## 4. Install Systemd Service (always-on)

```bash
sudo bash scripts/install_linux_service.sh
```

This installs two services:
- `personal-ai-agent` — web dashboard (port 8000)
- `personal-ai-agent-telegram` — Telegram bot

Both start on boot and auto-restart on failure.

---

## 5. Access from Anywhere

### Web dashboard
- **On Lenovo:** http://localhost:8000
- **From phone/other device on same Wi‑Fi:** http://LENOVO_IP:8000

**Google OAuth:** If you connect Calendar/Gmail, complete the flow from a browser that can reach the Lenovo (e.g. http://LENOVO_IP:8000). Add `http://LENOVO_IP:8000/auth/google/callback` to your Google Cloud Console redirect URIs if needed.

Find the Lenovo IP:
```bash
hostname -I | awk '{print $1}'
```

### Telegram
- Open Telegram, find your bot (from BotFather)
- Send a message — it will reply using the agent

---

## 6. Optional: Remote Access

To reach the agent when you're not on the same network:

1. **Tailscale** — Install on Lenovo + phone, use the Tailscale IP
2. **Port forwarding** — Forward port 8000 on your router to the Lenovo (less secure)
3. **Cloudflare Tunnel** — Free tunnel to your home network

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port 8000 in use | `sudo lsof -i :8000` then `kill <PID>` or change port in app.py |
| Telegram not responding | Check `TELEGRAM_BOT_TOKEN` in credentials/.secrets.env |
| Service won't start | `sudo journalctl -u personal-ai-agent -n 50` for logs |
| Can't reach from phone | Ensure firewall allows 8000: `sudo ufw allow 8000` (if using ufw) |

---

## Commands Reference

```bash
# Status
sudo systemctl status personal-ai-agent
sudo systemctl status personal-ai-agent-telegram

# Restart
sudo systemctl restart personal-ai-agent personal-ai-agent-telegram

# Stop
sudo systemctl stop personal-ai-agent personal-ai-agent-telegram

# Logs
tail -f ~/ml-from-scratch/logs/systemd.log
tail -f ~/ml-from-scratch/logs/telegram.log
```

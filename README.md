# 🔁 MN Auto Forward Bot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python"/>
  <img src="https://img.shields.io/badge/Deployed%20On-Koyeb-blueviolet?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Telegram-Userbot%20%7C%20Bot-blue?style=for-the-badge&logo=telegram"/>
  <img src="https://img.shields.io/github/license/MN-BOTS/MN-Auto-Forward-Bot?style=for-the-badge"/>
</p>

A Python-based Telegram auto-forwarding solution supporting **two interchangeable modes**:

| Mode | Library | Source Access | Setup |
|---|---|---|---|
| 🤖 **Userbot** | Telethon (MTProto) | Any public channel — **no membership needed** | API ID + Hash + Session |
| 🔑 **Bot** | python-telegram-bot | Bot must be a **member** of source channels | Bot Token only |

Both modes forward **silently** — no "Forwarded From" header in the target.

---

## ✨ Features

- 🔁 **Silent Forwarding** — Clean copy, no forward header
- 📋 **Multi-Rule Support** — Multiple sources → multiple targets in one config
- 🖼️ **Album Support** — Forwards full media groups/albums intact (userbot mode)
- 🚫 **Skip Terms** — Filter out messages by keyword
- 🔄 **Dual Mode** — Switch between userbot or bot with one env var
- 🐳 **Docker Ready** — One-click deploy on Koyeb
- ☁️ **Cloud Native** — Uses `SESSION_STRING` env var (no local session file needed)
- 🌐 **Health Check** — Optional HTTP endpoint for uptime monitors

---

## 🏗️ Project Structure

```
mnfor-main/
├── main.py                 # Entry point — mode detection & health server
├── config.py               # Config loader & validation
├── forwarder.py            # Shared: rules parser + skip logic
├── modes/
│   ├── userbot_mode.py     # Telethon userbot (reads any channel freely)
│   └── bot_mode.py         # python-telegram-bot polling
├── generate_session.py     # Helper: generate SESSION_STRING locally
├── requirements.txt        # Python dependencies
├── Dockerfile              # For Koyeb deployment
├── .dockerignore
└── .env.example            # Config template
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Mode | Required | Description |
|---|---|---|---|
| `MODE` | Both | ✅ | `userbot` or `bot` |
| `API_ID` | Userbot | ✅ | From [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Userbot | ✅ | From [my.telegram.org](https://my.telegram.org) |
| `SESSION_STRING` | Userbot | ✅* | For cloud/Koyeb (generated locally) |
| `PHONE` | Userbot | ✅* | For local first-run session generation only |
| `BOT_TOKEN` | Bot | ✅ | From [@BotFather](https://t.me/BotFather) |
| `FORWARD_RULES` | Both | ✅ | Forwarding rules (see below) |
| `SKIP_TERMS` | Both | ❌ | Comma-separated words to skip |
| `PORT` | Both | ❌ | Enable health-check HTTP server on this port |
| `LOG_LEVEL` | Both | ❌ | `DEBUG`/`INFO`/`WARNING`/`ERROR` (default: `INFO`) |

*`SESSION_STRING` needed for Koyeb; `PHONE` only for initial local setup.

### FORWARD_RULES Format

```bash
# Single source → single target
FORWARD_RULES=-100111111:-100222222

# Single source → multiple targets
FORWARD_RULES=-100111111:-100222222,-100333333

# Multiple sources → one target
FORWARD_RULES=-100111111,-100222222:-100333333

# Multiple rules (separated by ;)
FORWARD_RULES=-100111111:-100222222;-100444444:-100555555

# Mix of all
FORWARD_RULES=-100111111,-100222222:-100333333;-100444444:-100555555,-100666666
```

> 💡 To get a channel ID, forward any message from it to [@userinfobot](https://t.me/userinfobot)

---

## 🚀 Deployment on Koyeb

### Userbot Mode

#### Step 1 — Get Telegram API credentials

Go to [my.telegram.org](https://my.telegram.org) → **API Development Tools** → create an app.  
Save your `api_id` and `api_hash`.

#### Step 2 — Generate SESSION_STRING (run locally once)

```bash
# Clone the repo
git clone https://github.com/MN-BOTS/MN-Auto-Forward-Bot.git
cd MN-Auto-Forward-Bot

# Install dependencies
pip install telethon python-dotenv

# Fill in API_ID and API_HASH in .env (copy from .env.example)
cp .env.example .env
# Edit .env with your API_ID and API_HASH

# Generate session
python generate_session.py
```

Enter your phone number and the OTP. The script prints your `SESSION_STRING` — **copy it**.

#### Step 3 — Deploy on Koyeb

1. Push your repo to GitHub (no need to push `.env` — it's gitignored)
2. Go to [koyeb.com](https://koyeb.com) → **Create Service**
3. Choose **GitHub** → select your repo → Koyeb auto-detects `Dockerfile`
4. Set these **Environment Variables**:

| Variable | Value |
|---|---|
| `MODE` | `userbot` |
| `API_ID` | Your API ID |
| `API_HASH` | Your API hash |
| `SESSION_STRING` | Output from Step 2 |
| `FORWARD_RULES` | Your rules |
| `SKIP_TERMS` | *(optional)* |

5. Under **Instance**, choose **Eco** (free tier)
6. Set **Service type** to **Worker** (no HTTP port needed)
   - Or **Web Service** if you set `PORT=8080` for health checks
7. Click **Deploy** 🚀

---

### Bot Mode (simpler, no API credentials)

1. Create a bot with [@BotFather](https://t.me/BotFather) and get the token
2. **Add the bot as a member** of each source channel
3. **Add the bot as admin** (with post permission) in each target channel
4. Set env vars on Koyeb:

| Variable | Value |
|---|---|
| `MODE` | `bot` |
| `BOT_TOKEN` | Your bot token |
| `FORWARD_RULES` | Your rules |

> ⚠️ Bot mode limitation: The bot **must be a member** of source channels to receive updates.

---

## 🖥️ Running Locally

```bash
# Clone and install
git clone https://github.com/MN-BOTS/MN-Auto-Forward-Bot.git
cd MN-Auto-Forward-Bot
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your values

# For userbot mode, first generate session (if no SESSION_STRING):
python generate_session.py

# Run
python main.py
```

---

## 🤖 Bot Commands

Both modes respond to these commands in DM:

| Command | Description |
|---|---|
| `/start` | Check if bot/userbot is running |
| `/status` | View rules count, skip terms, token, and mode |

---

## ❓ FAQ

**Q: Does it show "Forwarded From"?**  
No. Userbot uses `drop_author=True`, Bot mode uses `copyMessage`.

**Q: Can the userbot read private channels?**  
Yes — as long as your user account is a **member** of the private channel.

**Q: Can the userbot read public channels without joining?**  
Yes! That's the main advantage over bot mode.

**Q: What about media groups / albums?**  
Userbot mode collects all messages in an album and forwards them together. Bot mode forwards each media item individually (PTB limitation).

**Q: My session expired?**  
Re-run `python generate_session.py` and update `SESSION_STRING` in Koyeb.

**Q: Can I run both modes at the same time?**  
No — set `MODE` to either `userbot` or `bot`. Deploy two separate services if you need both.

---

## 🆘 Support

💬 **[@mnbots_support](https://t.me/mnbots_support)**

---

## ⭐ Star the Repo

If this helped you, please leave a **⭐ star** on GitHub!

---

## 📄 License

[MIT License](LICENSE) — Free to use, modify, and distribute.

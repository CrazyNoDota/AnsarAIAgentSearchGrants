# Deploy on Oracle Cloud Always Free

## 1. Create the VM (one time)

1. Go to https://cloud.oracle.com → **Compute → Instances → Create Instance**
2. Shape: **VM.Standard.A1.Flex** (ARM) — 4 OCPUs + 24 GB RAM (all free)
3. Image: **Canonical Ubuntu 22.04**
4. Add your SSH public key
5. VCN: default; subnet: public; tick **Assign a public IPv4**
6. Click **Create** — wait ~2 min for it to start

## 2. Open port 22 (SSH is already open by default)

No extra ports needed — bot uses outbound connections only.

## 3. SSH in

```bash
ssh ubuntu@<YOUR_VM_PUBLIC_IP>
```

## 4. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker ubuntu
# Log out and back in so the group takes effect
exit
```

## 5. Clone the repo

```bash
ssh ubuntu@<YOUR_VM_PUBLIC_IP>
git clone https://github.com/<your-org>/AnsarAIAgentSearchGrants.git
cd AnsarAIAgentSearchGrants/event-bot
```

## 6. Create .env

```bash
cp .env.example .env
nano .env   # fill in the values below
```

Required values:

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → /newbot |
| `TELEGRAM_ALLOWED_USERS` | @userinfobot → your numeric ID |
| `NVIDIA_API_KEY` | Same key as grants project |
| `DATABASE_PATH` | Leave as `/data/event_bot.db` |
| `HEADLESS` | Leave as `true` |

## 7. Build and start

```bash
docker compose up -d --build
```

First build downloads Playwright + Chromium (~1 GB). Takes 5-10 min.

Check logs:

```bash
docker compose logs -f
```

You should see:
```
event-bot  | Database ready at /data/event_bot.db
event-bot  | Starting polling…
```

## 8. Test

Open Telegram, find your new bot, send `/start`.

## 9. Auto-restart on reboot

Docker Compose `restart: unless-stopped` handles this automatically.

To verify:

```bash
sudo reboot
# wait 1 min, SSH back in
docker ps   # event-bot should be running
```

## Updating the bot

```bash
cd AnsarAIAgentSearchGrants
git pull
cd event-bot
docker compose up -d --build
```

## Useful commands

```bash
# Live logs
docker compose logs -f

# Stop
docker compose down

# Rebuild after code change
docker compose up -d --build --force-recreate

# Shell inside container
docker compose exec event-bot bash

# SQLite browser (inside container)
docker compose exec event-bot python -c "
import asyncio, storage.db as db
db.configure('/data/event_bot.db')
async def main():
    p = await db.get_profile(YOUR_TELEGRAM_ID)
    print(p)
asyncio.run(main())
"
```

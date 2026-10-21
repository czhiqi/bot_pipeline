# Deploying a bot by hand

The web app's **Download bot** button gives you a zip with:

```
engine/  bots/<name>/  run_bot.py  requirements.txt  .env.example  DEPLOY.md  BOT.txt
```

`BOT.txt` records the branch, commit and gate result the zip was built from.

## 1. Install (Windows or Linux, Python 3.11+)

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

## 2. Paper first

Leave `MODE=paper` and run:

```bash
python run_bot.py bots/<name>
```

The bot uses real candles and simulated fills (the same simulator as the backtest). Trades go to `bots/<name>/trades.csv` and logs to `bots/<name>/logs/bot.log`. Run it in paper for at least as many trades as the out-of-sample period suggests before going live.

## 3. Live

In `.env`:

```
MODE=live
ALLOW_LIVE=true
EXCHANGE_API_KEY=...
EXCHANGE_SECRET=...
EXCHANGE_PASSWORD=...     # Bitget passphrase
```

- Use a sub-account and a key with **trade permission only**. Never enable withdrawals.
- On start, the bot sets margin mode and leverage from `config.json` and reads the position from the exchange.
- After every fill it places a reduce-only stop on the exchange. It also checks the stop itself on every poll as a backup.
- The bot only manages its own symbol. Don't trade that symbol by hand on the same account.

## 4. Stop / kill

- `Ctrl+C` stops the bot and leaves the position and exchange stop in place.
- Create a file named `KILL` in `bots/<name>/` to close the position at market and stop.

## 5. Keep it running

Windows: Task Scheduler → "At startup" → `python run_bot.py bots/<name>` with "Start in" set to the folder. Linux: a systemd service with `Restart=always`.

## Repository setup (once, admin)

1. Copy this folder into your GitHub repo (default branch `main`).
2. Edit `.github/CODEOWNERS` with your GitHub username.
3. Settings → Branches → protect `main`: require a pull request, the `gates` status check, and Code Owner review.
4. Settings → Actions → General: "Read repository contents" for the workflow token. Don't add exchange keys as secrets.
5. Commit candle files under `data/` if CI can't download them. Binance blocks some cloud regions; generate them locally with `python -m engine.data fetch …`.

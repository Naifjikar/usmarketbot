
# Jalwe Halal Stock Filter Bot

This Telegram bot checks the Sharia compliance of a stock symbol using data from:
- Chart Idea
- Yaqeen
- Filterna

It replies with a detailed summary and links to the JALWE channels.

## Deployment on Render

### 1. Create a new repository on GitHub
Upload the following files:
- `main.py`
- `requirements.txt`

### 2. Connect GitHub to Render
- Go to [Render.com](https://render.com)
- Click "New" > "Web Service"
- Select your repository

### 3. Set build and start commands
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py`

### 4. Add Environment Variables
Add a new variable:
- `BOT_TOKEN`: (Your bot token from @BotFather)

### 5. Done!
Your bot is now live and will respond to stock symbols sent by users.

### Example usage
Send a message like:
```
AAPL
```

Bot will reply with the Sharia status of the stock.

---

**JALWE Public Channels:**
- Stocks: https://t.me/JalweTrader
- Options: https://t.me/jalweoption
- Education: https://t.me/JalweVip

**Subscribe to private channels:**
https://salla.sa/jalawe/category/AXlzxy

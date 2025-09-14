import os
import hashlib
import json
import logging
import requests
import redis
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

if not TELEGRAM_TOKEN:
    raise ValueError("No TELEGRAM_TOKEN set for the bot!")

CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes

# --- Setup Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Redis Connection ---
try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True  # Decode from bytes to string
    )
    redis_client.ping()
    logger.info("Successfully connected to Redis.")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis: {e}")
    exit(1)


# --- Helper Functions ---
def get_website_hash(url):
    """Fetches a URL and returns a SHA-256 hash of its content."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return hashlib.sha256(response.content).hexdigest()
    except requests.RequestException as e:
        logger.error(f"Could not fetch {url}: {e}")
        return None

# --- Bot Command Handlers ---
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Hi! I am a website monitoring bot. 🤖\n\n"
        "Use `/monitor <URL>` to start watching a site.\n"
        "Use `/list` to see all sites you are watching.\n"
        "Use `/stop <URL>` to stop watching a site."
    )

def monitor(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    try:
        url = context.args[0]
        if not (url.startswith('http://') or url.startswith('https://')):
            update.message.reply_text("Please provide a valid URL starting with http:// or https://")
            return

        initial_hash = get_website_hash(url)
        if initial_hash is None:
            update.message.reply_text(f"Could not fetch the website at {url}. Please check the URL.")
            return

        # Use a Redis hash for each user. Key: "monitoring:{chat_id}"
        redis_key = f"monitoring:{chat_id}"
        redis_client.hset(redis_key, url, initial_hash)

        update.message.reply_text(f"✅ Started monitoring {url}. I'll notify you of any changes!")
        logger.info(f"User {chat_id} started monitoring {url}")

    except (IndexError, ValueError):
        update.message.reply_text("Usage: /monitor <URL>")

def stop(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    try:
        url_to_stop = context.args[0]
        redis_key = f"monitoring:{chat_id}"

        # hdel returns the number of fields that were removed. 1 if it existed, 0 otherwise.
        if redis_client.hdel(redis_key, url_to_stop):
            update.message.reply_text(f"❌ Stopped monitoring {url_to_stop}.")
            logger.info(f"User {chat_id} stopped monitoring {url_to_stop}")
        else:
            update.message.reply_text(f"You are not currently monitoring {url_to_stop}.")

    except (IndexError, ValueError):
        update.message.reply_text("Usage: /stop <URL>")


def list_monitors(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    redis_key = f"monitoring:{chat_id}"
    monitored_urls = redis_client.hkeys(redis_key)

    if monitored_urls:
        message = "You are currently monitoring the following sites:\n"
        for url in monitored_urls:
            message += f"- {url}\n"
        update.message.reply_text(message)
    else:
        update.message.reply_text("You are not monitoring any websites yet. Use /monitor to start.")

# --- Background Checker ---
def check_websites(context: CallbackContext) -> None:
    logger.info("Running scheduled check for website changes...")
    
    # Iterate over all chat_id keys
    for key in redis_client.scan_iter("monitoring:*"):
        chat_id = key.split(':')[1]
        user_urls = redis_client.hgetall(key)

        for url, known_hash in user_urls.items():
            current_hash = get_website_hash(url)
            
            if current_hash is not None and current_hash != known_hash:
                logger.info(f"Change detected for {url} for user {chat_id}")
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 *Change Detected!*\n\nThe website `{url}` has been updated."
                )
                # Update the hash in Redis
                redis_client.hset(key, url, current_hash)

# --- Main Bot Logic ---
def main() -> None:
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("monitor", monitor))
    dispatcher.add_handler(CommandHandler("stop", stop))
    dispatcher.add_handler(CommandHandler("list", list_monitors))

    job_queue = updater.job_queue
    job_queue.run_repeating(check_websites, interval=CHECK_INTERVAL_SECONDS, first=10)

    updater.start_polling()
    logger.info("Bot started polling...")
    updater.idle()

if __name__ == '__main__':
    main()
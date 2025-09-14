import os
import hashlib
import json
import logging
import requests
import time
from threading import Thread
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- Configuration ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("No TELEGRAM_TOKEN set for the bot!")
CHECK_INTERVAL_SECONDS = 60  # Check every 5 minutes
DATA_FILE = "monitoring_data.json"

# --- Setup Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def load_data():
    """Loads the monitoring data from a JSON file."""
    try:
        with open(DATA_FILE, 'r') as f:
            # The keys are chat_id (as strings), so we convert them back to int
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    """Saves the monitoring data to a JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_website_hash(url):
    """Fetches a URL and returns a SHA-256 hash of its content."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return hashlib.sha256(response.content).hexdigest()
    except requests.RequestException as e:
        logger.error(f"Could not fetch {url}: {e}")
        return None

# --- Bot Command Handlers ---

def start(update: Update, context: CallbackContext) -> None:
    """Sends a welcome message when the /start command is issued."""
    update.message.reply_text(
        "Hi! I am a website monitoring bot. 🤖\n\n"
        "Use the command `/monitor <URL>` to start watching a website for changes.\n\n"
        "Example: `/monitor https://example.com`"
    )

def monitor(update: Update, context: CallbackContext) -> None:
    """Adds a URL to the monitoring list for the user."""
    chat_id = update.message.chat_id
    try:
        url = context.args[0]
        if not (url.startswith('http://') or url.startswith('https://')):
            update.message.reply_text("Please provide a valid URL starting with http:// or https://")
            return

        initial_hash = get_website_hash(url)
        if initial_hash is None:
            update.message.reply_text(f"Could not fetch the website at {url}. Please check the URL and try again.")
            return

        data = load_data()
        if chat_id not in data:
            data[chat_id] = {}
        
        data[chat_id][url] = initial_hash
        save_data(data)

        update.message.reply_text(f"✅ Successfully started monitoring {url}. I will notify you of any changes!")
        logger.info(f"User {chat_id} started monitoring {url}")

    except (IndexError, ValueError):
        update.message.reply_text("Usage: /monitor <URL>")

# --- Background Checker ---

def check_websites(context: CallbackContext) -> None:
    """The background job that checks all monitored websites."""
    logger.info("Running scheduled check for website changes...")
    data = load_data()
    updated_data = data.copy() # Work on a copy to avoid issues during iteration

    for chat_id, user_urls in data.items():
        for url, known_hash in user_urls.items():
            current_hash = get_website_hash(url)
            
            # If fetching was successful and hash has changed
            if current_hash is not None and current_hash != known_hash:
                logger.info(f"Change detected for {url} for user {chat_id}")
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 **Change Detected!**\n\nThe website {url} has been updated."
                )
                # Update the hash in our data
                if chat_id in updated_data and url in updated_data[chat_id]:
                    updated_data[chat_id][url] = current_hash
    
    save_data(updated_data)

# --- Main Bot Logic ---

def main() -> None:
    """Start the bot."""
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("monitor", monitor))

    # Add the periodic job
    job_queue = updater.job_queue
    job_queue.run_repeating(check_websites, interval=CHECK_INTERVAL_SECONDS, first=10)

    # Start the Bot
    updater.start_polling()
    logger.info("Bot started polling...")

    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

# bot_helpers.py — shared helpers imported by bot.py and perp_handlers.py
from utils import database as db

def ensure_user(update):
    u = update.effective_user
    return db.upsert_user(u.id, u.username, u.first_name)

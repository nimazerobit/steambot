from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler, ContextTypes, JobQueue

from core.config_loader import CFG, TEXTS
from core.admin_system import show_all_users, admin_userinfo, adminpanel, broadcast, admin_callbacks
from core.main_menu_handler import show_main_menu, main_menu_callbacks
from core.steam_bot_core import show_change_region, send_wishlist_reminders, currency_db_update, show_user_favorites, command_search, change_region_callbacks, steam_core_callbacks, inline_search_games
from core.utils import check_user

# /start & ?start=HASH
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup", "channel"]:
        return
    if not await check_user(update, context):
        return
    
    await show_main_menu(update, context)

async def region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context):
        return
    await show_change_region(update, context, edit=False)

async def developer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context):
        return
    message_id = update.effective_message.message_id
    await update.effective_chat.send_sticker("CAACAgQAAxkBAAEYQ2VoyzUvLPliEpY_GyNMY7xdu6zd-gAC_RoAArthMFIYwE-KUPkN9zYE", reply_to_message_id=message_id)
    await update.effective_chat.send_message(text=TEXTS["dev"].format(version=CFG["VERSION"]), reply_to_message_id=message_id, parse_mode="HTML")

# ——— Global Callbacks ———
async def global_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    # user_id = update.effective_user.id

    # Empty Callback
    if data == "emptycallback":
        return
    
async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Job function for wishlist reminders"""
    try:
        await send_wishlist_reminders(context.bot)
    except Exception as e:
        print(f"Error in reminder job: {e}")

async def currency_db_job(context: ContextTypes.DEFAULT_TYPE):
    """Job function for currency data"""
    try:
        await currency_db_update()
    except Exception as e:
        print(f"Error in currency data job: {e}")

# ——— App bootstrap ———
def main():
    token = CFG["BOT_TOKEN"]
    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("dev", developer))
    app.add_handler(CommandHandler("region", region))
    app.add_handler(CommandHandler(["favorites", "favs", "fav"], show_user_favorites))
    app.add_handler(CommandHandler("search", command_search))
    app.add_handler(CommandHandler("users", show_all_users))
    app.add_handler(CommandHandler("user", admin_userinfo))
    app.add_handler(CommandHandler("adminpanel", adminpanel))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Callbacks
    app.add_handler(CallbackQueryHandler(main_menu_callbacks, pattern=r"^(backtomain|changeregion|help)"))
    app.add_handler(CallbackQueryHandler(change_region_callbacks, pattern=r"^(userregion|closechangeregion)"))
    app.add_handler(CallbackQueryHandler(steam_core_callbacks, pattern=r"^(addfav|rmfav|showfavs|closefavlist|update_currency_data)"))
    app.add_handler(CallbackQueryHandler(global_callbacks, pattern=r"^(emptycallback)$"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r"^(admin_|show_users:|toggle_user_notify|toggle_wishlist_reminder|status_panel|reload_config|reload_texts|adminpanel)"))

    # Inline query
    app.add_handler(InlineQueryHandler(inline_search_games))

    # Any message
    # app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, incoming_message))

    job_queue = app.job_queue
    job_queue.run_repeating(reminder_job, interval=1800, first=10)
    job_queue.run_repeating(currency_db_job, interval=900, first=10)

    print("Bot started")

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()

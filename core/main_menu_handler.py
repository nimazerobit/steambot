from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.config_loader import CFG, TEXTS
from core.steam_bot_core import show_change_region

### --- Main Menu --- ###
def main_menu_keyboard():
    button_text = TEXTS["main_menu"]["buttons"]
    rows = [
        [InlineKeyboardButton(button_text["search_game"], switch_inline_query_current_chat="")],
        [InlineKeyboardButton(button_text["change_region"], callback_data="changeregion")],
        [InlineKeyboardButton(button_text["showfavs"], callback_data="showfavs")],
        [InlineKeyboardButton(button_text["help"], callback_data="help")]
    ]
    return InlineKeyboardMarkup(rows)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    main_menu_text = TEXTS["main_menu"]["title"].format(version=CFG["VERSION"])
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(f'{main_menu_text}', reply_markup=main_menu_keyboard(), parse_mode="HTML")
    else:
        await update.effective_chat.send_message(f'{main_menu_text}', reply_markup=main_menu_keyboard(), parse_mode="HTML")

### --- Main Menu Callbacks --- ###
async def main_menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = update.effective_user.id

    if data == "backtomain":
        await show_main_menu(update, context, edit=True)
        return
    
    elif data == "changeregion":
        await show_change_region(update, context, edit=True)
        return

    elif data == "help":
        await query.edit_message_text(TEXTS["help"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")]]), parse_mode="HTML")
        return

    # elif data == "profile":
    #     user = DBH.get_user(user_id)
    #     links = DBH.get_links(user_id)
    #     now = now_ts()
    #     active_links = sum(1 for L in links if L["enabled"])
    #     txt = TEXTS["profile"].format(
    #         full_name=user["full_name"] or "-",
    #         username=user["username"] or "-",
    #         user_id=user["user_id"],
    #         user_hash=user["user_hash"],
    #         created_at=fmt_ts(user["created_at"]),
    #         created_ago=human_ago(now - user["created_at"]),
    #         last_active=fmt_ts(user["last_active"]),
    #         last_ago=human_ago(now - user["last_active"]),
    #     )
    #     await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")]]), parse_mode="HTML")
    #     return
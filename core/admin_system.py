import asyncio

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.config_loader import DBH, TEXTS, reload_config, reload_texts
from core.utils import check_user, is_admin, is_owner, now_ts, fmt_ts, human_ago
from core.steam_bot_core import load_steam_regions

# Load steam regions
_, COUNTRIES_MAP = load_steam_regions()

# Admin panel settings:
ADMIN_PANEL = {
    "notify_new_user": True,
    "wishlist_reminder": True
}
PAGE_SIZE = 20

### ---------------------------- Admin Panel ---------------------------- ###
def admin_panel_keyboard():
    rows = [
        [
            InlineKeyboardButton(
                TEXTS["admin"]["panel_keyboard"]["new_user_active"] if ADMIN_PANEL["notify_new_user"] else TEXTS["admin"]["panel_keyboard"]["new_user_inactive"],
                callback_data="toggle_user_notify"
            )
        ],
        [
            InlineKeyboardButton(
                TEXTS["admin"]["panel_keyboard"]["wishlist_active"] if ADMIN_PANEL["wishlist_reminder"] else TEXTS["admin"]["panel_keyboard"]["wishlist_inactive"],
                callback_data="toggle_wishlist_reminder"
            )
        ],
        [
            InlineKeyboardButton(TEXTS["admin"]["panel_keyboard"]["update_currency"], callback_data="update_currency_data")
        ],
        [
            InlineKeyboardButton(TEXTS["admin"]["panel_keyboard"]["reload_config"], callback_data="reload_config")
        ],
        [
            InlineKeyboardButton(TEXTS["admin"]["panel_keyboard"]["reload_texts"], callback_data="reload_texts")
        ],
        [
            InlineKeyboardButton(TEXTS["admin"]["panel_keyboard"]["status"], callback_data="status_panel")
        ]
    ]
    return InlineKeyboardMarkup(rows)

def admin_panel_text():
    return TEXTS["admin"]["panel_text"].format(user_notify_status='فعال ✅' if ADMIN_PANEL['notify_new_user'] else 'غیرفعال ❌', 
                                                wishlist_status='فعال ✅' if ADMIN_PANEL['wishlist_reminder'] else 'غیرفعال ❌')

async def adminpanel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context, check_force_join=False):
        return
    if not is_admin(update.effective_user.id):
        return
    await update.effective_chat.send_message(admin_panel_text(), reply_markup=admin_panel_keyboard(), parse_mode="HTML")

### --- Broadcast Command --- ###
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context, check_force_join=False):
        return

    # Check is owner
    if not is_owner(update.effective_user.id):
        return
    
    # If not a reply, show usage help
    if not update.message or not update.message.reply_to_message:
        await update.effective_chat.send_message(TEXTS["admin"]["broadcast"]["message"], parse_mode="HTML")
        return
    
    # Check if broadcasting to all or single user
    target = None
    if context.args:
        key = context.args[0]
        user = DBH.find_user_by_any(key)
        if not user:
            await update.effective_chat.send_message(TEXTS["errors"]["user_notfound"], parse_mode="HTML")
            return
        target = user["user_id"]

    # Get all target chat IDs
    chat_ids = []
    if target:
        chat_ids = [target]
    else:
        with DBH._connect() as con:
            cur = con.cursor()
            # Add all active user IDs
            user_ids = [row[0] for row in cur.execute(
                "SELECT user_id FROM users WHERE banned=0"
            ).fetchall()]
        
        # Merge lists and remove duplicates
        chat_ids = list(set(user_ids))
    
    # Forward message
    message = update.message.reply_to_message
    semaphore = asyncio.Semaphore(20)

    async def send_to_user(chat_id):
        async with semaphore:
            try:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )
                return True
            except Exception:
                return False

    outcomes = await asyncio.gather(*(send_to_user(chat_id) for chat_id in chat_ids))
    success = sum(outcomes)
    failed = len(outcomes) - success
    
    await update.effective_chat.send_message(
        TEXTS["admin"]["broadcast"]["result"].format(success=success, failed=failed),
        parse_mode="HTML"
    )

### --- Admin view list of all users Command --- ###
async def show_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    if not is_owner(update.effective_user.id):
        return

    total = DBH.count_users()
    if total == 0:
        if update.callback_query:
            await update.callback_query.edit_message_text(TEXTS["errors"]["user_notfound"])
        else:
            await update.message.reply_text(TEXTS["errors"]["user_notfound"])
        return

    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, max_page))
    offset = (page - 1) * PAGE_SIZE

    users = DBH.get_users_page(PAGE_SIZE, offset)

    message = (
        f"📊 تعداد کل کاربران: {total}\n"
        f"📄 صفحه {page} از {max_page}\n\n" +
        "\n".join([f"‎🔹<code>{u['user_id']}</code> - {u['full_name'] or 'بدون نام'}" for u in users])
    )

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"show_users:{page-1}"))
    if page < max_page:
        buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"show_users:{page+1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if update.callback_query:
        await update.callback_query.edit_message_text(message[:4096], reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(message[:4096], reply_markup=markup, parse_mode="HTML")

### --- Admin view user information Command --- ###
async def admin_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    if not await check_user(update, context, check_force_join=False):
        return
    # Check is admin or owner
    if not is_admin(update.effective_user.id):
        return
    
    is_edit = update.callback_query is not None
    query = update.callback_query
    row = None

    # Check arguments
    if (not context.args) and is_edit == False:
        await update.effective_chat.send_message(f'<b>{TEXTS["errors"]["invalid_command"]}</b>', parse_mode="HTML")
        return

    # Get user id
    target_user_id = None
    if context.args:
        key = context.args[0]
        row = DBH.find_user_by_any(key)
        if row:
            target_user_id = row["user_id"]
        else:
            await update.effective_chat.send_message(TEXTS["errors"]["user_notfound"], parse_mode="HTML")
            return
    elif is_edit:
        if user_id:
            target_user_id = user_id
            row = DBH.get_user(target_user_id)
            if not row:
                await update.effective_chat.send_message(TEXTS["errors"]["user_notfound"], parse_mode="HTML")
                return
        else:
            await update.effective_chat.send_message(TEXTS["errors"]["user_notfound"], parse_mode="HTML")
            return

    # Get user stats
    text = await generate_userinfo_text(target_user_id)
    banned = row["banned"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ رفع بن" if banned else "🚫 بن",
            callback_data=f"admin_banuser:{row['user_id']}"
        )]
    ])

    if is_edit:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.effective_chat.send_message(text, reply_markup=keyboard, parse_mode="HTML")

# Generate userinfo text from user_id
async def generate_userinfo_text(user_id: int) -> str:
    # Get user stats from DB
    user_stats = DBH.stats_for_user(user_id)
    current_country = COUNTRIES_MAP.get(user_stats["region"], {"name_fa": "نامشخص", "flag": "🏳️"})
    banned = DBH.get_user(user_id)["banned"]
    now = now_ts()
    text = TEXTS["admin"]["user_info"].format(
        user_id=user_id,
        username=user_stats["username"] or "بدون یوزرنیم",
        full_name=user_stats["full_name"] or "بدون نام",
        user_hash=user_stats["user_hash"] or "بدون هش",
        created_at=fmt_ts(user_stats["created_at"]) if user_stats["created_at"] else "-",
        created_ago=human_ago(max(0, now - (user_stats["created_at"] or now))),
        last_active=fmt_ts(user_stats["last_active"]) if user_stats["last_active"] else "-",
        last_ago=human_ago(max(0, now - (user_stats["last_active"] or now))),
        user_region=f"{current_country['name_fa']} {current_country['flag']}",
        status="🚫 بن شده" if banned else "✅ عادی"
    )
    return text

### --- Admin Callbacks --- ###
async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context, check_force_join=False):
        return
    
    query = update.callback_query
    data = query.data or ""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await query.answer(TEXTS["errors"]["access_denied"], show_alert=True)
        return
    
    elif data.startswith("show_users:"):
        page = int(data.split(":")[1])
        await show_all_users(update, context, page=page)
        return
    
    elif data.startswith("admin_banuser:"):
        target_user_id = int(data.split(":")[1])
        user = DBH.get_user(target_user_id)

        # Check ban yourself
        if user_id == target_user_id:
            await query.answer("میخوای خودتو بن کنی 😔", show_alert=True)
            return

        # Check is user available
        if not user:
            await query.answer(TEXTS["errors"]["user_notfound"], show_alert=True)
            return
        
        DBH.set_ban(target_user_id, not user["banned"])
        await query.answer(TEXTS["admin"]["ban_state_changed"], show_alert=True)
        await admin_userinfo(update, context, target_user_id)
        return

    elif data == "toggle_user_notify":
        ADMIN_PANEL["notify_new_user"] = not ADMIN_PANEL["notify_new_user"]
        await query.answer(TEXTS["admin"]["setting_saved"], show_alert=True)

    elif data == "toggle_wishlist_reminder":
        ADMIN_PANEL["wishlist_reminder"] = not ADMIN_PANEL["wishlist_reminder"]
        await query.answer(TEXTS["admin"]["setting_saved"], show_alert=True)

    elif data == "status_panel":
        with DBH._connect() as con:
            cur = con.cursor()
            total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned_users = cur.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
            import datetime
            today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_ts = int(today.timestamp())
            today_active = cur.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (today_ts,)).fetchone()[0]

        await query.edit_message_text(
            TEXTS["admin"]["status_result"].format(total_users=total_users, banned_users=banned_users, today_active=today_active),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(TEXTS["admin"]["backtomenu"], callback_data="adminpanel")]
            ]),
            parse_mode="HTML"
        )
        return
    
    elif data == "reload_config":
        if reload_config():
            await query.answer(TEXTS["admin"]["reload_config"]["success"])
        else:
            await query.answer(TEXTS["admin"]["reload_config"]["error"])
        return
    
    elif data == "reload_texts":
        if reload_texts():
            await query.answer(TEXTS["admin"]["reload_texts"]["success"])
        else:
            await query.answer(TEXTS["admin"]["reload_texts"]["error"])
        return
    
    elif data == "adminpanel":
        await query.edit_message_text(admin_panel_text(), reply_markup=admin_panel_keyboard(), parse_mode="HTML")
        return

    await query.edit_message_text(admin_panel_text(), reply_markup=admin_panel_keyboard(), parse_mode="HTML")
    return

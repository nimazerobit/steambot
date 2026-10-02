import aiohttp
from uuid import uuid4
import random
import time
import asyncio
import aiofiles
import json
from pathlib import Path
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent, InlineQueryResultsButton, CopyTextButton
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from core.config_loader import DBH, TEXTS
from core.utils import to_persian_digits, has_active_private_chat, check_user, get_tehran_shamsi_datetime, now_ts, is_admin

TELEGRAM_CALLBACK_DATA_LIMIT = 64
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_currency_cache = {}
_currency_mtime = None
_search_cache = {}
SEARCH_CACHE_TTL = 30

def add_favorite_callback(app_id: int, app_name: str) -> str:
    prefix = f"addfav:{app_id}:"
    available_bytes = TELEGRAM_CALLBACK_DATA_LIMIT - len(prefix.encode("utf-8"))
    name_bytes = (app_name or "").encode("utf-8")[:max(0, available_bytes)]
    while True:
        try:
            name = name_bytes.decode("utf-8")
            break
        except UnicodeDecodeError:
            name_bytes = name_bytes[:-1]
    return prefix + name

### --- Return Steam Regions --- ###
def load_steam_regions():
    with (PROJECT_ROOT / "config" / "steam_regions.json").open(encoding="utf-8") as f:
        countries = json.load(f)
    countries_map = {c["code"]: c for c in countries}
    return countries, countries_map

# Load steam regions
COUNTRIES, COUNTRIES_MAP = load_steam_regions()
# load currency data
def load_currency_data():
    global _currency_cache, _currency_mtime
    path = PROJECT_ROOT / "config" / "currency_prices.json"
    try:
        mtime = path.stat().st_mtime_ns
        if _currency_mtime == mtime:
            return _currency_cache
        with path.open(encoding="utf-8") as file:
            _currency_cache = json.load(file)
        _currency_mtime = mtime
        return _currency_cache
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

### --- Change Region --- ###
def change_region_keyboard(current_country_code: str):
    rows = []
    temp_row = []

    for country in COUNTRIES:
        is_current = country["code"] == current_country_code
        flag = country["flag"]
        name_fa = country["name_fa"]

        if is_current:
            btn_text = TEXTS["steam"]["change_region"]["button"]["selected"].format(flag=flag, name_fa=name_fa)
        else:
            btn_text = TEXTS["steam"]["change_region"]["button"]["unselected"].format(flag=flag, name_fa=name_fa)

        temp_row.append(
            InlineKeyboardButton(btn_text, callback_data=f"userregion:{country['code']}")
        )

        if len(temp_row) == 2:
            rows.append(temp_row)
            temp_row = []

    if temp_row:
        rows.append(temp_row)

    rows.append(
        [InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")]
    )
    rows.append(
        [InlineKeyboardButton(TEXTS["close_menu"], callback_data="closechangeregion")]
    )
    return InlineKeyboardMarkup(rows)


async def show_change_region(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    current_country_code = DBH.get_user(user_id=update.effective_user.id)["region"]
    current_country = COUNTRIES_MAP.get(current_country_code, {"name_fa": "نامشخص", "flag": "🏳️"})

    change_region_text = TEXTS["steam"]["change_region"]["title"].format(
        current_region=f"{current_country['name_fa']} {current_country['flag']}"
    )

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            change_region_text,
            reply_markup=change_region_keyboard(current_country_code),
            parse_mode="HTML"
        )
    else:
        await update.effective_chat.send_message(
            change_region_text,
            reply_markup=change_region_keyboard(current_country_code),
            parse_mode="HTML"
        )

### --- Change Region Callbacks --- ###
async def change_region_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = update.effective_user.id

    if data.startswith("userregion:"):
        await update.effective_chat.send_action(action=ChatAction.FIND_LOCATION)
        target_country_code = str(data.split(":")[1])
        user = DBH.get_user(user_id)
        country = COUNTRIES_MAP.get(target_country_code, {"name_fa": "نامشخص", "flag": "🏳️"})

        if user["region"] == target_country_code:
            await query.answer(
                TEXTS["steam"]["change_region"]["message"]["region_already_selected"].format(name_fa=country['name_fa'], flag=country['flag']),
                show_alert=True
            )
            return
        
        DBH.set_region(user_id, target_country_code)
        await query.answer(
            TEXTS["steam"]["change_region"]["message"]["region_changed"].format(name_fa=country['name_fa'], flag=country['flag']),
            show_alert=True
        )
        await show_change_region(update, context, edit=True)

    elif data.startswith("closechangeregion"):
        await query.edit_message_text(TEXTS["steam"]["change_region"]["message"]["menu_closed"])

### --- Search Game Handler --- ###
async def fetch_steam_results(query_text: str, cc: str, limit: int = 10):
    cache_key = (query_text.casefold(), cc, limit)
    cached = _search_cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < SEARCH_CACHE_TTL:
        return cached[1]
    params = {
        "term": query_text,
        "cc": cc,
        "l": "english"
    }
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://store.steampowered.com/api/storesearch/", params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except (Exception, aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"[ERROR] Failed to fetch Steam search results: {e}")
        return []

    results = []
    country_info = COUNTRIES_MAP.get(cc, {"name_fa": "نامشخص", "flag": "🏳️"})

    currency_data = load_currency_data()
    for game in data.get("items", [])[:limit]:
        title = game["name"]
        app_id = game["id"]
        url = f"https://store.steampowered.com/app/{app_id}"

        # price & discount
        price_data = game.get("price", {})
        if price_data:
            initial = price_data.get("initial", 0) / 100
            final = price_data.get("final", 0) / 100
            currency = price_data.get("currency", "")
            if initial > final:
                discount_percent = round((1 - (final / initial)) * 100)
                price_text = TEXTS["steam"]["result"]["price"]["with_discount"].format(price=f"{final:.2f}", currency=currency, discount_percent=discount_percent)
            else:
                price_text = TEXTS["steam"]["result"]["price"]["without_discount"].format(price=f"{final:.2f}", currency=currency)
        else:
            price_text = TEXTS["steam"]["result"]["price"]["free_or_unavailable"]

        # determine price in toman
        price_toman = None
        try:
            region_currency_code = country_info.get("currency_code", "usd").lower()
            cur_entry = None
            # prefer final price for conversion; if final is 0 (free), keep None
            if price_data and final > 0 and region_currency_code:
                cur_entry = currency_data.get(region_currency_code)
            if cur_entry and isinstance(cur_entry.get("value"), (int, float, str)):
                # ensure numeric and compute toman value
                rate = float(cur_entry["value"])
                toman_value = float(final) * rate
                # round to nearest integer and format with thousands separator
                toman_int = int(round(toman_value))
                price_toman = format(toman_int, ",")
                price_toman = to_persian_digits(price_toman)
                price_toman += " تومان"
        except Exception:
            price_toman = None

        results.append({
            "app_id": app_id,
            "title": title,
            "price_text": price_text,
            "price_toman": price_toman,
            "url": url,
            "thumb": game.get("tiny_image"),
            "region_text": f"{country_info['name_fa']} {country_info['flag']}"
        })
    _search_cache[cache_key] = (now, results)
    if len(_search_cache) > 256:
        oldest_key = min(_search_cache, key=lambda key: _search_cache[key][0])
        _search_cache.pop(oldest_key, None)
    return results

### --- Inline Search --- ###
async def inline_search_games(update, context):
    query_text = update.inline_query.query.strip()
    if not query_text:
        return

    query_text = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id

    pv_active = await has_active_private_chat(context.bot, user_id)
    user_data = DBH.get_user(user_id)

    if not pv_active or not user_data or not user_data["region"]:
        await context.bot.answer_inline_query(
            update.inline_query.id,
            results=[],
            cache_time=0,
            is_personal=True,
            button=InlineQueryResultsButton(
                text="برای استفاده از ربات کلیک کنید 🤖",
                start_parameter="inline"
            )
        )
        return

    cc = user_data["region"] or "us"
    steam_results = await fetch_steam_results(query_text, cc)

    results = []
    for game in steam_results:
        message = TEXTS["steam"]["result"]["message"].format(title=game['title'], price=game['price_text'], price_toman=game['price_toman'], region=game['region_text'], inquiry_time=get_tehran_shamsi_datetime(), url=game['url'])

        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=game["title"],
                description=f"💵 {game['price_text']}",
                input_message_content=InputTextMessageContent(
                    message,
                    parse_mode="HTML"
                ),
                thumbnail_url=game.get('thumb'),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(TEXTS["steam"]["result"]["add_to_fav"], callback_data=add_favorite_callback(game["app_id"], game["title"]))]
                ])
            )
        )

    await context.bot.answer_inline_query(
        update.inline_query.id,
        results=results,
        cache_time=5
    )

### --- /search Command --- ###
async def command_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            TEXTS["steam"]["result"]["search_command_error"], 
            parse_mode="HTML"
        )
        return

    # searching message
    searching_message = await update.message.reply_text("🔎")

    query_text = " ".join(context.args)
    user_id = update.effective_user.id
    cc = DBH.get_user(user_id)["region"] or "us"

    steam_results = await fetch_steam_results(query_text, cc, limit=1)
    if not steam_results:
        await searching_message.delete()
        await update.message.reply_text(TEXTS["steam"]["result"]["not_found"])
        return

    game = steam_results[0]

    # keyboard
    keyboard = [
        [InlineKeyboardButton(TEXTS["steam"]["result"]["add_to_fav"], callback_data=add_favorite_callback(game["app_id"], game["title"]))]
    ]

    # remove searching message
    await searching_message.delete()

    message = TEXTS["steam"]["result"]["message"].format(title=game['title'], price=game['price_text'], price_toman=game['price_toman'], region=game['region_text'], inquiry_time=get_tehran_shamsi_datetime(), url=game['url'])

    # send result
    await update.message.reply_text(
        text=message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

### --- Show user favorites list --- ###
async def show_user_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, edit: bool = False):
    if update.effective_chat.type not in ["private"]:
        await update.effective_message.reply_text(TEXTS["errors"]["private_message_only"])
        return
    if not await check_user(update, context):
        return
    user_id = update.effective_user.id
    favs = DBH.get_favorites(user_id)
    if not favs:
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(TEXTS["steam"]["favorite"]["empty"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")]]))
        else:
            await update.effective_chat.send_message(TEXTS["steam"]["favorite"]["empty"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")]]))
        return

    PAGE_SIZE = 5
    total = len(favs)
    max_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, max_page))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_favs = favs[start:end]

    msg = f"<b>📂 علاقه‌مندی‌های شما (صفحه {page}/{max_page}):</b>\n\n"
    keyboard = []
    for fav in page_favs:
        app_id = fav[0] if isinstance(fav, (list, tuple)) else fav["app_id"]

        game_name = fav["app_name"] or "نامشخص"

        keyboard.append([
            InlineKeyboardButton(f"🔗 {app_id}", url=f"https://store.steampowered.com/app/{app_id}"),
            InlineKeyboardButton(f"{game_name}", copy_text=CopyTextButton(text=f"{game_name}"))
        ])
        keyboard.append([
            InlineKeyboardButton("🗑️ حذف", callback_data=f"rmfav:{app_id}:{page}")
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"showfavs:{page-1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"showfavs:{page+1}"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(TEXTS["backtomain"], callback_data="backtomain")])
    keyboard.append([InlineKeyboardButton(TEXTS["close_menu"], callback_data="closefavlist")])

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)
    else:
        await update.effective_chat.send_message(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    return

### --- Steam Core Callbacks --- ###
async def steam_core_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = update.effective_user.id

    if data.startswith("addfav:"):
        payload = data.split(":", 1)[1]
        target_app_id, _, app_name = payload.partition(":")
        user = DBH.get_user(user_id)
        if not user:
            await query.answer(TEXTS["steam"]["favorite"]["add_error"], show_alert=True)
            return
        added = DBH.add_favorite(user_id, int(target_app_id), app_name, now_ts())
        if added:
            await query.answer(TEXTS["steam"]["favorite"]["add_success"], show_alert=True)
        else:
            await query.answer(TEXTS["steam"]["favorite"]["add_exist"], show_alert=True)
        return

    elif data.startswith("showfavs"):
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        await show_user_favorites(update, context, page=page, edit=True)
        return

    elif data.startswith("rmfav:"):
        parts = data.split(":")
        if len(parts) < 2:
            await query.answer(TEXTS["steam"]["favorite"]["remove_error"], show_alert=True)
            return
        app_id = int(parts[1])
        removed = DBH.remove_favorite(user_id, app_id)
        if removed:
            await query.answer(TEXTS["steam"]["favorite"]["remove_success"], show_alert=True)
        else:
            await query.answer(TEXTS["steam"]["favorite"]["remove_error"], show_alert=True)
        # Refresh favorites list, keep current page if possible
        page = 1
        if len(parts) > 2 and parts[2].isdigit():
            page = int(parts[2])
        await show_user_favorites(update, context, page=page, edit=True)
        return

    elif data.startswith("closefavlist"):
        await query.edit_message_text(TEXTS["steam"]["favorite"]["menu_closed"])
        return

    elif data == "update_currency_data":
        if not is_admin(user_id):
            await query.answer(TEXTS["errors"]["access_denied"], show_alert=True)
            return
        try:
            asyncio.create_task(currency_db_update())
            await query.answer(TEXTS["steam"]["update_currency_data"], show_alert=True)
        except:
            return
    
# --- Wishlist Reminder System --- #
REMINDER_MESSAGES = [
    "نمیخوای {game_name} رو بخری 😒",
    "عشقم تروخدا {game_name} برام بخر 🥺",
    "مطمئنی نمیخوای{game_name} رو بخری؟؟",
    "گیم {game_name} چشم انتظار تو که بخریش 😌",
    "عزیزم گیم {game_name} به لیستت اضافه کرده بودی رو یادت نره 😉",
    "قربونت بشم نمیخوای یه سر به ما بزنی 🥺😒"
]

REMINDER_INTERVAL_DAYS = 4

async def send_wishlist_reminders(bot):
    now_ts = int(time.time())
    print(f"[Wishlist Reminders] Starting at {now_ts}…")
    
    users = DBH.get_all_users()
    print(f"[Wishlist Reminders] Found {len(users)} users")

    for user in users:
        user_id = user["user_id"]
        try:
            last_reminder = user["last_reminder"] if user["last_reminder"] is not None else 0
        except (KeyError, TypeError):
            last_reminder = 0
            
        print(f"[!] Processing user {user_id}, last reminder: {last_reminder}")

        # Only remind if enough days have passed
        if now_ts - last_reminder < REMINDER_INTERVAL_DAYS * 86400:
            print("[+] User skipped: reminder interval not reached")
            continue
        
        favs = DBH.get_favorites(user_id)
        print(f"[+] Found {len(favs) if favs else 0} favorites")

        if not favs:
            print("[+] User skipped: No Favorites")
            continue

        # Pick a random favorite
        fav = random.choice(favs)
        app_id = fav[0] if isinstance(fav, (list, tuple)) else fav["app_id"]
        game_name = fav["app_name"] or "this game"
        print(f"    Selected game: {game_name} (AppID: {app_id})")

        # Pick a random message
        msg = random.choice(REMINDER_MESSAGES).format(game_name=game_name)
        
        try:
            await bot.send_message(chat_id=user_id, text=msg)
            DBH.update_last_reminder(user_id, now_ts)
            print(f"[+] Sent reminder to {user_id}")
        except Exception as e:
            print(f"[-] Failed to send reminder to {user_id}: {e}")

    print("[Wishlist Reminders] Done\n")

async def currency_db_update():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{} Safari/537.36".format(random.randint(70, 120)),
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{}_{}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{} Safari/605.1.15".format(random.randint(10, 15), random.randint(0, 9), random.randint(12, 17)),
        "Mozilla/5.0 (Linux; Android {}; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{} Mobile Safari/537.36".format(random.randint(8, 13), random.randint(80, 120))
    ]
    accept_headers = [
        "application/json",
        "application/json, text/plain, */*",
        "application/json;q=0.9,*/*;q=0.8"
    ]
    async with aiohttp.ClientSession() as session:
        while True:
            timestamp = int(time.time() * 1000) // 10000
            url = f"https://www.navasan.net/last_currencies.php?_={timestamp}"
            try:
                headers = {
                    "User-Agent": random.choice(user_agents),
                    "Accept": random.choice(accept_headers),
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache"
                }
                # perform non-blocking HTTP request
                try:
                    resp = await session.get(url, headers=headers, timeout=5)
                except Exception as e:
                    # aiohttp may raise for network errors / timeouts
                    print(f"[EXCEPTION] {e}")
                    await asyncio.sleep(6)
                    continue
                content_type = resp.headers.get("Content-Type", "")
                if resp.status == 200 and content_type.startswith("application/json"):
                    try:
                        data = await resp.json()
                        print("[DONE] Currency data received successfully!")
                    except Exception as e:
                        print(f"[EXCEPTION] Failed to parse JSON: {e}")
                        await asyncio.sleep(6)
                        continue
                    # save the latest JSON data to file asynchronously
                    try:
                        async with aiofiles.open(PROJECT_ROOT / "config" / "currency_prices.json", "w", encoding="utf-8") as f:
                            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
                    except Exception as e:
                        print(f"[FILE WRITE ERROR] {e}")
                    break  # exit after first correct response
                else:
                    print(f"[ERROR] Invalid response for currency data -> {resp.status}")
            except Exception as e:
                print(f"[EXCEPTION] {e}")

            await asyncio.sleep(6)

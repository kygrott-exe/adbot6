"""
Telegram Group Broadcaster Bot — simplified per-account management
"""

import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

from config import Config
from account_manager import AccountManager
from broadcaster import Broadcaster
from db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Client(
    "broadcaster_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

db = Database()
account_manager = AccountManager(db)
broadcaster = Broadcaster(db, account_manager)


# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(accounts):
    rows = []
    for acc in accounts:
        is_running = broadcaster.is_running(acc["phone"])
        icon = "🟢" if is_running else ("👤" if acc["active"] else "🔴")
        rows.append([InlineKeyboardButton(
            f"{icon} {acc.get('label', acc['phone'])}",
            callback_data=f"acc:{acc['phone']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Account", callback_data="add_account_start")])
    return InlineKeyboardMarkup(rows)


def kb_account(acc):
    phone = acc["phone"]
    is_running = broadcaster.is_running(phone)
    rows = [
        [InlineKeyboardButton("✏️ Label", callback_data=f"edit_label:{phone}"),
         InlineKeyboardButton("📝 Ad Message", callback_data=f"edit_ad:{phone}")],
        [InlineKeyboardButton("⏱ Send Interval", callback_data=f"edit_interval:{phone}"),
         InlineKeyboardButton("⏸ Cycle Pause", callback_data=f"edit_cycle:{phone}")],
        [InlineKeyboardButton("📢 Log Channel", callback_data=f"edit_log:{phone}")],
    ]
    if is_running:
        rows.append([InlineKeyboardButton("🛑 Stop Ad", callback_data=f"stop_ad:{phone}")])
    else:
        rows.append([InlineKeyboardButton("🚀 Start Ad", callback_data=f"start_ad:{phone}")])
    rows.append([InlineKeyboardButton("🗑 Remove Account", callback_data=f"remove_acc:{phone}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def kb_back(target="menu_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=target)]])


# ── Guards ────────────────────────────────────────────────────────────────────

def is_admin(uid): return uid in Config.ADMIN_IDS

def admin_only(func):
    async def wrapper(client, message: Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Unauthorized.")
            return
        return await func(client, message)
    wrapper.__name__ = func.__name__
    return wrapper

def admin_cb(func):
    async def wrapper(client, cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("⛔ Unauthorized", show_alert=True)
            return
        return await func(client, cb)
    wrapper.__name__ = func.__name__
    return wrapper


# ── Helpers ───────────────────────────────────────────────────────────────────

def _can_edit(target) -> bool:
    """True only if target is a bot-sent message (can be edited)."""
    from pyrogram.types import Message as PyroMsg
    if not isinstance(target, PyroMsg):
        return False
    # Bot messages: from_user is None (channel/bot) or is_bot is True
    return target.from_user is None or getattr(target.from_user, "is_bot", False)


async def show_main(target, accounts=None):
    accounts = accounts or account_manager.list_accounts()
    text = "📣 <b>Broadcaster</b>\n\nYour accounts:"
    if not accounts:
        text = "📣 <b>Broadcaster</b>\n\nNo accounts yet. Add one to get started."
    if _can_edit(target):
        await target.edit_text(text, reply_markup=kb_main(accounts))
    else:
        await target.reply(text, reply_markup=kb_main(accounts))


async def show_account(target, phone, edit=True):
    acc = db.get_account(phone)
    if not acc:
        return
    is_running = broadcaster.is_running(phone)
    ad_preview = (acc.get("ad_message") or "<i>Not set</i>")[:80]
    interval   = acc.get("send_interval", Config.DEFAULT_GROUP_INTERVAL)
    cycle      = acc.get("cycle_pause", Config.DEFAULT_BATCH_INTERVAL)
    log_ch     = acc.get("log_channel") or "<i>Not set</i>"
    groups     = acc.get("group_count", 0)
    text = (
        f"👤 <b>{acc.get('label', phone)}</b>\n"
        f"📱 <code>{phone}</code>\n"
        f"👥 Groups: <b>{groups}</b>\n"
        f"📊 Status: {'🟢 Running' if is_running else '🔴 Stopped'}\n\n"
        f"📝 <b>Ad message:</b>\n{ad_preview}\n\n"
        f"⏱ Send interval: <b>{interval}s</b>\n"
        f"⏸ Cycle pause: <b>{cycle}s</b>\n"
        f"📢 Log channel: {log_ch}"
    )
    if edit and _can_edit(target):
        await target.edit_text(text, reply_markup=kb_account(acc))
    else:
        await target.reply(text, reply_markup=kb_account(acc))


# ── /start ────────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start") & filters.private)
@admin_only
async def cmd_start(client, message: Message):
    await show_main(message)


@bot.on_callback_query(filters.regex("^menu_main$"))
@admin_cb
async def cb_menu_main(client, cb: CallbackQuery):
    await show_main(cb.message)


# ── Account detail ────────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex("^acc:"))
@admin_cb
async def cb_acc_detail(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    await show_account(cb.message, phone)


# ── Add account flow (3 steps) ────────────────────────────────────────────────

@bot.on_callback_query(filters.regex("^add_account_start$"))
@admin_cb
async def cb_add_start(client, cb: CallbackQuery):
    await cb.message.edit_text(
        "➕ <b>Add Account</b>\n\nChoose login method:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 OTP Login", callback_data="login_otp")],
            [InlineKeyboardButton("📂 Session File", callback_data="login_session")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
        ])
    )


@bot.on_callback_query(filters.regex("^login_otp$"))
@admin_cb
async def cb_login_otp(client, cb: CallbackQuery):
    db.set_user_state(cb.from_user.id, "awaiting_phone")
    await cb.message.edit_text(
        "📱 <b>OTP Login — Step 1/3</b>\n\n"
        "Send the phone number with country code:\n"
        "<code>+919876543210</code>",
        reply_markup=kb_back("add_account_start")
    )


@bot.on_callback_query(filters.regex("^login_session$"))
@admin_cb
async def cb_login_session(client, cb: CallbackQuery):
    db.set_user_state(cb.from_user.id, "awaiting_session_file")
    await cb.message.edit_text(
        "📂 <b>Session File Login</b>\n\n"
        "Send your <code>.session</code> file as a document.\n\n"
        "The file name will be used as the phone number identifier — "
        "rename it to your phone number first if needed:\n"
        "<code>+919876543210.session</code>",
        reply_markup=kb_back("add_account_start")
    )


# ── Edit account settings ─────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex("^edit_label:"))
@admin_cb
async def cb_edit_label(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    db.set_user_state(cb.from_user.id, f"awaiting_label:{phone}")
    await cb.message.edit_text(
        f"✏️ <b>Edit Label</b> — <code>{phone}</code>\n\nSend the new name:",
        reply_markup=kb_back(f"acc:{phone}")
    )


@bot.on_callback_query(filters.regex("^edit_ad:"))
@admin_cb
async def cb_edit_ad(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    db.set_user_state(cb.from_user.id, f"awaiting_ad:{phone}")
    await cb.message.edit_text(
        f"📝 <b>Edit Ad Message</b> — <code>{phone}</code>\n\n"
        "Send the ad text to broadcast:",
        reply_markup=kb_back(f"acc:{phone}")
    )


@bot.on_callback_query(filters.regex("^edit_interval:"))
@admin_cb
async def cb_edit_interval(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    db.set_user_state(cb.from_user.id, f"awaiting_interval:{phone}")
    current = db.get_account(phone).get("send_interval", Config.DEFAULT_GROUP_INTERVAL)
    await cb.message.edit_text(
        f"⏱ <b>Send Interval</b> — <code>{phone}</code>\n\n"
        f"Current: <b>{current}s</b>\n\n"
        "Seconds to wait between each group message.\nSend a number:",
        reply_markup=kb_back(f"acc:{phone}")
    )


@bot.on_callback_query(filters.regex("^edit_cycle:"))
@admin_cb
async def cb_edit_cycle(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    db.set_user_state(cb.from_user.id, f"awaiting_cycle:{phone}")
    current = db.get_account(phone).get("cycle_pause", Config.DEFAULT_BATCH_INTERVAL)
    await cb.message.edit_text(
        f"⏸ <b>Cycle Pause</b> — <code>{phone}</code>\n\n"
        f"Current: <b>{current}s</b>\n\n"
        "Seconds to wait after finishing all groups before repeating.\nSend a number:",
        reply_markup=kb_back(f"acc:{phone}")
    )


@bot.on_callback_query(filters.regex("^edit_log:"))
@admin_cb
async def cb_edit_log(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    db.set_user_state(cb.from_user.id, f"awaiting_log:{phone}")
    current = db.get_account(phone).get("log_channel") or "Not set"
    await cb.message.edit_text(
        f"📢 <b>Log Channel</b> — <code>{phone}</code>\n\n"
        f"Current: <code>{current}</code>\n\n"
        "Send channel username or ID:\n<code>@mychannel</code> or <code>-100123456789</code>\n\n"
        "⚠️ Add this bot as admin in that channel first.",
        reply_markup=kb_back(f"acc:{phone}")
    )


# ── Start / Stop ad ───────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex("^start_ad:"))
@admin_cb
async def cb_start_ad(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    acc = db.get_account(phone)
    if not acc:
        await cb.answer("Account not found.", show_alert=True)
        return
    if broadcaster.is_running(phone):
        await cb.answer("Already running!", show_alert=True)
        return
    if not acc.get("ad_message"):
        await cb.answer("⚠️ Set an ad message first.", show_alert=True)
        return
    await cb.message.edit_text(f"⏳ Starting ad for <b>{acc.get('label', phone)}</b>…")
    asyncio.create_task(broadcaster.run_account(bot, phone, cb.message))


@bot.on_callback_query(filters.regex("^stop_ad:"))
@admin_cb
async def cb_stop_ad(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    broadcaster.stop_account(phone)
    await cb.answer("🛑 Stop signal sent.", show_alert=True)
    await show_account(cb.message, phone)


# ── Remove account ────────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex("^remove_acc:"))
@admin_cb
async def cb_remove_acc(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    broadcaster.stop_account(phone)
    await account_manager.remove_account(phone)
    await show_main(cb.message)


# ── Session file upload handler ───────────────────────────────────────────────

@bot.on_message(filters.private & filters.document)
@admin_only
async def handle_document(client, message: Message):
    uid = message.from_user.id
    state = db.get_user_state(uid)
    if state != "awaiting_session_file":
        return

    doc = message.document
    if not doc.file_name.endswith(".session"):
        await message.reply(
            "❌ That doesn't look like a <code>.session</code> file.\n"
            "Send a file ending in <code>.session</code>",
            reply_markup=kb_back("add_account_start")
        )
        return

    db.set_user_state(uid, None)
    # Derive phone from filename: strip .session extension
    fname = doc.file_name[:-8]  # remove .session
    # Normalize: keep only + and digits
    phone = "+" + "".join(c for c in fname if c.isdigit())
    if len(phone) < 8:
        phone = fname  # fallback to raw filename without extension

    msg = await message.reply(f"⏳ Importing session for <code>{phone}</code>…")

    result = await account_manager.import_session(phone, message)
    if result["status"] == "success":
        db.set_user_state(uid, f"awaiting_label_new:{phone}")
        acc = db.get_account(phone)
        await msg.edit_text(
            f"✅ Session imported! Found <b>{acc.get('group_count', 0)}</b> groups.\n\n"
            "<b>Now send a label/name for this account:</b>\n"
            "<code>My Shop</code>"
        )
    else:
        await msg.edit_text(
            f"❌ {result.get('error', 'Failed to import session.')}",
            reply_markup=kb_back("add_account_start")
        )


# ── Universal text input handler ──────────────────────────────────────────────

@bot.on_message(filters.private & filters.text & ~filters.command(["start"]))
@admin_only
async def handle_states(client, message: Message):
    uid = message.from_user.id
    state = db.get_user_state(uid)
    if not state:
        await show_main(message)
        return

    text = message.text.strip()

    # ── Phone number ──
    if state == "awaiting_phone":
        db.set_user_state(uid, None)
        msg = await message.reply(f"🔐 Sending OTP to <code>{text}</code>…")
        result = await account_manager.start_login(text, text, None)
        if result["status"] == "otp_sent":
            db.set_user_state(uid, f"awaiting_otp:{text}")
            await msg.edit_text(
                f"✅ OTP sent to <code>{text}</code>\n\n"
                "<b>Step 2/3 — Enter OTP</b>\n"
                "Send the code you received:"
            )
        else:
            await msg.edit_text(
                f"❌ {result.get('error', 'Unknown error')}",
                reply_markup=kb_back()
            )

    # ── OTP ──
    elif state and state.startswith("awaiting_otp:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        msg = await message.reply("🔄 Verifying OTP…")
        result = await account_manager.complete_login(phone, text)
        if result["status"] == "2fa_required":
            db.set_user_state(uid, f"awaiting_2fa:{phone}")
            await msg.edit_text("🔒 2FA enabled. Send your cloud password:")
        elif result["status"] == "success":
            db.set_user_state(uid, f"awaiting_label_new:{phone}")
            acc = db.get_account(phone)
            await msg.edit_text(
                f"✅ Logged in! Found <b>{acc.get('group_count', 0)}</b> groups.\n\n"
                "<b>Step 3/3 — Account Label</b>\n"
                "Send a name for this account:\n<code>My Shop</code>"
            )
        else:
            await msg.edit_text(f"❌ {result.get('error')}", reply_markup=kb_back())

    # ── 2FA ──
    elif state and state.startswith("awaiting_2fa:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        msg = await message.reply("🔄 Verifying password…")
        result = await account_manager.complete_2fa(phone, text)
        if result["status"] == "success":
            db.set_user_state(uid, f"awaiting_label_new:{phone}")
            acc = db.get_account(phone)
            await msg.edit_text(
                f"✅ Logged in! Found <b>{acc.get('group_count', 0)}</b> groups.\n\n"
                "<b>Step 3/3 — Account Label</b>\n"
                "Send a name for this account:"
            )
        else:
            await msg.edit_text(f"❌ {result.get('error')}", reply_markup=kb_back())

    # ── New account: label ──
    elif state and state.startswith("awaiting_label_new:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        db.update_account_label(phone, text)
        await show_account(message, phone, edit=False)

    # ── Edit label ──
    elif state and state.startswith("awaiting_label:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        db.update_account_label(phone, text)
        await show_account(message, phone, edit=False)

    # ── Edit ad ──
    elif state and state.startswith("awaiting_ad:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        db.update_account_ad(phone, text)
        await message.reply("✅ Ad message saved!", reply_markup=kb_back(f"acc:{phone}"))

    # ── Send interval ──
    elif state and state.startswith("awaiting_interval:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        if not text.isdigit():
            await message.reply("❌ Send a number.", reply_markup=kb_back(f"acc:{phone}"))
            return
        db.update_account_setting(phone, "send_interval", int(text))
        await show_account(message, phone, edit=False)

    # ── Cycle pause ──
    elif state and state.startswith("awaiting_cycle:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        if not text.isdigit():
            await message.reply("❌ Send a number.", reply_markup=kb_back(f"acc:{phone}"))
            return
        db.update_account_setting(phone, "cycle_pause", int(text))
        await show_account(message, phone, edit=False)

    # ── Log channel ──
    elif state and state.startswith("awaiting_log:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        db.update_account_setting(phone, "log_channel", text)
        await show_account(message, phone, edit=False)


if __name__ == "__main__":
    logger.info("Starting Broadcaster Bot…")
    bot.run()

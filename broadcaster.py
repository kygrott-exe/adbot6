"""
Broadcaster — per-account broadcast loops.
Each account runs independently: sends to all groups, pauses, repeats.
"""
import asyncio
import logging
from typing import Dict, Optional

from pyrogram import Client
from pyrogram.types import Message
from telethon.errors import (
    FloodWaitError, ChatWriteForbiddenError, UserBannedInChannelError,
    SlowModeWaitError, ChannelPrivateError,
)

from db import Database
from account_manager import AccountManager
from config import Config

logger = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self, db: Database, account_manager: AccountManager):
        self.db = db
        self.account_manager = account_manager
        self._running: Dict[str, bool] = {}      # phone → running flag
        self._tasks:   Dict[str, asyncio.Task] = {}

    def is_running(self, phone: str) -> bool:
        return self._running.get(phone, False)

    def stop_account(self, phone: str):
        self._running[phone] = False

    async def run_account(self, bot: Client, phone: str, status_msg: Message):
        self._running[phone] = True
        cycle = 0

        try:
            while self._running.get(phone):
                cycle += 1
                acc = self.db.get_account(phone)
                if not acc:
                    break

                label        = acc.get("label", phone)
                ad_text      = acc.get("ad_message")
                interval     = int(acc.get("send_interval") or Config.DEFAULT_GROUP_INTERVAL)
                cycle_pause  = int(acc.get("cycle_pause")   or Config.DEFAULT_BATCH_INTERVAL)
                log_channel  = acc.get("log_channel")

                if not ad_text:
                    await self._edit(status_msg, f"⚠️ No ad message set for <code>{phone}</code>.")
                    break

                client = await self.account_manager.get_client(phone)
                if not client:
                    await self._edit(status_msg, f"❌ Could not connect <code>{phone}</code>.")
                    break

                groups = await self.account_manager.get_groups(phone)
                total  = len(groups)
                sent = failed = flood_waits = 0

                await self._edit(status_msg,
                    f"📡 <b>{label}</b> — Cycle {cycle}\n"
                    f"Sending to <b>{total}</b> groups…"
                )
                await self._log(bot, log_channel,
                    f"🔄 <b>{label}</b> started cycle {cycle} — {total} groups")

                for i, group in enumerate(groups, 1):
                    if not self._running.get(phone):
                        break

                    gid    = group["id"]
                    gtitle = group["title"]

                    try:
                        sent_msg = await client.send_message(gid, ad_text)
                        sent += 1

                        username = group.get("username")
                        if username:
                            link = f"https://t.me/{username}/{sent_msg.id}"
                        else:
                            clean = str(abs(gid))
                            if clean.startswith("100"):
                                clean = clean[3:]
                            link = f"https://t.me/c/{clean}/{sent_msg.id}"

                        self.db.log_broadcast(phone, str(gid), gtitle, "sent", link)
                        await self._log(bot, log_channel,
                            f"✅ <b>{gtitle}</b>\n📎 {link}")

                    except FloodWaitError as e:
                        flood_waits += 1
                        wait = e.seconds
                        self.db.log_broadcast(phone, str(gid), gtitle, "flood_wait",
                                              error=f"FloodWait {wait}s")
                        await self._log(bot, log_channel,
                            f"⏳ FloodWait <b>{wait}s</b> — <b>{gtitle}</b>")
                        await asyncio.sleep(wait + 2)
                        # retry once
                        try:
                            sent_msg = await client.send_message(gid, ad_text)
                            sent += 1
                            username = group.get("username")
                            link = (f"https://t.me/{username}/{sent_msg.id}" if username
                                    else f"https://t.me/c/{str(abs(gid))[3:]}/{sent_msg.id}")
                            self.db.log_broadcast(phone, str(gid), gtitle, "sent", link)
                            await self._log(bot, log_channel,
                                f"✅ Retry OK — <b>{gtitle}</b>\n📎 {link}")
                        except Exception as e2:
                            failed += 1
                            self.db.log_broadcast(phone, str(gid), gtitle, "failed", error=str(e2))
                            await self._log(bot, log_channel,
                                f"❌ Retry failed — <b>{gtitle}</b>\n<code>{e2}</code>")

                    except (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError):
                        failed += 1
                        self.db.log_broadcast(phone, str(gid), gtitle, "failed",
                                              error="No permission")
                        await self._log(bot, log_channel,
                            f"🚫 No permission — <b>{gtitle}</b>")

                    except SlowModeWaitError as e:
                        failed += 1
                        self.db.log_broadcast(phone, str(gid), gtitle, "failed",
                                              error=f"SlowMode {e.seconds}s")
                        await self._log(bot, log_channel,
                            f"🐢 SlowMode {e.seconds}s — <b>{gtitle}</b> (skipped)")

                    except Exception as e:
                        failed += 1
                        self.db.log_broadcast(phone, str(gid), gtitle, "failed", error=str(e))
                        await self._log(bot, log_channel,
                            f"❌ Error — <b>{gtitle}</b>\n<code>{e}</code>")

                    # interval between groups
                    if self._running.get(phone) and i < total:
                        await asyncio.sleep(interval)

                # ── Cycle complete ──
                summary = (
                    f"🏁 <b>{label}</b> — Cycle {cycle} done\n"
                    f"✅ {sent} sent | ❌ {failed} failed | ⏳ {flood_waits} flood waits"
                )
                await self._log(bot, log_channel, summary)

                if not self._running.get(phone):
                    break

                # pause between cycles
                await self._edit(status_msg,
                    f"⏸ <b>{label}</b> — Cycle {cycle} done\n"
                    f"✅ {sent} | ❌ {failed}\n"
                    f"Next cycle in <b>{cycle_pause}s</b>…"
                )
                await asyncio.sleep(cycle_pause)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Broadcaster error for {phone}: {e}")
            await self._log(bot, self.db.get_account(phone or "").get("log_channel"),
                            f"💥 Fatal error for <code>{phone}</code>: {e}")
        finally:
            self._running[phone] = False
            acc = self.db.get_account(phone)
            label = acc.get("label", phone) if acc else phone
            await self._edit(status_msg, f"🛑 <b>{label}</b> — broadcast stopped.")

    async def _edit(self, msg: Optional[Message], text: str):
        if not msg:
            return
        try:
            await msg.edit_text(text)
        except Exception:
            pass

    async def _log(self, bot: Client, log_channel: Optional[str], text: str):
        logger.info(text.replace("<b>", "").replace("</b>", "")
                       .replace("<code>", "").replace("</code>", "")
                       .replace("<i>", "").replace("</i>", ""))
        if not log_channel:
            return
        try:
            await bot.send_message(log_channel, text, disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"Log channel error: {e}")

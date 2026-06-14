"""
Account manager — handles Telethon user-account sessions.
Each account gets its own .session file under /accounts/
"""
import os
import asyncio
import logging
from typing import Dict, Optional

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PasswordHashInvalidError, PhoneNumberInvalidError,
    FloodWaitError
)
from telethon.tl.types import Channel, Chat

from config import Config
from db import Database

logger = logging.getLogger(__name__)
SESSIONS_DIR = Config.SESSIONS_DIR
os.makedirs(SESSIONS_DIR, exist_ok=True)


class AccountManager:
    def __init__(self, db: Database):
        self.db = db
        self._clients: Dict[str, TelegramClient] = {}
        self._pending_login: Dict[str, dict] = {}   # phone → {client, phone_code_hash}

    def _session_path(self, phone: str) -> str:
        safe = phone.replace("+", "").replace(" ", "")
        return os.path.join(SESSIONS_DIR, safe)

    # ── Login flow ────────────────────────────────────────────────────────────
    async def start_login(self, phone: str, label: str, ad_message: Optional[str]) -> dict:
        try:
            client = TelegramClient(self._session_path(phone), Config.API_ID, Config.API_HASH)
            await client.connect()
            result = await client.send_code_request(phone)
            self._pending_login[phone] = {
                "client": client,
                "phone_code_hash": result.phone_code_hash,
                "label": label,
                "ad_message": ad_message,
            }
            return {"status": "otp_sent"}
        except PhoneNumberInvalidError:
            return {"status": "error", "error": "Invalid phone number."}
        except FloodWaitError as e:
            return {"status": "error", "error": f"Flood wait {e.seconds}s. Try later."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def complete_login(self, phone: str, code: str) -> dict:
        pending = self._pending_login.get(phone)
        if not pending:
            return {"status": "error", "error": "No pending login for this number."}
        client: TelegramClient = pending["client"]
        try:
            await client.sign_in(phone, code, phone_code_hash=pending["phone_code_hash"])
            await self._finalize(phone, client, pending)
            return {"status": "success"}
        except SessionPasswordNeededError:
            return {"status": "2fa_required"}
        except PhoneCodeInvalidError:
            return {"status": "error", "error": "Invalid OTP. Try /addaccount again."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def complete_2fa(self, phone: str, password: str) -> dict:
        pending = self._pending_login.get(phone)
        if not pending:
            return {"status": "error", "error": "No pending login."}
        client: TelegramClient = pending["client"]
        try:
            await client.sign_in(password=password)
            await self._finalize(phone, client, pending)
            return {"status": "success"}
        except PasswordHashInvalidError:
            return {"status": "error", "error": "Wrong 2FA password."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _finalize(self, phone: str, client: TelegramClient, pending: dict):
        self._clients[phone] = client
        self.db.add_account(phone, pending["label"], pending.get("ad_message"))
        self._pending_login.pop(phone, None)
        # Count groups immediately
        count = await self._count_groups(client)
        self.db.update_group_count(phone, count)

    # ── Session file import ───────────────────────────────────────────────────
    async def import_session(self, phone: str, message) -> dict:
        """Download a .session file sent as a document and use it directly."""
        try:
            session_path = self._session_path(phone)
            dest = session_path + ".session"

            # Download the file Pyrogram message document to the sessions dir
            await message.download(file_name=dest)

            # Try connecting with it
            client = TelegramClient(session_path, Config.API_ID, Config.API_HASH)
            await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                os.remove(dest)
                return {"status": "error", "error": "Session is expired or invalid."}

            # Get the real phone number from Telegram
            me = await client.get_me()
            real_phone = f"+{me.phone}" if me.phone else phone

            # If phone derived from filename differs from real, rename session file
            if real_phone != phone:
                real_path = self._session_path(real_phone) + ".session"
                os.rename(dest, real_path)
                phone = real_phone
                client = TelegramClient(self._session_path(phone), Config.API_ID, Config.API_HASH)
                await client.connect()

            self._clients[phone] = client
            self.db.add_account(phone, phone, None)
            count = await self._count_groups(client)
            self.db.update_group_count(phone, count)
            return {"status": "success", "phone": phone}

        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Get or reconnect a client ─────────────────────────────────────────────
    async def get_client(self, phone: str) -> Optional[TelegramClient]:
        if phone in self._clients:
            client = self._clients[phone]
            if not client.is_connected():
                await client.connect()
            return client
        # Try to restore from saved session
        session_path = self._session_path(phone)
        if os.path.exists(session_path + ".session"):
            client = TelegramClient(session_path, Config.API_ID, Config.API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                self._clients[phone] = client
                return client
        return None

    # ── Get all groups for an account ─────────────────────────────────────────
    async def get_groups(self, phone: str) -> list:
        client = await self.get_client(phone)
        if not client:
            return []
        groups = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, (Channel, Chat)):
                # Include groups and supergroups; skip channels (broadcast-only)
                is_megagroup = getattr(entity, "megagroup", False)
                is_chat = isinstance(entity, Chat)
                is_channel_broadcast = isinstance(entity, Channel) and not is_megagroup
                if is_chat or is_megagroup:
                    groups.append({
                        "id":    entity.id,
                        "title": dialog.name,
                        "username": getattr(entity, "username", None),
                        "megagroup": is_megagroup,
                    })
        self.db.update_group_count(phone, len(groups))
        return groups

    async def _count_groups(self, client: TelegramClient) -> int:
        count = 0
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, (Channel, Chat)):
                is_megagroup = getattr(entity, "megagroup", False)
                if isinstance(entity, Chat) or is_megagroup:
                    count += 1
        return count

    # ── Remove account ────────────────────────────────────────────────────────
    async def remove_account(self, phone: str):
        client = self._clients.pop(phone, None)
        if client and client.is_connected():
            await client.disconnect()
        # Remove session file
        session_path = self._session_path(phone) + ".session"
        if os.path.exists(session_path):
            os.remove(session_path)
        self.db.remove_account(phone)

    def list_accounts(self) -> list:
        return self.db.list_accounts()

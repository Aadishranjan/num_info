import json
import io
import logging
import os
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import httpx
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ButtonStyle
from pyrogram.errors import UserNotParticipant
from pyrogram.types import Message

load_dotenv(interpolate=False)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+?[0-9][0-9\s-]{6,19}$")
Aadhaar_RE = re.compile(r"(?<!\d)(\d{4})[ -]?(\d{4})[ -]?(\d{4})(?!\d)")
SENSITIVE_KEYS = {"aadhar", "aadhaar", "aadhar_no", "aadhaar_no", "uid", "uidai"}
REMOVED_KEYS = {"owner", "metadata"}


def sanitize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(item): sanitize(child, str(item))
            for item, child in value.items()
            if re.sub(r"[^a-z0-9]", "", str(item).lower()) not in REMOVED_KEYS
        }

    if isinstance(value, list):
        return [sanitize(item, key) for item in value]

    return value


def format_result(data: Any) -> str:
    safe_data = sanitize(data)
    return json.dumps(safe_data, indent=2, ensure_ascii=True, default=str)


def result_file(data: Any, filename: str) -> io.BytesIO:
    document = io.BytesIO(format_result(data).encode("utf-8"))
    document.name = filename
    return document


def json_message(data: Any) -> str:
    return "```json\n" + format_result(data) + "\n```"


def combine_lookup_results(number_data: Any, aadhar_data: Any) -> Any:
    if aadhar_data:
        return {"number_info": number_data, "aadhaar_info": aadhar_data}
    return number_data


def is_no_result_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    status = data.get("status")
    message = data.get("message")
    if status is False and isinstance(message, str):
        normalized = re.sub(r"[^a-z0-9]", "", message.lower())
        if "nonumberdatafound" in normalized or "numberdatafound" in normalized and "no" in normalized:
            return True
    return False


def build_api_url(template: str, placeholder: str, value: str, parameter: str) -> str:
    encoded_value = quote(value, safe="")
    expanded = template.replace("${" + placeholder + "}", encoded_value)
    if "${" + placeholder + "}" in expanded:
        raise ValueError(f"Unresolved API placeholder: {placeholder}")

    parts = urlsplit(expanded)
    if parameter not in parts.query:
        separator = "&" if parts.query else ""
        expanded = urlunsplit(parts._replace(query=parts.query + separator + f"{parameter}={encoded_value}"))
    return expanded


app = Client(
    "number_to_info_bot",
    api_id=int(os.environ["TELEGRAM_API_ID"]),
    api_hash=os.environ["TELEGRAM_API_HASH"],
    bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
)


OWNER_ID = 5927078600
REQUIRED_CHANNEL = "hack4user"
REQUIRED_CHANNEL_URL = "https://t.me/hack4user"


async def has_joined_required_channel(client: Client, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        }
    except UserNotParticipant:
        return False
    except Exception:
        logger.warning("Unable to verify channel membership for user %s", user_id, exc_info=True)
        return False


async def require_channel_join(client: Client, message: Message) -> bool:
    if not message.from_user:
        return False

    if await has_joined_required_channel(client, message.from_user.id):
        return True

    await message.reply_text(
        "You must join @hack4user before using this bot.\n\n"
        "Please join the channel and then send /start again.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📢 Join Channel",
                    url=REQUIRED_CHANNEL_URL,
                    style=ButtonStyle.PRIMARY,
                )
            ]
        ]),
        disable_web_page_preview=True,
    )
    return False


@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message) -> None:
    if not await require_channel_join(client, message):
        return

    await message.reply_text(
        "<b>🕵️‍♂️ NAnonymousDetails_bot</b>\n\n"
        "I can help you find information using osint commands.\n\n"
        "<b<── ── ── ── ── ── ── ── ── ── ── ── ── ── ──\n"
        "🛠 Available Commands:</b>\n\n"
        "<code>/num number</code> - get number information\n"
    ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📢 Update Channel",
                    url=REQUIRED_CHANNEL_URL,
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 Owner",
                    user_id=OWNER_ID,
                    style=ButtonStyle.PRIMARY,
                )
            ]
        ]),
        disable_web_page_preview=True,
    )


@app.on_message(filters.command("num") & filters.private)
async def lookup_number(client: Client, message: Message) -> None:
    if not await require_channel_join(client, message):
        return


    parts = message.text.split(maxsplit=1) if message.text else []
    number = parts[1].strip() if len(parts) == 2 else ""
    if not PHONE_RE.fullmatch(number):
        await message.reply_text("Usage: /num <phone number>")
        return

    first_api = os.getenv("NUM_TO_INFO", "").strip()
    second_api = os.getenv("AADHAR_TO_INFO", "").strip()
    if not first_api:
        await message.reply_text("The number lookup API is not configured.")
        return

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            first_url = build_api_url(first_api, "NUMBER", number, "number")
            first_response = await client.get(first_url)
            first_response.raise_for_status()
            first_data = first_response.json()

            second_data = {}
            if second_api:
                aadhaar = find_aadhaar(first_data)
                if aadhaar:
                    try:
                        second_url = build_api_url(second_api, "AADHAR", aadhaar, "aadhar")
                        second_response = await client.get(second_url)
                        second_response.raise_for_status()
                        second_data = second_response.json()
                    except (httpx.HTTPError, ValueError, KeyError) as error:
                        logger.warning("Aadhaar lookup failed; using number-only data. Error: %s", type(error).__name__)
                        second_data = {}
    except (httpx.HTTPError, ValueError, KeyError) as error:
        logger.warning("Lookup failed: %s", type(error).__name__)
        await message.reply_text("Lookup failed. Please try again later.")
        return

    combined_data = combine_lookup_results(first_data, second_data)
    if is_no_result_payload(first_data):
        await message.reply_text("**No result found**")
        return
    if not combined_data:
        await message.reply_text("**No result found**")
        return

    result_text = json_message(combined_data)
    if len(result_text) > 4096:
        await message.reply_document(result_file(combined_data, "lookup-result.txt"))
        return

    await message.reply_text(result_text)


def find_aadhaar(value: Any) -> str | None:
    """Find an Aadhaar field internally; it is never included in bot output."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"aadhar", "aadhaar", "aadharno", "aadhaarno", "uid"}:
                digits = re.sub(r"\D", "", str(child))
                if len(digits) == 12:
                    return digits
            found = find_aadhaar(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_aadhaar(child)
            if found:
                return found
    return None


if __name__ == "__main__":
    app.run()

"""Pure extraction helpers for Telegram customer interactions."""

from __future__ import annotations

from dataclasses import dataclass

from telethon.tl import types


@dataclass(frozen=True)
class TelegramInteraction:
    contact_id: int
    event_id: str
    kind: str
    text: str = ""
    reply_peer: object | None = None


def new_message_interaction(
    message,
    *,
    chat_id: int,
    is_private: bool,
    reply_peer: object | None = None,
) -> TelegramInteraction | None:
    if not is_private or chat_id is None:
        return None
    text = (getattr(message, "message", None) or "").strip()
    if not text and getattr(message, "media", None) is None:
        return None
    grouped_id = getattr(message, "grouped_id", None)
    if grouped_id is not None:
        event_id = f"album:{grouped_id}"
    else:
        message_id = getattr(message, "id", None)
        if message_id is None:
            return None
        event_id = f"message:{message_id}"
    return TelegramInteraction(chat_id, event_id, "content", text, reply_peer)


def requested_call_interaction(
    update,
    *,
    self_user_id: int | None,
    reply_peer: object | None = None,
) -> TelegramInteraction | None:
    phone_call = getattr(update, "phone_call", None)
    if not isinstance(phone_call, (types.PhoneCallRequested, types.PhoneCallWaiting)):
        return None
    if self_user_id is None or phone_call.participant_id != self_user_id:
        return None
    if phone_call.admin_id == self_user_id:
        return None
    return TelegramInteraction(
        phone_call.admin_id,
        f"call:{phone_call.id}",
        "call",
        reply_peer=reply_peer,
    )

def missed_call_interaction(
    update,
    *,
    self_user_id: int | None,
    reply_peer: object | None = None,
) -> TelegramInteraction | None:
    message = getattr(update, "message", None)
    if not isinstance(message, types.MessageService) or message.out:
        return None
    if not isinstance(message.action, types.MessageActionPhoneCall):
        return None

    if isinstance(message.from_id, types.PeerUser):
        caller_id = message.from_id.user_id
    elif isinstance(message.peer_id, types.PeerUser):
        caller_id = message.peer_id.user_id
    else:
        return None
    if caller_id == self_user_id:
        return None
    return TelegramInteraction(
        caller_id,
        f"call:{message.action.call_id}",
        "call",
        reply_peer=reply_peer,
    )

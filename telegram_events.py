"""Pure extraction helpers for Telegram customer interactions."""

from __future__ import annotations

from dataclasses import dataclass

from telethon import errors, utils
from telethon.tl import functions, types


@dataclass(frozen=True)
class TelegramInteraction:
    contact_id: int
    event_id: str
    kind: str
    text: str = ""
    reply_peer: object | None = None


PHONE_CALL_SUBTYPES = (
    "requested",
    "waiting",
    "accepted",
    "active",
    "discarded",
    "empty",
    "other",
)


def phone_call_subtype(update) -> str:
    """Classify every raw ``UpdatePhoneCall`` transition without client IDs."""

    phone_call = getattr(update, "phone_call", None)
    if isinstance(phone_call, types.PhoneCallRequested):
        return "requested"
    if isinstance(phone_call, types.PhoneCallWaiting):
        return "waiting"
    if isinstance(phone_call, types.PhoneCallAccepted):
        return "accepted"
    if isinstance(phone_call, types.PhoneCall):
        return "active"
    if isinstance(phone_call, types.PhoneCallDiscarded):
        return "discarded"
    if isinstance(phone_call, types.PhoneCallEmpty):
        return "empty"
    return "other"


def missed_call_search_request(not_before):
    """Build the compatible private-history search for recent missed calls."""

    return functions.messages.SearchRequest(
        peer=types.InputPeerEmpty(),
        q="",
        filter=types.InputMessagesFilterPhoneCalls(missed=True),
        min_date=not_before,
        max_date=None,
        offset_id=0,
        add_offset=0,
        limit=30,
        max_id=0,
        min_id=0,
        hash=0,
    )


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


def incoming_call_discard_request(update, *, self_user_id: int | None):
    """Build a refusal request only for a genuine incoming one-to-one call."""

    if requested_call_interaction(update, self_user_id=self_user_id) is None:
        return None
    phone_call = update.phone_call
    call_id = getattr(phone_call, "id", None)
    access_hash = getattr(phone_call, "access_hash", None)
    if not isinstance(call_id, int) or not isinstance(access_hash, int):
        return None
    return functions.phone.DiscardCallRequest(
        peer=types.InputPhoneCall(id=call_id, access_hash=access_hash),
        duration=0,
        reason=types.PhoneCallDiscardReasonBusy(),
        connection_id=0,
        video=bool(getattr(phone_call, "video", False)),
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

    # In a private dialog ``peer_id`` is the remote account.  It is more
    # reliable than ``from_id`` for service messages generated when a call is
    # declined or times out, where Telegram may identify the actor that closed
    # the call rather than the original caller.
    if isinstance(message.peer_id, types.PeerUser):
        caller_id = message.peer_id.user_id
    elif isinstance(message.from_id, types.PeerUser):
        caller_id = message.from_id.user_id
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


async def resolve_reply_peer(
    client,
    update,
    *,
    contact_id: int,
) -> tuple[object, str]:
    """Resolve an input peer using the richest data carried by an update.

    Raw updates are not wrapped in a Telethon ``EventCommon`` instance, so a
    numeric user ID alone may be insufficient when the session has not cached
    its access hash.  Message service updates, however, carry entity data that
    can be converted to an ``InputPeerUser`` without another lookup.
    """

    message = getattr(update, "message", None)
    entities = getattr(update, "_entities", None)
    if not isinstance(entities, dict):
        entities = {}

    if isinstance(message, types.MessageService):
        try:
            if getattr(message, "_client", None) is None:
                message._finish_init(client, entities, None)
            input_chat = getattr(message, "input_chat", None)
            if input_chat is not None:
                return input_chat, "message"
            input_chat = await message.get_input_chat()
            if input_chat is not None:
                return input_chat, "dialog"
        except (AttributeError, TypeError, ValueError, OSError, errors.RPCError):
            pass

    marked_id = utils.get_peer_id(types.PeerUser(contact_id))
    entity = entities.get(marked_id) or entities.get(contact_id)
    if entity is not None:
        try:
            return utils.get_input_peer(entity), "update_entities"
        except (TypeError, ValueError):
            pass

    candidates = []
    if isinstance(message, types.MessageService):
        candidates.append(message.peer_id)
    candidates.extend((types.PeerUser(contact_id), contact_id))
    for candidate in candidates:
        try:
            return await client.get_input_entity(candidate), "cache"
        except (TypeError, ValueError, OSError, errors.RPCError):
            continue

    try:
        async for dialog in client.iter_dialogs(limit=200):
            if getattr(dialog, "id", None) == contact_id:
                input_entity = getattr(dialog, "input_entity", None)
                if input_entity is not None:
                    return input_entity, "dialog"
    except (AttributeError, TypeError, ValueError, OSError, errors.RPCError):
        pass

    # Keep the event retryable.  ``send_response`` will attempt resolution
    # again, and a later MessageService/poll result may provide the access hash.
    return types.PeerUser(contact_id), "unresolved"

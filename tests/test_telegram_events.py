import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from telethon.tl import types

from telegram_events import (
    missed_call_interaction,
    new_message_interaction,
    phone_call_subtype,
    requested_call_interaction,
    resolve_reply_peer,
)


class TelegramEventExtractionTests(unittest.TestCase):
    def test_text_and_every_media_type_are_content(self):
        text = SimpleNamespace(id=1, message="hola", media=None, grouped_id=None)
        voice = SimpleNamespace(id=2, message="", media=object(), grouped_id=None)

        text_result = new_message_interaction(text, chat_id=50, is_private=True)
        voice_result = new_message_interaction(voice, chat_id=50, is_private=True)

        self.assertEqual(("content", "message:1", "hola"), (
            text_result.kind,
            text_result.event_id,
            text_result.text,
        ))
        self.assertEqual(("content", "message:2"), (voice_result.kind, voice_result.event_id))

    def test_album_is_one_deduplicable_interaction(self):
        first = SimpleNamespace(id=10, message="", media=object(), grouped_id=999)
        second = SimpleNamespace(id=11, message="", media=object(), grouped_id=999)

        first_result = new_message_interaction(first, chat_id=50, is_private=True)
        second_result = new_message_interaction(second, chat_id=50, is_private=True)

        self.assertEqual("album:999", first_result.event_id)
        self.assertEqual(first_result.event_id, second_result.event_id)

    def test_groups_and_empty_service_messages_are_ignored(self):
        empty = SimpleNamespace(id=1, message="", media=None, grouped_id=None)
        self.assertIsNone(new_message_interaction(empty, chat_id=1, is_private=True))
        self.assertIsNone(new_message_interaction(empty, chat_id=1, is_private=False))

    def test_only_incoming_phone_call_requested_is_a_call(self):
        protocol = types.PhoneCallProtocol(
            min_layer=65,
            max_layer=100,
            library_versions=[],
            udp_p2p=True,
            udp_reflector=True,
        )
        incoming = types.UpdatePhoneCall(types.PhoneCallRequested(
            id=700,
            access_hash=1,
            date=datetime.now(timezone.utc),
            admin_id=123,
            participant_id=999,
            g_a_hash=b"hash",
            protocol=protocol,
        ))
        outgoing = types.UpdatePhoneCall(types.PhoneCallRequested(
            id=701,
            access_hash=1,
            date=datetime.now(timezone.utc),
            admin_id=999,
            participant_id=123,
            g_a_hash=b"hash",
            protocol=protocol,
        ))

        result = requested_call_interaction(incoming, self_user_id=999)

        self.assertEqual((123, "call:700", "call"), (
            result.contact_id,
            result.event_id,
            result.kind,
        ))
        self.assertIsNone(requested_call_interaction(outgoing, self_user_id=999))
        self.assertIsNone(requested_call_interaction(incoming, self_user_id=555))

    def test_incoming_waiting_call_and_reply_peer_are_supported(self):
        protocol = types.PhoneCallProtocol(
            min_layer=65,
            max_layer=92,
            library_versions=["test"],
        )
        update = types.UpdatePhoneCall(types.PhoneCallWaiting(
            id=701,
            access_hash=2,
            date=None,
            admin_id=123,
            participant_id=999,
            protocol=protocol,
        ))
        peer = types.InputPeerUser(123, 456)

        result = requested_call_interaction(
            update,
            self_user_id=999,
            reply_peer=peer,
        )

        self.assertEqual("call:701", result.event_id)
        self.assertIs(peer, result.reply_peer)

    def test_missed_call_service_uses_same_call_event_id_for_dedupe(self):
        service = types.MessageService(
            id=80,
            peer_id=types.PeerUser(123),
            from_id=types.PeerUser(123),
            out=False,
            action=types.MessageActionPhoneCall(call_id=700),
        )
        update = types.UpdateNewMessage(message=service, pts=1, pts_count=1)

        result = missed_call_interaction(update, self_user_id=999)

        self.assertEqual((123, "call:700", "call"), (
            result.contact_id,
            result.event_id,
            result.kind,
        ))

    def test_missed_call_uses_private_dialog_peer_before_service_actor(self):
        service = types.MessageService(
            id=81,
            peer_id=types.PeerUser(123),
            from_id=types.PeerUser(999),
            out=False,
            action=types.MessageActionPhoneCall(call_id=701),
        )
        result = missed_call_interaction(
            types.UpdateNewMessage(message=service, pts=1, pts_count=1),
            self_user_id=999,
        )
        self.assertEqual(123, result.contact_id)

    def test_phone_call_terminal_subtype_is_not_collapsed_to_other(self):
        discarded = types.UpdatePhoneCall(types.PhoneCallDiscarded(id=900))
        empty = types.UpdatePhoneCall(types.PhoneCallEmpty(id=901))
        self.assertEqual("discarded", phone_call_subtype(discarded))
        self.assertEqual("empty", phone_call_subtype(empty))

    def test_reply_peer_uses_entities_carried_by_raw_update(self):
        user = types.User(id=123, access_hash=456, first_name="Caller")
        update = SimpleNamespace(_entities={123: user})
        peer, source = asyncio.run(
            resolve_reply_peer(object(), update, contact_id=123)
        )
        self.assertIsInstance(peer, types.InputPeerUser)
        self.assertEqual((123, 456), (peer.user_id, peer.access_hash))
        self.assertEqual("update_entities", source)


if __name__ == "__main__":
    unittest.main()

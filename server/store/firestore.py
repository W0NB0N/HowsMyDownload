"""Firestore implementation of BasePairingStore."""

import asyncio
import logging
from datetime import timedelta

import firebase_admin
from firebase_admin import firestore
from server.store.base import BasePairingStore, PairingRecord, utc_now

logger = logging.getLogger("notifs.store.firestore")


class FirestorePairingStore(BasePairingStore):
    """Pairing store backed by Google Cloud Firestore."""

    def __init__(self, collection_name: str = "pairings") -> None:
        self.collection_name = collection_name
        self._db = None

    def _get_db(self):
        if self._db is None:
            if not firebase_admin._apps:
                raise RuntimeError("Firebase Admin SDK not initialized.")
            self._db = firestore.client()
        return self._db

    async def create_pairing(
        self,
        pairing_id: str,
        code: str,
        secret_hash: str,
        pc_name: str,
        expires_in_sec: int = 300,
    ) -> PairingRecord:
        now = utc_now()
        record = PairingRecord(
            pairing_id=pairing_id,
            code=code.upper(),
            secret_hash=secret_hash,
            pc_name=pc_name,
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in_sec),
            claim_attempts=0,
            is_claimed=False,
        )

        def _sync_create():
            db = self._get_db()
            doc_ref = db.collection(self.collection_name).document(pairing_id)
            doc_ref.set(record.model_dump(mode="json"))

        await asyncio.to_thread(_sync_create)
        return record

    async def get_pairing(self, pairing_id: str) -> PairingRecord | None:
        def _sync_get():
            db = self._get_db()
            doc = db.collection(self.collection_name).document(pairing_id).get()
            if doc.exists:
                return PairingRecord.model_validate(doc.to_dict())
            return None

        return await asyncio.to_thread(_sync_get)

    async def get_pairing_by_code(self, code: str) -> PairingRecord | None:
        def _sync_get():
            db = self._get_db()
            query = (
                db.collection(self.collection_name)
                .where("code", "==", code.upper())
                .limit(1)
                .get()
            )
            for doc in query:
                return PairingRecord.model_validate(doc.to_dict())
            return None

        return await asyncio.to_thread(_sync_get)

    async def get_pairing_by_secret_hash(self, secret_hash: str) -> PairingRecord | None:
        def _sync_get():
            db = self._get_db()
            query = (
                db.collection(self.collection_name)
                .where("secret_hash", "==", secret_hash)
                .limit(1)
                .get()
            )
            for doc in query:
                return PairingRecord.model_validate(doc.to_dict())
            return None

        return await asyncio.to_thread(_sync_get)

    async def claim_pairing(self, code: str, fcm_token: str) -> PairingRecord | None:
        def _sync_claim():
            db = self._get_db()
            query = (
                db.collection(self.collection_name)
                .where("code", "==", code.upper())
                .limit(1)
                .get()
            )

            for doc in query:
                record = PairingRecord.model_validate(doc.to_dict())
                if record.is_expired or record.claim_attempts >= 5 or record.is_claimed:
                    doc.reference.update({"claim_attempts": record.claim_attempts + 1})
                    return None

                record.fcm_token = fcm_token
                record.is_claimed = True
                record.claimed_at = utc_now()
                record.claim_attempts += 1

                doc.reference.update(record.model_dump(mode="json"))
                return record
            return None

        return await asyncio.to_thread(_sync_claim)

    async def delete_pairing(self, pairing_id: str) -> bool:
        def _sync_delete():
            db = self._get_db()
            doc_ref = db.collection(self.collection_name).document(pairing_id)
            if doc_ref.get().exists:
                doc_ref.delete()
                return True
            return False

        return await asyncio.to_thread(_sync_delete)

    async def update_fcm_token(self, pairing_id: str, fcm_token: str) -> bool:
        def _sync_update():
            db = self._get_db()
            doc_ref = db.collection(self.collection_name).document(pairing_id)
            doc = doc_ref.get()
            if doc.exists:
                doc_ref.update({"fcm_token": fcm_token})
                return True
            return False

        return await asyncio.to_thread(_sync_update)

    async def rotate_secret(self, pairing_id: str, new_secret_hash: str) -> bool:
        def _sync_rotate():
            db = self._get_db()
            doc_ref = db.collection(self.collection_name).document(pairing_id)
            doc = doc_ref.get()
            if doc.exists:
                doc_ref.update({"secret_hash": new_secret_hash})
                return True
            return False

        return await asyncio.to_thread(_sync_rotate)

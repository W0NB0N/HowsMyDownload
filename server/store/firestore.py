"""Firestore implementation of BasePairingStore."""

import asyncio
import logging
from datetime import timedelta

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore import transactional

from server.store.base import MAX_CLAIM_ATTEMPTS, BasePairingStore, PairingRecord, utc_now

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

    async def claim_pairing(
        self,
        code: str,
        fcm_token: str,
        device_secret_hash: str,
    ) -> PairingRecord | None:
        def _sync_claim():
            db = self._get_db()
            query = (
                db.collection(self.collection_name)
                .where("code", "==", code.upper())
                .limit(1)
            )

            # Read-check-write inside a transaction so two concurrent claims of the same
            # code cannot both succeed and the attempt counter cannot lose increments.
            @transactional
            def _claim_in_txn(txn):
                for doc in txn.get(query):
                    record = PairingRecord.model_validate(doc.to_dict())
                    record.claim_attempts += 1
                    if (
                        record.is_expired
                        or record.is_claimed
                        or record.claim_attempts > MAX_CLAIM_ATTEMPTS
                    ):
                        txn.update(doc.reference, {"claim_attempts": record.claim_attempts})
                        return None

                    record.fcm_token = fcm_token
                    record.device_secret_hash = device_secret_hash
                    record.is_claimed = True
                    record.claimed_at = utc_now()
                    txn.update(doc.reference, record.model_dump(mode="json"))
                    return record
                return None

            return _claim_in_txn(db.transaction())

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

"""Startup configuration must fail loudly instead of silently degrading."""

from unittest.mock import patch

import pytest

from server import main
from server.store.firestore import FirestorePairingStore
from server.store.memory import InMemoryPairingStore


def test_memory_store(monkeypatch):
    monkeypatch.setattr(main.settings, "STORE_TYPE", "memory")
    assert isinstance(main.build_pairing_store(), InMemoryPairingStore)


def test_firestore_without_credentials_refuses_to_start(monkeypatch):
    """Previously this fell back to an in-memory store, silently losing pairings on restart."""
    monkeypatch.setattr(main.settings, "STORE_TYPE", "firestore")
    with (
        patch("server.main.init_firebase", return_value=False),
        pytest.raises(RuntimeError, match="Firebase could not be initialized"),
    ):
        main.build_pairing_store()


def test_firestore_with_credentials(monkeypatch):
    monkeypatch.setattr(main.settings, "STORE_TYPE", "firestore")
    with patch("server.main.init_firebase", return_value=True):
        assert isinstance(main.build_pairing_store(), FirestorePairingStore)


def test_unknown_store_type_refuses_to_start(monkeypatch):
    monkeypatch.setattr(main.settings, "STORE_TYPE", "sqlite")
    with pytest.raises(RuntimeError, match="Unsupported STORE_TYPE"):
        main.build_pairing_store()


def test_lifespan_wires_throttler_epoch(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main.settings, "STORE_TYPE", "memory")
    monkeypatch.setattr(main.settings, "NOTIFIER_TYPE", "console")
    app = main.create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        state = client.app.state
        assert state.tracker_manager.throttler is state.throttler
        assert state.tracker_manager.epoch == state.throttler.epoch > 0

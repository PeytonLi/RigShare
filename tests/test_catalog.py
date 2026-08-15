from __future__ import annotations

from pathlib import Path

from app.catalog import load_weights, write_weights


def test_write_weights_roundtrip(tmp_path: Path, monkeypatch) -> None:
    from app import catalog

    path = tmp_path / "catalog_weights.json"
    monkeypatch.setattr(catalog, "WEIGHTS_PATH", path)
    write_weights({"hdmi": 4.0, "usbc_charger": 5.0})
    loaded = load_weights()
    assert loaded["hdmi"] == 4.0
    assert loaded["usbc_charger"] == 5.0
    assert path.is_file()

from __future__ import annotations

import pytest

from tempest.metar import normalize_metar


def test_normalize_metar_maps_core_fields() -> None:
    payload = {
        "icaoId": "KLAF",
        "rawOb": "KLAF 011654Z 22012G20KT 10SM FEW025 08/M02 A2992",
        "obsTime": "2026-03-01T16:54:00Z",
        "name": "Purdue University Airport",
        "lat": 40.4123,
        "lon": -86.9369,
        "elev": 184,
        "fltCat": "VFR",
        "wdir": 220,
        "wspd": 12,
        "wgst": 20,
        "visib": 10,
        "temp": 8,
        "dewp": -2,
        "altim": 29.92,
        "wxString": "",
    }

    record = normalize_metar(payload)

    assert record.icao_id == "KLAF"
    assert "22012G20KT" in record.raw_text
    assert record.wind_speed_kt == 12
    assert record.altimeter_in_hg == 29.92
    assert record.source_payload["name"] == "Purdue University Airport"


def test_normalize_metar_requires_raw_text() -> None:
    payload = {"icaoId": "KLAF"}

    with pytest.raises(ValueError, match="raw METAR"):
        normalize_metar(payload)


def test_normalize_metar_converts_altim_hpa_to_inhg() -> None:
    payload = {
        "icaoId": "KLAF",
        "rawOb": "KLAF 040202Z AUTO 06005KT 5SM -RA BR FEW007 OVC035 05/04 A3014",
        "altim": 1020.7,
    }

    record = normalize_metar(payload)
    assert record.altimeter_in_hg == 30.14

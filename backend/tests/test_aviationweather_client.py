from __future__ import annotations

from urllib.request import Request

from tempest.aviationweather_client import AviationWeatherClient


def test_metar_fetch_accepts_raw_text_when_json_parse_fails(monkeypatch) -> None:
    client = AviationWeatherClient(user_agent="TempestTest")

    def read_raw_metar(self: AviationWeatherClient, request: Request, station: str) -> str:
        assert station == "KCIC"
        return "KCIC 090447Z AUTO 18005KT 10SM BKN050 18/12 A2998"

    monkeypatch.setattr(AviationWeatherClient, "_read_with_retries", read_raw_metar)

    assert client.fetch_latest_metar_json("KCIC") == [
        {
            "icaoId": "KCIC",
            "rawOb": "KCIC 090447Z AUTO 18005KT 10SM BKN050 18/12 A2998",
        }
    ]


def test_metar_fetch_treats_empty_body_as_no_records(monkeypatch) -> None:
    client = AviationWeatherClient(user_agent="TempestTest")

    def read_empty_body(self: AviationWeatherClient, request: Request, station: str) -> str:
        return ""

    monkeypatch.setattr(AviationWeatherClient, "_read_with_retries", read_empty_body)

    assert client.fetch_latest_metar_json("KCIC") == []

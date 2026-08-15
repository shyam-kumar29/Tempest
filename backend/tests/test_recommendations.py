from __future__ import annotations

from datetime import UTC, datetime

from tempest.recommendations import (
    apply_ai_downgrade,
    destination_candidates,
    recommendation_score,
)
from tempest.route import AirportIndexEntry, RoutePoint


def test_destination_candidates_filter_and_prefer_weather_stations() -> None:
    candidates = destination_candidates(
        home=RoutePoint("KAAA", "Home", 0.0, 0.0),
        airport_index=[
            AirportIndexEntry("KAAA", "Home", 0.0, 0.0, "METAR|TAF"),
            AirportIndexEntry("KMTA", "Both", 0.0, 1.0, "METAR|TAF"),
            AirportIndexEntry("KMET", "Metar", 0.0, 0.5, "METAR"),
            AirportIndexEntry("KTAF", "Taf", 0.0, 0.25, "TAF"),
            AirportIndexEntry("KNON", "No Weather", 0.0, 0.2, "airport"),
            AirportIndexEntry("KFAR", "Far", 0.0, 4.0, "METAR|TAF"),
        ],
        radius_nm=100.0,
        groundspeed_kt=100.0,
        planned_departure=datetime(2026, 4, 4, 18, tzinfo=UTC),
        max_candidates=10,
    )

    assert [candidate.airport.icao_id for candidate in candidates] == ["KMTA", "KMET", "KTAF"]
    assert candidates[0].estimated_arrival > datetime(2026, 4, 4, 18, tzinfo=UTC)


def test_recommendation_score_sorts_good_weather_ahead() -> None:
    score = recommendation_score(
        {
            "distance_from_home_nm": 50,
            "sources": {"metar": "api", "taf": "api", "airport": "api"},
            "decision": {
                "decision": "go",
                "metar_summary": {"visibility_sm": 10, "ceiling_ft_agl": 6000, "wind_speed_kt": 8},
                "taf_summary": {"evaluated_periods": []},
                "best_runway": {"runway_id": "22"},
            },
        }
    )

    assert score["severity"] == 0
    assert score["data_quality"] == 5
    assert score["margin"] > 0
    assert score["sort_key"][0] == 0


def test_apply_ai_downgrade_never_upgrades() -> None:
    assert apply_ai_downgrade(base_decision="go", ai_decision="caution") == "caution"
    assert apply_ai_downgrade(base_decision="caution", ai_decision="no-go") == "no-go"
    assert apply_ai_downgrade(base_decision="no-go", ai_decision="go") == "no-go"
    assert apply_ai_downgrade(base_decision="caution", ai_decision="go") == "caution"
    assert apply_ai_downgrade(base_decision="go", ai_decision="invalid") == "go"

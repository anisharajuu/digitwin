"""HTTP and WebSocket contract tests, driven through the real app."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

API = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_healthz_reports_twin_vitals(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["assets"] == 10
    assert body["series"] > 0
    assert body["tick"] >= 1


def test_plant_registry_is_complete(client):
    body = client.get(f"{API}/plant").json()
    assert body["plant"]["name"] == "Aurora Works"
    assert len(body["areas"]) == 5
    assert len(body["assets"]) == 10

    areas = {a["id"] for a in body["areas"]}
    for asset in body["assets"]:
        assert asset["area"] in areas  # no orphaned assets
        assert asset["tags"]  # every asset publishes something
        assert len(asset["position"]) == 3  # placeable in the 3D view
        for downstream in asset["feeds"]:
            assert any(a["id"] == downstream for a in body["assets"])


def test_frame_covers_every_asset(client):
    plant = client.get(f"{API}/plant").json()
    frame = client.get(f"{API}/frame").json()
    assert set(frame["assets"]) == {a["id"] for a in plant["assets"]}
    assert 0.0 < frame["kpis"]["oee"] <= 1.0


def test_asset_detail_exposes_wear_and_injectable_faults(client):
    body = client.get(f"{API}/assets/P-101A").json()
    assert body["info"]["kind"] == "centrifugal_pump"
    modes = {m["name"] for m in body["degradation_detail"]}
    assert modes == {"impeller_wear", "bearing_wear"}
    assert {f["id"] for f in body["injectable_faults"]} == {"bearing_spall", "impeller_erosion"}
    for mode in body["degradation_detail"]:
        assert mode["action"] and mode["cost_eur"] > 0


def test_unknown_asset_is_a_404(client):
    assert client.get(f"{API}/assets/NOPE-1").status_code == 404


def test_telemetry_carries_the_model_overlay(client):
    body = client.get(
        f"{API}/assets/P-101A/telemetry", params={"tags": "flow_m3h", "points": 10}
    ).json()
    assert len(body) == 1
    series = body[0]
    assert series["tag"] == "flow_m3h"
    assert series["spec"]["unit"] == "m3/h"
    assert len(series["points"]) == len(series["expected"]) > 0


def test_telemetry_rejects_an_unknown_tag(client):
    r = client.get(f"{API}/assets/P-101A/telemetry", params={"tags": "not_a_tag"})
    assert r.status_code == 404


def test_telemetry_defaults_to_every_tag(client):
    body = client.get(f"{API}/assets/HX-201/telemetry", params={"points": 5}).json()
    assert len(body) == 9


def test_fault_catalogue_is_typed_by_asset_kind(client):
    catalogue = client.get(f"{API}/faults/catalogue").json()
    assert len(catalogue) >= 10
    pump_faults = [f for f in catalogue if "centrifugal_pump" in f["kinds"]]
    assert {f["id"] for f in pump_faults} == {"bearing_spall", "impeller_erosion"}
    assert all(f["description"] and f["symptom"] for f in catalogue)


def test_fault_lifecycle(client):
    created = client.post(
        f"{API}/faults",
        json={"asset_id": "CMP-501", "mode": "filter_blockage", "severity": 0.5, "ramp_hours": 2.0},
    )
    assert created.status_code == 200
    fault_id = created.json()["id"]
    assert any(f["id"] == fault_id for f in client.get(f"{API}/faults").json())

    assert client.delete(f"{API}/faults/{fault_id}").status_code == 200
    assert all(f["id"] != fault_id for f in client.get(f"{API}/faults").json())
    assert client.delete(f"{API}/faults/{fault_id}").status_code == 404


def test_injecting_onto_an_unknown_asset_is_a_404(client):
    r = client.post(
        f"{API}/faults",
        json={"asset_id": "NOPE-1", "mode": "bearing_spall", "severity": 0.5, "ramp_hours": 1.0},
    )
    assert r.status_code == 404


def test_fault_severity_is_validated(client):
    r = client.post(
        f"{API}/faults",
        json={"asset_id": "P-101A", "mode": "bearing_spall", "severity": 9.0, "ramp_hours": 1.0},
    )
    assert r.status_code == 422


def test_work_orders_are_risk_ranked(client):
    orders = client.get(f"{API}/maintenance/work-orders").json()
    scores = [o["risk_score"] for o in orders]
    assert scores == sorted(scores, reverse=True)
    for order in orders:
        assert order["action"] and order["rationale"]
        assert order["estimated_cost_eur"] > 0


def test_maintenance_can_be_performed_and_is_scoped(client):
    body = client.post(
        f"{API}/maintenance/perform", json={"asset_id": "CHL-202", "mode": "condenser_fouling"}
    ).json()
    assert body["restored"] == ["condenser_fouling"]
    assert body["downtime_h"] > 0

    detail = client.get(f"{API}/assets/CHL-202").json()
    fouling = [m for m in detail["degradation_detail"] if m["name"] == "condenser_fouling"][0]
    assert fouling["level"] == 0.0


def test_maintenance_on_an_unknown_mode_is_a_404(client):
    r = client.post(f"{API}/maintenance/perform", json={"asset_id": "P-101A", "mode": "nope"})
    assert r.status_code == 404


def test_alerts_endpoint_and_acknowledgement(client):
    assert client.get(f"{API}/alerts").status_code == 200
    assert client.post(f"{API}/alerts/alr_nonexistent/acknowledge").status_code == 404


def test_scenario_simulation_returns_a_business_case(client):
    body = client.post(
        f"{API}/scenarios/simulate",
        json={
            "name": "Clean the exchanger",
            "horizon_days": 30,
            "changes": [{"asset_id": "HX-201", "parameter": "maintain"}],
        },
    ).json()
    assert body["baseline"]["label"] == "Do nothing"
    assert body["proposed"]["series"]
    assert body["verdict"]
    assert "delta_cost_eur" in body
    assert body["compute_ms"] > 0


def test_scenario_horizon_is_bounded(client):
    r = client.post(f"{API}/scenarios/simulate", json={"horizon_days": 9_999})
    assert r.status_code == 422


def test_stream_pushes_frames(client):
    with client.websocket_connect(f"{API}/stream") as ws:
        first = json.loads(ws.receive_text())
        assert first["tick"] >= 1
        assert len(first["assets"]) == 10
        assert "kpis" in first and "alerts" in first


def test_openapi_documents_every_route(client):
    spec = client.get("/openapi.json").json()
    assert len(spec["paths"]) >= 15
    assert f"{API}/scenarios/simulate" in spec["paths"]

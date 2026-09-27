# API reference

Base path `/api/v1`. Interactive OpenAPI docs are served at `/docs` when the
service is running.

## Plant and state

### `GET /plant`
The as-designed registry: plant metadata, areas, and every asset with its
nameplate data, 3D position, topology (`feeds`), tag specifications and
degradation modes. Static — fetch once and cache.

### `GET /frame`
The current tick. Identical in shape to what the WebSocket pushes.

```jsonc
{
  "tick": 412,
  "sim_time": 27120.0,
  "assets": {
    "P-101A": {
      "state": "degraded",
      "health": 71.4,
      "values":      { "flow_m3h": 104.2, "vibration_mms": 2.31, "...": 0 },
      "residuals":   { "flow_m3h": { "observed": 104.2, "expected": 118.0,
                                     "residual": -13.8, "z": -21.4,
                                     "breached": true } },
      "degradation": { "impeller_wear": 0.38, "bearing_wear": 0.12 },
      "rul": [ { "mode": "impeller_wear", "hours_remaining": 52.4,
                 "confidence": 0.81, "trend_per_day": 0.284 } ],
      "open_alerts": 4
    }
  },
  "kpis":   { "oee": 0.79, "throughput_tph": 104.9, "power_kw": 418.2, "...": 0 },
  "alerts": [ /* worst first */ ]
}
```

### `GET /assets` · `GET /assets/{id}`
List, or one asset in full: nameplate, live snapshot, per-mode wear detail with
the action and cost to clear it, the faults injectable into that asset kind,
and anything currently active.

### `GET /assets/{id}/telemetry`
`?tags=flow_m3h,vibration_mms&points=360`

Recent samples for one or more tags, each series carrying the observed values
**and** the model's prediction at the same instants. That overlay is the single
most useful view in the console — the gap between the two lines is the fault,
visible long before either line approaches an alarm limit.

### `WS /stream`
One frame per tick. The server sends current state immediately on connect so a
client paints without waiting. Each subscriber gets a small bounded queue; a
client that cannot keep up has its oldest frame dropped rather than buffered,
because a twin that stalls when a browser tab sleeps is worse than a tab that
misses a second of history.

## Alerts

### `GET /alerts`
`?include_cleared=true&limit=100` — newest first.

### `POST /alerts/{id}/acknowledge`

## Maintenance

### `GET /maintenance/work-orders`
Pending interventions ranked by risk. See [analytics.md](analytics.md).

### `POST /maintenance/perform`
```json
{ "asset_id": "P-101A", "mode": "impeller_wear" }
```
Restores one wear mode, or every mode when `mode` is omitted. The asset is held
in a `maintenance` state for the work's duration, so the availability cost
lands in OEE instead of being free. Open alerts are closed and the RUL history
is discarded — after an overhaul the old trend is no longer evidence about the
new machine.

## Faults

### `GET /faults/catalogue` · `GET /faults`
The twelve injectable mechanisms, and whatever is currently active.

### `POST /faults`
```json
{ "asset_id": "P-101A", "mode": "impeller_erosion",
  "severity": 0.8, "ramp_hours": 3.0 }
```
Begins driving a failure mechanism. The fault raises a degradation **rate**,
ramped in over `ramp_hours`; it never writes a sensor value, so every symptom
that follows is produced by the physics.

### `DELETE /faults/{id}`
Stops driving the fault. Wear already accumulated is not undone — that is what
maintenance is for.

## What-if

### `POST /scenarios/simulate`
```json
{
  "name": "Overhaul the agitator gearbox now",
  "horizon_days": 45,
  "changes": [
    { "asset_id": "AGT-301", "parameter": "maintain" },
    { "asset_id": "RX-301",  "parameter": "setpoint_c", "value": 101.0 }
  ]
}
```

`parameter: "maintain"` restores an asset to as-new at t=0 and charges planned
rates; any other parameter overrides that design value for the projection.

Returns the proposed case, a do-nothing baseline over the same horizon,
per-day series for both, and the deltas in euros, saleable tonnes, CO₂ and OEE,
plus a plain-language verdict. Runs synchronously in a few hundred
milliseconds.

## Operations

### `GET /healthz`
Liveness plus twin vitals: tick count, simulated hours, series and point
counts, open alerts, active faults, and whether the detectors have finished
warming up.

### `GET /api/v1/meta`
Effective runtime configuration — tick interval, speed-up, history depth,
warm-up length.

## Errors

Every 4xx carries a `detail` string explaining what went wrong: `404` for an
unknown asset, tag, alert, fault or degradation mode; `422` for a request that
fails validation (a severity outside `[0, 1]`, a horizon over 365 days).

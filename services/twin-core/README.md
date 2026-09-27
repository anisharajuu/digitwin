# twin-core

The simulation and analytics service behind DigiTwin.

`twin-core` runs a first-principles model of every asset on the line, compares
what the model expects against what the sensors report, and turns the gap
between the two into health scores, remaining-useful-life estimates and alerts.
It exposes that state over REST and a WebSocket stream.

See [`docs/architecture.md`](../../docs/architecture.md) for the full design and
[`docs/api.md`](../../docs/api.md) for the endpoint reference.

## Run it

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000/docs.

## Test it

```bash
uv run pytest
uv run ruff check .
```

# Analytics

Three layers sit on the residual: detection (something changed), projection
(how long have I got), and valuation (what is it worth).

## Residual anomaly detection

`app/analytics/anomaly.py`

For every monitored tag the engine supplies two numbers per tick: what the
sensor read, and what the as-new model says it should have read under identical
operating conditions. The difference is the residual.

**Characterisation.** During a warm-up window the residual's normal
distribution is described by its **median** and **median absolute deviation**,
then frozen. Robust statistics rather than mean and standard deviation, for two
reasons: a fault arriving during warm-up widens the band instead of poisoning
the centre, and existing wear at boot is absorbed into the median rather than
being reported as a fault. Only *changes* from the established baseline alarm.

The scale is floored at the tag's known instrument noise, so a quiet channel
cannot manufacture enormous z-scores out of quantisation noise:

```
scale = max(1.4826 · MAD, instrument σ, 1e-6)
z     = (residual − median) / scale
```

**Smoothing and persistence.** The z-score is EWMA-smoothed (α = 0.25) and must
breach for six consecutive samples before anything is raised, and stay in band
for twenty before it clears. A single spike, however large, raises nothing.
That combination is what keeps the false-positive rate survivable across
seventy live tags.

**Thresholds.** Warning at 4σ, critical at 7.5σ. Alerts escalate but never
de-escalate, so one that peaked at critical stays visible as critical until it
genuinely clears.

**Measured behaviour.** Silent across 800 samples of healthy noise and across
26 simulated hours of full-plant operation. Catches a 0.9 mm/s vibration drift
— comfortably under the ISO 10816 Class III alarm limit of 4.5 mm/s — within
about ninety simulated minutes.

## Remaining useful life

`app/analytics/rul.py`

Wear is noisy and not quite linear, so ordinary least squares is a poor choice:
one bad sample drags the slope, the projected date jumps around, and an
operator stops trusting the number within about a day.

**Theil–Sen** is used instead — the median of all pairwise slopes. It tolerates
roughly 29 % contaminated samples before breaking down, and because it is a
median it moves smoothly as new data arrives. The spread of those pairwise
slopes falls out for free, which gives an honest confidence figure rather than
a fabricated one:

```
confidence = 0.75 · slope agreement (IQR vs median) + 0.25 · history maturity
```

It recovers a known wear rate to within 10 % and collapses from 719 days to
about 4 hours when a fault accelerates the trend. Nothing is published until
there are at least twelve samples, and a mode that is not trending toward
failure returns `null` rather than a spuriously precise date.

The estimator is deliberately slower to react than the residual detector. That
ordering is correct: residuals are the *warning* signal, RUL is the *planning*
signal, and a planning number that jumps around is worse than one that lags.

## Work orders

`TwinEngine.work_orders()` ranks pending interventions by **risk**, not by date:

```
urgency = 1 / (1 + hours_remaining / 168)          # one week reference
risk    = criticality_weight · urgency · 32 · (0.5 + confidence)
```

Sorting purely by due date is how a critical reactor slips behind a filter
change. Criticality weights run 0.5 / 1 / 2 / 4 from low to critical, so a
low-criticality asset failing next week can legitimately rank below a critical
one failing next month.

Each order carries the action, the estimated downtime and cost, and a plain
rationale naming the mechanism, its level, its trend and the confidence behind
the projection.

## Plant KPIs

`app/analytics/kpis.py`

OEE is computed the standard way — availability × performance × quality — but
each term is sourced from the twin rather than from a manual log:

- **Availability** — criticality-weighted, driven by which assets are in a
  fault or maintenance state right now. An asset counts as down only once a
  wear mode has actually reached its intervention threshold; an open alert
  means degraded, not stopped. Calling every alert an outage would make the
  number meaningless.
- **Performance** — achieved gross throughput against the line's design rate.
- **Quality** — on-spec yield end to end: reactor conversion × separator split
  efficiency. Unreacted feed and a failed phase split both cost saleable
  tonnes, so both belong in the same term.

Energy intensity, cost and carbon come out of the same tick, which is the
point: reliability and sustainability reporting stop being separate exercises
over separate spreadsheets.

## What-if projection

`app/simulation/scenarios.py`

Detecting a failing pump is table stakes. The question that releases budget is
"what does it cost me to fix it on Tuesday versus letting it run?" — and that
is a question about the future.

A projection forks the live twin (cloned wear, cloned dynamic state, optionally
overridden design parameters) and sweeps it forward under a deliberately simple
**run-to-failure policy**: run until a wear mode hits threshold, take the
unplanned outage, pay the unplanned bill, repeat. Unplanned work is charged at
3× planned cost and 2.2× planned downtime, which are the usual industry rules
of thumb.

The proposed case runs the identical model with the intervention applied up
front, charged at planned rates. The difference between the two, in euros and
saleable tonnes, is the business case.

Projections are isolated from live state and reproducible: running the same
scenario twice gives the same answer, and running one does not perturb the
twin. A 45-day horizon over ten assets lands in roughly 330 ms, so the console
can run it synchronously.

The verdict is stated plainly and is willing to say no — overhauling a healthy
asset buys downtime and nothing else, and the tool says so.

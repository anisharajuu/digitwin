# Simulation models

Ten assets on a specialty-chemicals line, each solved from first principles.
Units are SI-ish and stated on every tag: bar (absolute unless noted), °C, kW,
m³/h, mm/s RMS, K.

## The line

```
 TK-101 ──▶ P-101A ──▶ HX-201 ──▶ RX-301 ──▶ SEP-401 ──▶ TK-601
  surge      duty       feed       jacketed    product     product
  tank       pump     preheater    reactor     separator    tank
              ▲                       ▲
           P-101B                  AGT-301        CHL-202        CMP-501
           standby                 agitator       chiller        air compressor
```

At design point the line runs 118 m³/h, preheats feed to 97.8 °C, holds the
reactor at 96 °C with the jacket valve near 50 %, achieves 90 % conversion and
produces about 110 t/h of on-spec product for roughly 420 kW.

## Asset models

### Centrifugal pump — `P-101A`, `P-101B`

Head follows `H = H₀ − aQ²` against a system curve `H = H_s + bQ²`; the duty
point is where they meet. The system curve is fitted so an as-new pump lands
exactly on its best efficiency point.

Impeller wear drops `H₀` and steepens `a`, walking the duty point back down the
system curve. Flow and head fall together while shaft power stays stubbornly
high, because efficiency falls faster than hydraulic power does — the classic
signature, and the reason worn pumps hide on the electricity bill rather than
in the production numbers.

Bearing wear touches nothing the process can see: vibration RMS and bearing
temperature rise, flow does not move by a single m³/h. NPSH margin is tracked,
and cavitation (margin < 1 m) adds broadband vibration and accelerates impeller
wear by 3.4×.

### Heat exchanger — `HX-201`

Counter-flow shell-and-tube, solved effectiveness–NTU. Fouling adds a thermal
resistance in series with the clean UA — sized so a fully fouled bundle retains
half its clean UA — and narrows the flow area, so duty falls and pressure drop
rises together. Approach temperature is the tag that moves first, which is why
it is the one plant engineers actually trend.

### Jacketed reactor — `RX-301`

A CSTR running a first-order exothermic reaction, integrated rather than
assumed at steady state:

```
dC/dt = (C_in − C)/τ − k·C
dT/dt = (T_in − T)/τ + (−ΔH)·k·C/(ρ·c_p) − UA_eff·(T − T_cool)/(V·ρ·c_p)
k     = A·exp(−E_a/RT)
```

`UA_eff` is set by a PI controller on temperature. The interesting behaviour is
transient: when the jacket fouls, the controller opens up to compensate and the
reactor stays exactly on setpoint. Only once the valve saturates does the
temperature actually run away. A twin that solved this at steady state would
miss the entire margin-erosion story — which is precisely the early warning
worth having.

Sub-stepped at 5 s against a ~490 s residence time in the live loop, relaxed to
60 s for what-if projections.

### Agitator gearbox — `AGT-301`

The classic condition-monitoring asset. Nothing it does touches the process;
every symptom is a condition signal — vibration velocity against ISO 10816,
bearing temperature, oil particle count. That is exactly why it is the asset
where residual analytics earns its keep: no production number would ever warn
you. Lubricant degradation acts as a multiplier on the mechanical modes rather
than as an independent failure.

### Chiller — `CHL-202`

Condenser fouling raises the condensing temperature, costing COP roughly
linearly over the range that matters, and lowers the capacity ceiling just as
the machine is asked to work harder. Once it runs out of capacity the supply
temperature walks off setpoint — the point at which a reliability problem
becomes a production problem.

### Screw compressor — `CMP-501`

Modelled empirically against the shape of a VSD screw's published performance
map, not polytropically. On an oil-flooded screw the injected oil absorbs most
of the heat of compression, so a textbook adiabatic discharge temperature would
be wildly wrong. Being honest about that is better than being rigorous about
the wrong equation.

### Separator — `SEP-401`

Split efficiency is the plant's quality term. Fouling degrades it; so does
overloading the coalescer pack. On-spec yield is the whole chain — reactor
conversion × split efficiency — because feed that never reacted is as
unsaleable as product the pack failed to split.

### Buffer vessels — `TK-101`, `TK-601`

`volume_m3` is the twin's own integrated mass balance; `level_pct` is what the
transmitter reports. A `sensor_drift` fault separates the two without moving a
drop of liquid — the cheapest possible demonstration that the detector is
reasoning about a model rather than watching a threshold.

Two subtleties, both learned the hard way:

- **Level is a pure integrator**, so a free-running reference copy diverges
  without bound on any flow mismatch, however legitimate. The reference is
  re-anchored to the real inventory each tick (`anchor_reference`), which is
  what a state observer does, so the residual isolates the instrument.
- **The product export slot is exogenous.** A road-tanker booking is a
  commercial input, not a process response, so the export window is a pure
  function of time. Switching on each copy's own level instead let the two
  sawtooths drift out of phase and manufacture a 400 m³/h "residual" that meant
  nothing at all.

## Degradation

Every wear mechanism is a dimensionless level in `[0, 1]`, where `1.0` means
"this needs intervention now". Levels advance at a base rate drawn from the
asset's duty, accelerated by operating stress — cavitation, over-temperature,
abrasive particles in the oil — and by any injected fault, and are reset by a
maintenance action.

The levels are deliberately **not readable by any sensor**. They are the hidden
state the analytics layer has to infer from residuals, which is the whole point
of the exercise.

Bearing life follows the usual 10 K halving rule of thumb; fouling lays down
faster on a hot, slow-moving surface; a standby machine does not age on the
shelf.

## Fault catalogue

Twelve mechanisms across the line. Every one raises a degradation **rate**,
ramped in over a configurable window with a smoothstep so faults arrive
gradually rather than as a step change. Nothing writes a sensor value directly.

| Fault | Asset kinds | What you see |
| --- | --- | --- |
| Bearing spalling | pump, gearbox | Vibration and bearing temperature rise; no process change |
| Impeller erosion | pump | Head and flow fall while shaft power stays high |
| Exchanger fouling | heat exchanger | Approach widens, duty falls, shell dP rises |
| Condenser fouling | chiller | COP falls, power rises, supply drifts off setpoint |
| Jacket fouling | reactor | Control valve saturates; margin erodes before temperature moves |
| Catalyst deactivation | reactor | Conversion drops at unchanged temperature |
| Valve plate leakage | compressor | Volumetric efficiency and flow fall, specific power rises |
| Inlet filter blockage | compressor | Inlet dP rises, flow falls, discharge temperature climbs |
| Gear tooth wear | gearbox | Gear-mesh vibration and oil particle count rise together |
| Lubricant degradation | gearbox | Particle count and temperature rise; accelerates every other mode |
| Coalescer mesh fouling | separator | Split efficiency falls, dP rises — quality suffers |
| Level transmitter drift | tank | Reading diverges from the mass balance. No physical fault at all |

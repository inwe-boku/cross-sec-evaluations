# Plan: Cross-Sec coupling variables from PyPSA-AT

Status: decisions agreed, implemented in `coupling-variables.py` · updated 2026-11-04

## Scope (decisions)

- **Run:** `resources/electricity-network-0p3/AT_KN2040` (PyPSA-AT, myopic, horizons 2025/2030/2040/2050, 365 daily snapshots, Austria in NUTS3 regions `AT111` …).
- **Region:** Austria total (sum over all `AT*` locations).
- **Output:** marimo notebook `coupling-variables.py`, one cell per variable, for exploration (no export).
- **Input data:** only the run folder (`networks/`, `configs/`, `resources/energy_totals.csv`). No further inputs.
- **Variables not in the model:** keep them as "not modelled" cells.
- **Left out:** 8 Gesamter Endenergiebedarf, 25 Nachfrage nach industriellen Produkten.

## Status legend

| Status | Meaning |
|---|---|
| **A** | Model result: optimised, read directly from the network |
| **B** | Derived: computed from network results with an extra rule or assumption |
| **C** | Exogenous input: fixed in config or input data, passed through |
| **D** | Not in the model |
| **–** | Left out |

## Overview

| # | Variable | Status | Unit | Method (short) |
|---|---|---|---|---|
| 1 | Gesamte Größe des CO2-Untergrundspeichers in Österreich | C | Mt CO2 | national potential of `AT* co2 sequestered` stores |
| 2 | Kosten von Technologien (BECCS, DACCS, …) | C | €/MW/a, €/MWh | input costs of current vintage |
| 3 | Endenergiebedarf nach Energieträger Industrie | A/C | TWh/a | industry loads incl. non-energy use |
| 4 | Endenergiebedarf Mobilität, Energieträger fixiert | C | TWh/a | land transport only |
| 5 | Endenergiebedarf Wärme | C | TWh/a | useful heat demand (heat loads) |
| 6 | Installierte Leistungen von BECCS | A | MW, t CO2/h | capacities |
| 7 | Installierte Leistungen von DACCS | A | MW_el, t CO2/h | capacities |
| 8 | Gesamter Endenergiebedarf | – | | left out |
| 9 | Gesamte Speicherkapazität | A (+ C for vehicles) | GWh | stores by group, vehicle storage from config |
| 10 | Biomasse für Strom, Wärme, Treibstoffe | A | TWh/a, % | all biomass: supply and use |
| 11 | CO2-Preis | A | €/t CO2 | one value: EU cap + AT target shadow prices |
| 12 | Sanierungsrate | D | – | note only |
| 13 | Durchschnittliche Wohnfläche pro Person | D | – | not modelled |
| 14 | Indikator für Zersiedelung | D | – | not modelled |
| 15 | Anteil fossiler vs. erneuerbarer Heizsysteme | A | % | by heat output, heat pumps renewable |
| 16 | Anteil nachwachsender Baustoffe | D | – | not modelled |
| 17 | Anteil E-Autos | C | % | fleet share |
| 18 | Anzahl/Lage von Ladepunkten | D | – | not modelled |
| 19 | Durchschnittliches Geschwindigkeitsniveau | D | – | not modelled |
| 20 | Zurückgelegte Autokilometer pro Person | B | km/person/a | derived from loads and config |
| 21 | Zurückgelegte Wege ÖPNV | D | – | not modelled |
| 22 | Zurückgelegte Wege aktive Mobilität | D | – | not modelled |
| 23 | Anteil an erneuerbarem Strom im Industriesektor | B | % | grid mix incl. imports |
| 24 | Anteil des grünen Wasserstoffs im Industriesektor | B | % | electrolysis share, no weighting by electricity mix |
| 25 | Nachfrage nach industriellen Produkten | – | | left out |
| 26 | Import von grünem Wasserstoff / Stahl | D | – | not modelled, will be integrated later |

## Method per variable

### 1 CO2-Untergrundspeicher (national potential, no exports)
Sum over `AT* co2 sequestered` stores: remaining potential (`e_nom_max` of the current vintage) + capacity built in earlier horizons (`e_nom` of older vintages); used capacity (`e_nom_opt`) shown for context.

### 2 Kosten von Technologien (input costs only)
Current vintage (`-<year>`), mean over Austrian regions, for `DAC` and all BECCS carriers (see 6); more carriers can be added in `EXTRA_COST_CARRIERS`. Columns: `capital_cost` (annualised, incl. FOM, per MW of the bus0 input), `marginal_cost`, `lifetime`, capture rate (t CO2 per MWh input), capital cost per t CO2/h capture capacity. `overnight_cost` is empty in this run.

### 3 Endenergiebedarf Industrie (incl. non-energy use)
Withdrawal of Austrian industry loads: electricity, gas, solid biomass, H2, coal, low-temperature heat (energy use); naphtha, methanol, ammonia (non-energy use). `process emissions` excluded.

### 4 Endenergiebedarf Mobilität (land transport only)
Electricity = BEV charger input from the grid minus V2G feed-in; hydrogen = `land transport fuel cell` load; liquid fuels = `land transport oil` load. Carrier shares are fixed in the config (`land_transport_*_share`).

### 5 Endenergiebedarf Wärme (heat demand)
Useful heat loads: buildings rural, urban decentral, district heating; industry low-temperature heat and agriculture as separate rows.

### 6 BECCS (capacities)
Austrian links with `solid biomass` or `biogas` input and an output to `co2 stored`: capacity (MW input) and capture capacity (t CO2/h, and Mt CO2/a at full load). `waste CHP CC` is not included (input is waste, not biomass).

### 7 DACCS (capacities)
`DAC` links in Austria: capacity in MW_el (bus0 = electricity) and capture capacity (t CO2/h, Mt CO2/a at full load).

### 9 Gesamte Speicherkapazität
`e_nom_opt` of Austrian stores, grouped:
- electric: battery, home battery, PHS store, hydro store;
- gaseous: gas, H2 Store, ammonia store;
- heat: water tanks, water pits;
- vehicle: from config (`meta.sector`): number of BEVs (BEV charger capacity / `bev_charge_rate`) × `bev_energy` × `bev_dsm_availability`, from the year `bev_dsm` on. This equals the `EV battery` store in the network.

Excluded: `co2*`, `non-sequestered HVC` and fuel stocks (oil, coal, lignite, uranium, methanol).

### 10 Biomasse (all biomass)
- Supply: Austrian biomass generators (incl. unsustainable biomass in early years) + net imports via `solid biomass transport`.
- Use: withdrawal from the `solid biomass` and `biogas` buses by link carrier, grouped into power, heat, industry and fuels (gas, liquid, H2). CHP input is split into power and heat by energy output. Transport between regions is shown but excluded from the shares.

### 11 CO2-Preis (one value)
−(μ of `CO2Limit` + μ of `co2_limit-AT`).

### 12 Sanierungsrate (note only)
Not modelled: `retro_endogen: false`. Space-heat demand is reduced exogenously (`reduce_space_heat_exogenously_factor`), which is not a renovation rate.

### 15 Heizsysteme (by heat output)
Heat supplied to the building heat buses (rural, urban decentral, district heating) by technology, grouped:
- renewable: heat pumps, biomass, solar thermal;
- fossil: gas/oil boilers, gas/coal/lignite/oil CHPs;
- electric (resistive);
- other: waste heat, waste CHP, H2 CHP / fuel cell.

Storage discharge and heat venting are excluded.

### 17 Anteil E-Autos (fleet share)
Fleet shares = config `land_transport_{electric,fuel_cell,ice}_share` (PyPSA applies them to the vehicle count). Number of BEVs = BEV charger capacity / `bev_charge_rate`; implied fleet size = BEVs / electric share.

### 20 Autokilometer pro Person (derived)
Vehicle-km = land transport loads × `transport_{electric,fuel_cell,ice}_efficiency` × 100 km. Passenger-car share = energy share of passenger cars in road transport (`energy_totals.csv`, latest year 2024: 61.1 %). Divided by population (editable input, default 9.16 million, assumption).

### 23 Erneuerbarer Strom Industrie (incl. imports)
Share = (domestic RES generation + gross imports × RES share of the exporting country) / (domestic generation + gross imports). Applied to `industry electricity`. Storage discharge, V2G and transmission are not generation; waste CHP is non-renewable.

### 24 Grüner Wasserstoff Industrie (no weighting by electricity mix)
Green = `H2 Electrolysis`. Shares of domestic production and of domestic production + pipeline imports (imports not green). Pipeline trade shown as gross imports, gross exports and net imports.

## Results overview (Austria, from the notebook)

| # | 2025 → 2050 |
|---|---|
| 1 | 0 Mt in all years |
| 3 | 113 → 86 TWh |
| 4 | 66 → 24 TWh |
| 5 | 81 → 56 TWh |
| 6 | BioSNG CC 0 → 14.4 GW input; solid biomass for industry CC about 2 GW |
| 7 | ≈ 0 MW |
| 9 | ≈ 106 TWh (gas storage 100 TWh); vehicle 0 → 130 GWh |
| 10 | 71 → 128 TWh supply; net imports up to 92 TWh; 2050: 90 % fuels |
| 11 | 152 → 307 €/t |
| 15 | renewable 81 % → 9 % |
| 17 | 5 % → 99.9 % (0.26 → 5.18 million BEVs) |
| 20 | ≈ 7,400–7,600 km/person |
| 23 | 52 % → 63 % |
| 24 | ≈ 0 % |

## Open points

- **Run-of-river is 0 in this run:** `p_nom_opt = 0` for all Austrian `ror` generators (probably the `Trajectories … ['ror']` upper-limit constraint). Austrian hydro is only about 2.3 TWh, so domestic generation is too low and imports are too high. This affects 23 (and 10, 15 indirectly). To be clarified with the model run.
- **15, gas counted as fossil:** by 2050 heat comes mostly from gas boilers, while Austria produces 72 TWh of BioSNG. Option: split gas boilers by the green-gas share of Austrian gas supply.
- **20, population:** no population in the run data; the default 9.16 million is an assumption.
- **24, green H2:** electrolysis is built but barely dispatched. Austrian H2 comes from biomass-to-hydrogen (3.7 TWh) and pipeline net imports (4–19 TWh); gross imports (up to 257 TWh) are mostly transit.
- **26:** H2 and steel imports will be integrated later.

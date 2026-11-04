import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import logging

    import marimo as mo
    import numpy as np
    import pandas as pd
    import pypsa

    logging.getLogger("pypsa").setLevel(logging.ERROR)
    return mo, np, pd, pypsa


@app.cell
def _(mo):
    mo.md(r"""
    # Cross-Sec coupling variables from PyPSA-AT

    Run: `resources/electricity-network-0p3/AT_KN2040` · region: **Austria total** (all `AT*` locations).
    Plan and decisions: `coupling-variables-plan.md`.

    Left out on purpose: *Gesamter Endenergiebedarf* (8), *Nachfrage nach industriellen Produkten* (25).
    """)
    return


@app.cell
def _(mo, pd, pypsa):
    RUN_DIR = mo.notebook_dir() / "resources" / "electricity-network-0p3" / "AT_KN2040"

    networks = {}
    for _f in sorted((RUN_DIR / "networks").glob("*.nc")):
        _n = pypsa.Network(_f)
        networks[int(_n.meta["wildcards"]["planning_horizons"])] = _n

    energy_totals = pd.read_csv(RUN_DIR / "resources" / "energy_totals.csv", index_col=[0, 1])
    mo.md(f"Loaded investment years: {list(networks)}")
    return energy_totals, networks


@app.cell
def _(pd, pypsa):
    MWH_TO_TWH = 1e-6
    BIOMASS_BUS_CARRIERS = ["solid biomass", "biogas"]


    def bus_in_at(n: pypsa.Network, buses: pd.Series) -> pd.Series:
        """True where a bus lies in Austria."""
        return buses.map(n.buses.location).fillna("").str.startswith("AT")


    def at_by_carrier(stat: pd.Series) -> pd.Series:
        """Sum an `n.statistics` result over Austrian locations, per carrier."""
        if stat.empty:
            return pd.Series(dtype=float)
        stat = stat.groupby(level=["location", "carrier"]).sum()
        at = stat.index.get_level_values("location").str.startswith("AT")
        return stat[at].groupby(level="carrier").sum()


    def by_country_carrier(stat: pd.Series) -> pd.Series:
        """Sum an `n.statistics` result per country (first two letters of location) and carrier."""
        stat = stat.groupby(level=["location", "carrier"]).sum()
        country = pd.Index(stat.index.get_level_values("location").str[:2], name="country")
        return stat.groupby([country, stat.index.get_level_values("carrier")]).sum()


    def stat_at(
        n: pypsa.Network, kind: str, components: list[str], bus_carrier: list[str] | None = None
    ) -> pd.Series:
        """Austrian `supply` or `withdrawal` per carrier in MWh/a."""
        func = getattr(n.statistics, kind)
        stat = func(
            components=components,
            bus_carrier=bus_carrier,
            groupby=["location", "carrier"],
            nice_names=False,
        )
        return at_by_carrier(stat)


    def port_efficiency(n: pypsa.Network, links: pd.DataFrame, bus_carrier: str) -> pd.Series:
        """Energy at all ports of `links` connected to `bus_carrier`, per unit of bus0 input."""
        eff = pd.Series(0.0, index=links.index)
        ports = [c for c in links.columns if c.startswith("bus") and c[3:].isdigit()]
        for col in ports:
            i = int(col[3:])
            hits = links[col].map(n.buses.carrier) == bus_carrier
            if i == 0:
                port_eff = pd.Series(-1.0, index=links.index)
            else:
                port_eff = links["efficiency" if i == 1 else f"efficiency{i}"]
            eff += port_eff.where(hits, 0.0)
        return eff


    def border_flows(n: pypsa.Network, component: str, carriers: list[str] | None = None) -> pd.DataFrame:
        """Gross energy flows across the Austrian border (MWh/a), by neighbouring country.

        Columns `imports` (into AT) and `exports` (out of AT). `component` is the list name,
        e.g. "lines" or "links".
        """
        static, dynamic = getattr(n, component), getattr(n, f"{component}_t")
        if carriers is not None:
            static = static[static.carrier.isin(carriers)]
        w = n.snapshot_weightings.generators
        parts = []
        for k, other in ((0, 1), (1, 0)):
            sel = static.index[bus_in_at(n, static[f"bus{k}"]) & ~bus_in_at(n, static[f"bus{other}"])]
            if len(sel) == 0:
                continue
            p = dynamic[f"p{k}"].reindex(columns=sel, fill_value=0.0).mul(w, axis=0)
            neighbour = static.loc[sel, f"bus{other}"].map(n.buses.location).str[:2]
            parts.append(
                pd.DataFrame(
                    {"imports": (-p).clip(lower=0).sum(), "exports": p.clip(lower=0).sum(), "country": neighbour}
                )
            )
        if not parts:
            return pd.DataFrame(columns=["imports", "exports"], dtype=float)
        return pd.concat(parts).groupby("country")[["imports", "exports"]].sum()


    def beccs_links(n: pypsa.Network) -> pd.DataFrame:
        """Austrian links with biomass input and an output to `co2 stored` (BECCS)."""
        links = n.links[bus_in_at(n, n.links.bus0)]
        capture = port_efficiency(n, links, "co2 stored")
        is_bio = links.bus0.map(n.buses.carrier).isin(BIOMASS_BUS_CARRIERS)
        return links[is_bio & (capture > 0)].assign(co2_capture=capture)


    def config_by_year(value: dict | float, year: int) -> float:
        """Read a per-year config value (keys may be int or str)."""
        if not isinstance(value, dict):
            return value
        return value.get(year, value.get(str(year)))
    return (
        MWH_TO_TWH,
        beccs_links,
        border_flows,
        bus_in_at,
        by_country_carrier,
        config_by_year,
        port_efficiency,
        stat_at,
    )


@app.cell
def _(bus_in_at, mo, networks, np, pd):
    # 1 Gesamte Größe des CO2-Untergrundspeichers in Österreich (national potential)
    _rows = []
    for _y, _n in networks.items():
        _s = _n.stores[(_n.stores.carrier == "co2 sequestered") & bus_in_at(_n, _n.stores.bus)]
        _current = _s.index.str.endswith(f"-{_y}")  # myopic: older vintages are fixed
        _remaining = _s.e_nom_max.where(_current & _s.e_nom_extendable, 0.0).replace(np.inf, np.nan)
        _built = _s.e_nom.where(~_current, 0.0)
        _rows.append(
            {
                "year": _y,
                "remaining potential": _remaining.sum() / 1e6,
                "built in earlier horizons": _built.sum() / 1e6,
                "national potential": (_remaining.sum() + _built.sum()) / 1e6,
                "used (optimised)": _s.e_nom_opt.sum() / 1e6,
            }
        )
    mo.vstack(
        [
            mo.md("## 1 Gesamte Größe des CO2-Untergrundspeichers in Österreich [Mt CO2]"),
            mo.md("Sum over all `AT* co2 sequestered` stores. Unlimited potential (`inf`) would show as empty."),
            pd.DataFrame(_rows).set_index("year").round(3),
        ]
    )
    return


@app.cell
def _(beccs_links, bus_in_at, mo, networks, pd, port_efficiency):
    # 2 Kosten von Technologien (BECCS, DACCS, ...) - input costs only
    EXTRA_COST_CARRIERS = []  # add further link carriers here, e.g. "H2 Electrolysis"

    _rows = []
    for _y, _n in networks.items():
        _links = _n.links[bus_in_at(_n, _n.links.bus0) & _n.links.index.str.endswith(f"-{_y}")]
        _bio = beccs_links(_n).carrier.unique().tolist()
        _sel = _links[_links.carrier.isin(["DAC", *_bio, *EXTRA_COST_CARRIERS])]
        _sel = _sel.assign(co2_capture=port_efficiency(_n, _sel, "co2 stored"))
        _sel = _sel.assign(group=_sel.carrier.map(lambda c: "DACCS" if c == "DAC" else "BECCS" if c in _bio else "other"))
        _g = _sel.groupby(["group", "carrier"])
        _df = pd.DataFrame(
            {
                "unit of p_nom (bus0)": _g.bus0.first().map(_n.buses.carrier),
                "capital_cost [€/MW/a]": _g.capital_cost.mean(),
                "marginal_cost [€/MWh]": _g.marginal_cost.mean(),
                "lifetime [a]": _g.lifetime.mean(),
                "capture [t CO2/MWh]": _g.co2_capture.mean(),
            }
        )
        _df["capital_cost [€/(t CO2/h)/a]"] = _df["capital_cost [€/MW/a]"] / _df["capture [t CO2/MWh]"]
        _rows.append(_df.assign(year=_y))
    mo.vstack(
        [
            mo.md(
                "## 2 Kosten von Technologien (input costs)\n"
                "Current vintage, mean over Austrian regions. `capital_cost` is annualised (incl. FOM); "
                "`overnight_cost` is empty in this run. Per MW of the bus0 input (`bus0 unit`: AC = MW_el)."
            ),
            pd.concat(_rows).reset_index().set_index(["year", "group", "carrier"]).round(3),
        ]
    )
    return


@app.cell
def _(MWH_TO_TWH, mo, networks, pd, stat_at):
    # 3 Endenergiebedarf nach Energieträger Industrie (incl. non-energy use)
    INDUSTRY_LOADS = {
        "industry electricity": ("Electricity", "energy"),
        "gas for industry": ("Gas", "energy"),
        "solid biomass for industry": ("Solid biomass", "energy"),
        "H2 for industry": ("Hydrogen", "energy"),
        "coal for industry": ("Coal", "energy"),
        "low-temperature heat for industry": ("Heat", "energy"),
        "naphtha for industry": ("Oil (naphtha)", "non-energy"),
        "industry methanol": ("Methanol", "non-energy"),
        "NH3": ("Ammonia", "non-energy"),
    }

    _rows = []
    for _y, _n in networks.items():
        _w = stat_at(_n, "withdrawal", ["Load"])
        for _c, (_carrier, _use) in INDUSTRY_LOADS.items():
            _rows.append({"year": _y, "carrier": _carrier, "use": _use, "value": _w.get(_c, 0.0) * MWH_TO_TWH})
    _df = pd.DataFrame(_rows).pivot_table(index=["use", "carrier"], columns="year", values="value", aggfunc="sum").rename(columns=str)
    _df.loc[("total", "total"), :] = _df.sum()
    mo.vstack(
        [
            mo.md("## 3 Endenergiebedarf Industrie nach Energieträger [TWh/a]\nAustrian industry loads; `process emissions` (CO2) excluded."),
            _df.round(2),
        ]
    )
    return


@app.cell
def _(MWH_TO_TWH, bus_in_at, mo, networks, pd, stat_at):
    # 4 Endenergiebedarf Mobilität (land transport), Energieträger fixiert
    _rows = []
    for _y, _n in networks.items():
        _w = _n.snapshot_weightings.generators
        _l = _n.links[bus_in_at(_n, _n.links.bus0)]
        _bev = _l.index[_l.carrier == "BEV charger"]
        _v2g = _l.index[_l.carrier == "V2G"]
        _charged = _n.links_t.p0.reindex(columns=_bev, fill_value=0).mul(_w, axis=0).sum().sum()
        _fed_back = (-_n.links_t.p1.reindex(columns=_v2g, fill_value=0)).mul(_w, axis=0).sum().sum()
        _loads = stat_at(_n, "withdrawal", ["Load"])
        _rows += [
            {"year": _y, "carrier": "Electricity (grid, net of V2G)", "value": _charged - _fed_back},
            {"year": _y, "carrier": "Hydrogen", "value": _loads.get("land transport fuel cell", 0.0)},
            {"year": _y, "carrier": "Liquid fuels", "value": _loads.get("land transport oil", 0.0)},
        ]
    _df = pd.DataFrame(_rows).pivot_table(index="carrier", columns="year", values="value").rename(columns=str) * MWH_TO_TWH
    _df.loc["total"] = _df.sum()
    mo.vstack(
        [
            mo.md("## 4 Endenergiebedarf Landverkehr [TWh/a]\nCarrier shares are fixed in the config (`land_transport_*_share`)."),
            _df.round(2),
        ]
    )
    return


@app.cell
def _(MWH_TO_TWH, mo, networks, pd, stat_at):
    # 5 Endenergiebedarf Wärme (heat demand)
    HEAT_LOADS = {
        "rural heat": "Buildings – rural",
        "urban decentral heat": "Buildings – urban decentral",
        "urban central heat": "Buildings – district heating",
        "low-temperature heat for industry": "Industry low-temperature heat",
        "agriculture heat": "Agriculture",
    }
    _data = {}
    for _y, _n in networks.items():
        _w = stat_at(_n, "withdrawal", ["Load"])
        _data[_y] = pd.Series({v: _w.get(k, 0.0) for k, v in HEAT_LOADS.items()}) * MWH_TO_TWH
    _df = pd.DataFrame(_data).rename(columns=str)
    _df.loc["total"] = _df.sum()
    mo.vstack([mo.md("## 5 Wärmebedarf (useful heat demand) [TWh/a]"), _df.round(2)])
    return


@app.cell
def _(beccs_links, mo, networks, pd):
    # 6 Installierte Leistungen BECCS
    _rows = []
    for _y, _n in networks.items():
        _b = beccs_links(_n)
        _g = _b.assign(capture=_b.p_nom_opt * _b.co2_capture).groupby("carrier")
        _rows.append(
            pd.DataFrame(
                {
                    "input bus": _g.bus0.first().map(_n.buses.carrier),
                    "capacity [MW input]": _g.p_nom_opt.sum(),
                    "capture capacity [t CO2/h]": _g.capture.sum(),
                }
            ).assign(year=_y)
        )
    _df = pd.concat(_rows).reset_index().set_index(["year", "carrier"])
    _df["capture capacity at full load [Mt CO2/a]"] = _df["capture capacity [t CO2/h]"] * 8760 / 1e6
    mo.vstack(
        [
            mo.md(
                "## 6 Installierte Leistungen BECCS\n"
                "Austrian links with solid biomass or biogas input and an output to `co2 stored`. "
                "`waste CHP CC` is not included (input is non-sequestered HVC / waste)."
            ),
            _df.round(2),
        ]
    )
    return


@app.cell
def _(bus_in_at, mo, networks, pd, port_efficiency):
    # 7 Installierte Leistungen DACCS
    _rows = []
    for _y, _n in networks.items():
        _d = _n.links[(_n.links.carrier == "DAC") & bus_in_at(_n, _n.links.bus0)]
        _capture = (_d.p_nom_opt * port_efficiency(_n, _d, "co2 stored")).sum()
        _rows.append(
            {
                "year": _y,
                "capacity [MW_el]": _d.p_nom_opt.sum(),
                "capture capacity [t CO2/h]": _capture,
                "capture capacity at full load [Mt CO2/a]": _capture * 8760 / 1e6,
            }
        )
    mo.vstack([mo.md("## 7 Installierte Leistungen DACCS (`DAC`, bus0 = electricity)"), pd.DataFrame(_rows).set_index("year").round(3)])
    return


@app.cell
def _(bus_in_at, mo, networks, pd):
    # 9 Gesamte Speicherkapazität
    STORAGE_GROUPS = {
        "battery": "electric",
        "home battery": "electric",
        "PHS store": "electric",
        "hydro store": "electric",
        "gas": "gaseous",
        "H2 Store": "gaseous",
        "ammonia store": "gaseous",
        "rural water tanks": "heat",
        "urban decentral water tanks": "heat",
        "urban central water tanks": "heat",
        "urban central water pits": "heat",
    }

    def _vehicle_storage(n, year: int) -> float:
        """V2G/DSM storage from config: number of BEVs x bev_energy x bev_dsm_availability (MWh)."""
        s = n.meta["sector"]
        dsm = s["bev_dsm"]
        active = dsm if isinstance(dsm, bool) else year >= int(dsm)
        if not active:
            return 0.0
        chargers = n.links[(n.links.carrier == "BEV charger") & bus_in_at(n, n.links.bus0)]
        n_bev = chargers.p_nom_opt.sum() / s["bev_charge_rate"]
        return n_bev * s["bev_energy"] * s["bev_dsm_availability"]

    _rows = []
    for _y, _n in networks.items():
        _st = _n.stores[bus_in_at(_n, _n.stores.bus) & _n.stores.carrier.isin(STORAGE_GROUPS)]
        _e = _st.groupby("carrier").e_nom_opt.sum()
        for _c, _v in _e.items():
            _rows.append({"year": _y, "group": STORAGE_GROUPS[_c], "carrier": _c, "value": _v})
        _rows.append({"year": _y, "group": "vehicle", "carrier": "EV battery (V2G/DSM, from config)", "value": _vehicle_storage(_n, _y)})
    _df = pd.DataFrame(_rows).pivot_table(index=["group", "carrier"], columns="year", values="value", aggfunc="sum").fillna(0).rename(columns=str) / 1e3
    _totals = _df.groupby(level="group").sum()
    _totals.loc["total"] = _totals.sum()
    _cfg = {k: networks[max(networks)].meta["sector"][k] for k in ["v2g", "bev_dsm", "bev_energy", "bev_dsm_availability", "bev_charge_rate"]}
    mo.vstack(
        [
            mo.md(
                "## 9 Gesamte Speicherkapazität [GWh]\n"
                f"Vehicle storage = BEVs (charger capacity / `bev_charge_rate`) × `bev_energy` × `bev_dsm_availability`, "
                f"only from the year `bev_dsm` on. Config: `{_cfg}`"
            ),
            _totals.round(1),
            _df.round(1),
        ]
    )
    return


@app.cell
def _(MWH_TO_TWH, border_flows, bus_in_at, mo, networks, pd, port_efficiency, stat_at):
    # 10 Biomasse: supply and use (all biomass)
    def _use_category(carrier: str) -> str:
        if "transport" in carrier:
            return "transport between regions (excluded)"
        if "CHP" in carrier:
            return "CHP"
        if "boiler" in carrier:
            return "heat"
        if "for industry" in carrier:
            return "industry"
        if carrier in ("solid biomass", "biogas"):
            return "power"
        return "fuels (gas, liquid, H2)"

    def _chp_power_share(n, carrier: str) -> float:
        """Share of electricity in the energy output of an Austrian CHP carrier."""
        l = n.links[(n.links.carrier == carrier) & bus_in_at(n, n.links.bus0)]
        el = port_efficiency(n, l, "AC").mean()
        heat = port_efficiency(n, l, "urban central heat").mean()
        return el / (el + heat) if el + heat > 0 else 0.0

    _supply, _use = {}, {}
    for _y, _n in networks.items():
        _gen = stat_at(_n, "supply", ["Generator"], ["solid biomass", "biogas"])
        _flows = border_flows(_n, "links", ["solid biomass transport"]).sum()
        _supply[_y] = pd.concat(
            [
                _gen.rename(lambda c: f"domestic {c}"),
                pd.Series({"net imports solid biomass": _flows.get("imports", 0.0) - _flows.get("exports", 0.0)}),
            ]
        )

        _w = stat_at(_n, "withdrawal", ["Link"], ["solid biomass", "biogas"])
        _cats = {}
        for _c, _v in _w.items():
            _cat = _use_category(_c)
            if _cat == "CHP":
                _share = _chp_power_share(_n, _c)
                _cats["power"] = _cats.get("power", 0.0) + _v * _share
                _cats["heat"] = _cats.get("heat", 0.0) + _v * (1 - _share)
            else:
                _cats[_cat] = _cats.get(_cat, 0.0) + _v
        _use[_y] = pd.Series(_cats)
    _sdf = pd.DataFrame(_supply).fillna(0).rename(columns=str) * MWH_TO_TWH
    _sdf.loc["total"] = _sdf.sum()
    _udf = pd.DataFrame(_use).fillna(0).rename(columns=str) * MWH_TO_TWH
    _shares = _udf.drop(index="transport between regions (excluded)", errors="ignore")
    _shares = _shares / _shares.sum() * 100
    mo.vstack(
        [
            mo.md(
                "## 10 Biomasse (all biomass)\n"
                "Primary biomass input in TWh/a. CHP input is split into power and heat by energy output. "
                "Fuels include BioSNG, biogas upgrading, BtL, biomass-to-methanol and solid biomass to hydrogen."
            ),
            mo.md("**Supply [TWh/a]**"),
            _sdf.round(2),
            mo.md("**Use [TWh/a]**"),
            _udf.round(2),
            mo.md("**Use shares [%]** (without transport between regions)"),
            _shares.round(1),
        ]
    )
    return


@app.cell
def _(mo, networks, pd):
    # 11 CO2-Preis (one value)
    CO2_CONSTRAINTS = ["CO2Limit", "co2_limit-AT"]
    _rows = []
    for _y, _n in networks.items():
        _gc = _n.global_constraints.reindex(CO2_CONSTRAINTS)
        _rows.append({"year": _y, "CO2 price [€/t CO2]": -_gc.mu.fillna(0).sum()})
    mo.vstack(
        [
            mo.md(f"## 11 CO2-Preis\nShadow price: −(μ of {CO2_CONSTRAINTS}), EU-wide cap plus Austrian target."),
            pd.DataFrame(_rows).set_index("year").round(1),
        ]
    )
    return


@app.cell
def _(mo):
    # 12 Sanierungsrate
    mo.md(r"""
    ## 12 Sanierungsrate — not modelled
    Retrofitting is not optimised (`sector.retrofitting.retro_endogen: false`). Space-heat demand is reduced
    exogenously by `sector.reduce_space_heat_exogenously_factor`; this is not a renovation rate.
    """)
    return


@app.cell
def _(mo):
    # 13 Durchschnittliche Wohnfläche pro Person
    mo.md("## 13 Durchschnittliche Wohnfläche pro Person — not modelled")
    return


@app.cell
def _(mo):
    # 14 Indikator für Zersiedelung
    mo.md("## 14 Indikator für Zersiedelung (z.B. Nutzungsdichte) — not modelled")
    return


@app.cell
def _(MWH_TO_TWH, mo, networks, pd, stat_at):
    # 15 Anteil fossiler vs. erneuerbarer Heizsysteme (by heat output)
    BUILDING_HEAT_BUSES = ["rural heat", "urban decentral heat", "urban central heat"]

    def _heat_category(carrier: str) -> str | None:
        if any(k in carrier for k in ("water tanks", "water pits", "heat vent")):
            return None  # storage discharge / venting is not a heating system
        if any(k in carrier for k in ("heat pump", "biomass", "solar thermal")):
            return "renewable"
        if any(k in carrier for k in ("gas boiler", "oil boiler", "gas CHP", "coal CHP", "lignite CHP", "oil CHP")):
            return "fossil"
        if "resistive heater" in carrier:
            return "electric (resistive)"
        return "other (waste heat, waste CHP, H2 CHP)"

    _out = {}
    for _y, _n in networks.items():
        _s = stat_at(_n, "supply", ["Generator", "Link"], BUILDING_HEAT_BUSES)
        _cat = _s.groupby(_s.index.map(_heat_category)).sum()
        _out[_y] = _cat
    _df = pd.DataFrame(_out).fillna(0).rename(columns=str) * MWH_TO_TWH
    _share = _df / _df.sum() * 100
    mo.vstack(
        [
            mo.md(
                "## 15 Anteil fossiler vs. erneuerbarer Heizsysteme (by heat output)\n"
                "Heat supplied to the building heat buses (rural, urban decentral, district heating). "
                "Heat pumps count as renewable; gas boilers and gas CHPs as fossil."
            ),
            mo.md("**Heat output [TWh/a]**"),
            _df.round(2),
            mo.md("**Shares [%]**"),
            _share.round(1),
        ]
    )
    return


@app.cell
def _(mo):
    # 16 Anteil nachwachsender Baustoffe
    mo.md("## 16 Anteil nachwachsender Baustoffe — not modelled")
    return


@app.cell
def _(bus_in_at, config_by_year, mo, networks, pd):
    # 17 Anteil E-Autos (fleet share)
    _rows = []
    for _y, _n in networks.items():
        _s = _n.meta["sector"]
        _el = config_by_year(_s["land_transport_electric_share"], _y)
        _chargers = _n.links[(_n.links.carrier == "BEV charger") & bus_in_at(_n, _n.links.bus0)]
        _n_bev = _chargers.p_nom_opt.sum() / _s["bev_charge_rate"]
        _rows.append(
            {
                "year": _y,
                "BEV fleet share [%]": _el * 100,
                "FCEV fleet share [%]": config_by_year(_s["land_transport_fuel_cell_share"], _y) * 100,
                "ICE fleet share [%]": config_by_year(_s["land_transport_ice_share"], _y) * 100,
                "number of BEVs [million]": _n_bev / 1e6,
                "implied fleet size [million]": _n_bev / _el / 1e6 if _el else float("nan"),
            }
        )
    mo.vstack(
        [
            mo.md(
                "## 17 Anteil E-Autos\n"
                "The config shares are applied to the vehicle count (charger capacity = cars × share × `bev_charge_rate`), "
                "so they are fleet shares. Number of BEVs = BEV charger capacity / `bev_charge_rate`."
            ),
            pd.DataFrame(_rows).set_index("year").round(2),
        ]
    )
    return


@app.cell
def _(mo):
    # 18 Anzahl/Lage von Ladepunkten
    mo.md("## 18 Anzahl/Lage von Ladepunkten pro Fahrzeug/Einwohner — not modelled")
    return


@app.cell
def _(mo):
    # 19 Durchschnittliches Geschwindigkeitsniveau
    mo.md("## 19 Durchschnittliches Geschwindigkeitsniveau — not modelled")
    return


@app.cell
def _(mo):
    population_at = mo.ui.number(
        start=1e6,
        stop=2e7,
        step=1e4,
        value=9_160_000,
        label="Population AT (assumption, not in run data; Statistik Austria 2024 ≈ 9.16 million)",
    )
    population_at
    return (population_at,)


@app.cell
def _(energy_totals, mo, networks, pd, population_at, stat_at):
    # 20 Zurückgelegte Autokilometer pro Person (derived)
    _et = energy_totals.loc["AT"]
    _base_year = _et.index[_et["total road"] > 0].max()
    _car_share = _et.loc[_base_year, "total passenger cars"] / _et.loc[_base_year, "total road"]

    _rows = []
    for _y, _n in networks.items():
        _s = _n.meta["sector"]
        _loads = stat_at(_n, "withdrawal", ["Load"])
        # config: 1 MWh = efficiency x 100 km for each drive type
        _vkm = 100 * (
            _loads.get("land transport EV", 0.0) * _s["transport_electric_efficiency"]
            + _loads.get("land transport fuel cell", 0.0) * _s["transport_fuel_cell_efficiency"]
            + _loads.get("land transport oil", 0.0) * _s["transport_ice_efficiency"]
        )
        _rows.append(
            {
                "year": _y,
                "land transport vehicle-km [bn km]": _vkm / 1e9,
                "passenger car vehicle-km [bn km]": _vkm * _car_share / 1e9,
                "car-km per person [km]": _vkm * _car_share / population_at.value,
            }
        )
    mo.vstack(
        [
            mo.md(
                "## 20 Zurückgelegte Autokilometer pro Person (derived)\n"
                "Vehicle-km = land transport loads × `transport_*_efficiency` × 100 km. Passenger-car share = "
                f"energy share of passenger cars in road transport in `energy_totals.csv` ({_base_year}: {_car_share:.1%}). "
                "This assumes cars and other road vehicles have the same energy per km."
            ),
            pd.DataFrame(_rows).set_index("year").round(1),
        ]
    )
    return


@app.cell
def _(mo):
    # 21 Zurückgelegte Wege ÖPNV
    mo.md("## 21 Zurückgelegte Wege ÖPNV — not modelled")
    return


@app.cell
def _(mo):
    # 22 Zurückgelegte Wege aktive Mobilität
    mo.md("## 22 Zurückgelegte Wege aktive Mobilität — not modelled")
    return


@app.cell
def _(MWH_TO_TWH, border_flows, by_country_carrier, mo, networks, pd, stat_at):
    # 23 Anteil erneuerbarer Strom im Industriesektor (incl. imports)
    NOT_GENERATION = [
        "DC",
        "electricity distribution grid",
        "battery discharger",
        "home battery discharger",
        "PHS discharger",
        "V2G",
    ]
    RENEWABLE_ELECTRICITY = [
        "onwind",
        "offwind-ac",
        "offwind-dc",
        "offwind-float",
        "solar",
        "solar rooftop",
        "solar-hsat",
        "ror",
        "hydro",
        "hydro discharger",
        "solid biomass",
        "biogas",
        "urban central solid biomass CHP",
        "urban central solid biomass CHP CC",
    ]

    _rows = []
    for _y, _n in networks.items():
        _gen = _n.statistics.supply(
            components=["Generator", "Link", "StorageUnit"],
            bus_carrier=["AC", "low voltage"],
            groupby=["location", "carrier"],
            nice_names=False,
        )
        _gen = by_country_carrier(_gen)
        _gen = _gen[~_gen.index.get_level_values("carrier").isin(NOT_GENERATION)]
        _is_res = _gen.index.get_level_values("carrier").isin(RENEWABLE_ELECTRICITY)
        _total = _gen.groupby(level="country").sum()
        _res_share = _gen[_is_res].groupby(level="country").sum().reindex(_total.index, fill_value=0) / _total

        _flows = pd.concat([border_flows(_n, "lines"), border_flows(_n, "links", ["DC"])]).groupby(level=0).sum()
        _imp = _flows["imports"]
        _imp_res = (_imp * _res_share.reindex(_imp.index).fillna(0)).sum()
        _dom, _dom_res = _total.get("AT", 0.0), _res_share.get("AT", 0.0) * _total.get("AT", 0.0)
        _share = (_dom_res + _imp_res) / (_dom + _imp.sum())
        _ind = stat_at(_n, "withdrawal", ["Load"]).get("industry electricity", 0.0)
        _rows.append(
            {
                "year": _y,
                "domestic generation [TWh]": _dom * MWH_TO_TWH,
                "gross imports [TWh]": _imp.sum() * MWH_TO_TWH,
                "gross exports [TWh]": _flows["exports"].sum() * MWH_TO_TWH,
                "RES share domestic only [%]": _dom_res / _dom * 100,
                "RES share incl. imports [%]": _share * 100,
                "industry electricity [TWh]": _ind * MWH_TO_TWH,
                "renewable industry electricity [TWh]": _ind * _share * MWH_TO_TWH,
            }
        )
    mo.vstack(
        [
            mo.md(
                "## 23 Anteil erneuerbarer Strom im Industriesektor\n"
                "Industry uses the grid mix. Share = (domestic RES generation + gross imports × RES share of the "
                "exporting country) / (domestic generation + gross imports), i.e. exports and transit leave with the "
                "same mix. Storage discharge, V2G and transmission are not generation; waste CHP counts as non-renewable."
            ),
            pd.DataFrame(_rows).set_index("year").round(2),
        ]
    )
    return


@app.cell
def _(MWH_TO_TWH, border_flows, mo, networks, pd, stat_at):
    # 24 Anteil grüner Wasserstoff im Industriesektor (no weighting by electricity mix)
    _out, _trade = {}, {}
    for _y, _n in networks.items():
        _prod = stat_at(_n, "supply", ["Link", "Generator"], ["H2"])
        _prod = _prod[~_prod.index.str.contains("pipeline")]
        _pipes = [c for c in _n.links.carrier.unique() if "H2 pipeline" in c]
        _flows = border_flows(_n, "links", _pipes).sum()
        _col = _prod.rename(lambda c: f"domestic: {c}")
        _col["imports (pipeline)"] = _flows.get("imports", 0.0)
        _out[_y] = _col
        _trade[_y] = pd.Series(
            {
                "gross imports": _flows.get("imports", 0.0),
                "gross exports": _flows.get("exports", 0.0),
                "net imports": _flows.get("imports", 0.0) - _flows.get("exports", 0.0),
            }
        )
    _df = pd.DataFrame(_out).fillna(0).rename(columns=str) * MWH_TO_TWH
    _trade_df = pd.DataFrame(_trade).rename(columns=str) * MWH_TO_TWH
    _green = _df.loc[_df.index.str.contains("Electrolysis")].sum()
    _domestic = _df.loc[_df.index.str.startswith("domestic")].sum()
    _summary = pd.DataFrame(
        {
            "green share of domestic production [%]": _green / _domestic * 100,
            "green share incl. imports (imports not green) [%]": _green / _df.sum() * 100,
        }
    ).T
    mo.vstack(
        [
            mo.md(
                "## 24 Anteil grüner Wasserstoff im Industriesektor\n"
                "Green = `H2 Electrolysis` (no weighting by the electricity mix). Industry uses the Austrian H2 mix, "
                "so the share applies to `H2 for industry`. Pipeline imports are shown separately."
            ),
            mo.md("**H2 supply in Austria [TWh/a]** (gross imports include transit)"),
            _df.round(2),
            mo.md("**H2 pipeline trade [TWh/a]**"),
            _trade_df.round(2),
            _summary.round(1),
        ]
    )
    return


@app.cell
def _(mo):
    # 26 Import von grünem Wasserstoff / Stahl
    mo.md("## 26 Import von grünem Wasserstoff / Stahl — not modelled (will be integrated later)")
    return


if __name__ == "__main__":
    app.run()

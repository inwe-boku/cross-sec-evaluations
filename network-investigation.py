import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pypsa 
    import pandas as pd
    import os

    return mo, os, pd, pypsa


@app.cell
def _(os, pypsa):
    nw_path = "/home/maxnutz/Documents/pypsa-at-validation/pypsa-validation_processing/resources/electricity_network_0p3/networks/"

    nc = pypsa.NetworkCollection([nw_path + n for n in list(os.listdir(nw_path))])
    return (nc,)


@app.cell
def _(nc):
    nc
    return


@app.cell
def _(mo, nc, pd, pypsa):
    def co2_storage_potential_per_country(n: pypsa.Network) -> pd.DataFrame:
        """Annual CO2 sequestration potential per country in Mt CO2/a."""
        seq_cfg = n.meta["sector"]["regional_co2_sequestration_potential"]
        if not seq_cfg["enable"] or not n.meta["sector"]["co2_spatial"]:
            raise ValueError("No regional CO2 sequestration: only one EU-wide store.")

        year = n.meta["wildcards"]["planning_horizons"]
        stores = n.stores[n.stores.carrier == "co2 sequestered"]
        country = stores.bus.map(n.buses.location).str[:2]
        current = stores.index.str.endswith(f"-{year}")  # myopic: older vintages are fixed

        df = pd.DataFrame(
            {
                # e_nom_max of the current vintage = remaining potential in this horizon
                "remaining_potential": stores.e_nom_max.where(current, 0.0),
                # capacity built in earlier horizons (fixed e_nom)
                "built_earlier": stores.e_nom.where(~current, 0.0),
                "optimised": stores.e_nom_opt,
            }
        ).groupby(country).sum().div(1e6)  # t -> Mt
        df.index.name = "country"

        # EU-wide cap (binds across all countries) from config
        eu_cap = n.meta["sector"]["co2_sequestration_potential"][year]
        print(f"EU-wide sequestration cap {year}: {eu_cap} Mt CO2/a")
        return df.reindex(n.meta["countries"], fill_value=0.0).assign(unit="Mt CO2/a")

    mo.md(f"# Gesamte Größe des CO2-Untergrundspeichers in Österreich\n")
    mo.ui.table(co2_storage_potential_per_country(nc[3]))
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()

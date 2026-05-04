"""
FIRE Simulator — Flask server
Run:  python app.py
Open: http://localhost:5051
"""

import json
import os
from flask import Flask, jsonify, request, send_from_directory
from simulator import dict_to_household, run_all_scenarios, results_to_dict

app = Flask(__name__, static_folder=".")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# Percentage fields stored as fractions in config.json; multiply by 100 for the UI.
_PCT_UI_FIELDS = {
    "annual_return", "inflation", "swr",
    "bonus_pct",                        # per-person
    "geo_col_reduction",
}


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _config_for_ui(cfg: dict) -> dict:
    """
    Flatten config.json into the key schema expected by the HTML inputs and
    convert fraction fields → percentage for display (0.07 → 7.0).
    """
    pa = cfg["person_a"]
    pb = cfg["person_b"]
    hh = cfg["household"]

    flat = {
        # person A
        "age_a":          pa["age"],
        "retire_age_a":   pa["retire_age"],
        "base_a":         pa["base_salary"],
        "bonus_pct_a":    pa["bonus_pct"]         * 100,
        "rsu_a":          pa["unvested_rsu"],
        "rsu_years_a":    pa["rsu_vesting_years"],
        "k401_contrib_a": pa["k401_contribution"],
        "k401_a":         pa["k401_balance"],
        "roth_a":         pa["roth_balance"],
        "hsa_a":          pa["hsa_balance"],
        "ss_a":           pa["ss_benefit"],
        # person B
        "age_b":          pb["age"],
        "retire_age_b":   pb["retire_age"],
        "base_b":         pb["base_salary"],
        "bonus_pct_b":    pb["bonus_pct"]         * 100,
        "rsu_b":          pb["unvested_rsu"],
        "rsu_years_b":    pb["rsu_vesting_years"],
        "k401_contrib_b": pb["k401_contribution"],
        "k401_b":         pb["k401_balance"],
        "roth_b":         pb["roth_balance"],
        "hsa_b":          pb["hsa_balance"],
        "ss_b":           pb["ss_benefit"],
        # household
        "life_expectancy":  hh["life_expectancy"],
        "state":            hh["state"],
        "brokerage":        hh["brokerage_balance"],
        "cash":             hh["cash_balance"],
        "home_value":       hh["home_value"],
        "mortgage_bal":     hh["mortgage_balance"],
        "mortgage_pmt":     hh["mortgage_monthly_payment"],
        "sell_home":        hh["sell_home_at_retirement"],
        "expenses_now":     hh["annual_expenses_current"],
        "expenses_ret":     hh["annual_expenses_retirement"],
        "annual_return":    hh["annual_return"]      * 100,
        "inflation":        hh["inflation"]          * 100,
        "swr":              hh["swr"]                * 100,
        "ss_start_age":     hh["ss_start_age"],
        "model_healthcare": hh["model_healthcare"],
        "include_kids":     hh["include_kids"],
        "kids_count":       hh["kids_count"],
        "kids_start_years": hh["kids_start_years"],
        "geo_col_reduction":hh["geo_col_reduction"]  * 100,
    }
    return flat


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/config")
def get_config():
    """Serve UI-ready (percentage, not fraction) defaults from config.json."""
    try:
        return jsonify(_config_for_ui(_load_config()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/simulate", methods=["POST"])
def simulate():
    data = request.get_json(force=True)
    try:
        params    = dict_to_household(data)
        scenarios = run_all_scenarios(params)
        return jsonify(results_to_dict(params, scenarios))
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5051))
    print(f"FIRE Simulator running at http://localhost:{port}")
    app.run(debug=True, port=port)

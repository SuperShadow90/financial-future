"""
FIRE Simulator — Flask server
Run:  python app.py
Open: http://localhost:5051
"""

import os
from flask import Flask, jsonify, request, send_from_directory
from simulator import dict_to_household, run_all_scenarios, results_to_dict

app = Flask(__name__, static_folder=".")


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


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

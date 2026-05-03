# FIRE Simulator

Interactive FIRE (Financial Independence, Retire Early) simulator for a dual-income tech household.

## Features

- **10 scenarios**: Base case, Sequential FIRE, Kids, Lean, Fat, Sequence-of-returns risk, Coast FIRE, Geographic arbitrage, Mortgage payoff, Layoff disruption
- **Dual-income modeling**: Base salary, bonus, RSU vesting, 401(k), Roth IRA, HSA per person
- **Tax-aware**: Federal + state income tax, marginal RSU taxation
- **Healthcare**: ACA pre-65, Medicare post-65 cost projections
- **Social Security**: Included with 20% funding haircut

## Stack

- `simulator.py` — pure Python simulation logic (no web dependencies)
- `app.py` — Flask API server
- `index.html` — interactive UI (Chart.js)

## Usage

```bash
pip install flask
python app.py
# Open http://localhost:5051
```

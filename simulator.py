"""
FIRE Simulator — core logic for a dual-income tech couple.

Scenarios modelled (S1–S10):
  S1  Base case
  S2  Sequential FIRE (Person A retires first, B works 3 more years)
  S3  Kids
  S4  Lean FIRE  (30 % lower retirement spend)
  S5  Fat FIRE   ($150K+/yr)
  S6  Sequence-of-returns risk (35 % crash year 1 of retirement)
  S7  Coast FIRE check
  S8  Geographic arbitrage
  S9  Mortgage paid off before retiring
  S10 Layoff disruption (Person A, 12 months)

All dollar values are nominal unless labelled _real.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json, os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _load_config() -> dict:
    """Load config.json; return empty dict if missing."""
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# ─────────────────────────────────────────────────────────
# Tax helpers
# ─────────────────────────────────────────────────────────

STATE_TAX: dict[str, float] = {
    "CA": 0.093, "NY": 0.0685, "OR": 0.090, "MN": 0.0985,
    "WA": 0.000, "TX": 0.000,  "FL": 0.000, "NV": 0.000,
    "AZ": 0.025, "CO": 0.044,  "GA": 0.055, "NC": 0.0499,
    "MA": 0.050, "IL": 0.0495, "OH": 0.040, "MI": 0.0425,
    "VA": 0.0575,"PA": 0.0307, "NJ": 0.0637,"CT": 0.0699,
}

def _federal_eff_rate(gross: float) -> float:
    """Simplified federal effective income tax rate."""
    if gross <= 100_000:  return 0.18
    if gross <= 200_000:  return 0.22
    if gross <= 400_000:  return 0.28
    if gross <= 700_000:  return 0.32
    return 0.35

def _state_rate(state: str) -> float:
    return STATE_TAX.get(state.upper(), 0.05)

def income_after_tax(gross: float, state: str) -> float:
    rate = min(_federal_eff_rate(gross) + _state_rate(state), 0.55)
    return gross * (1.0 - rate)

def rsu_after_tax(gross: float, state: str) -> float:
    """RSUs taxed as ordinary income at marginal federal rate (37 %)."""
    rate = min(0.37 + _state_rate(state), 0.58)
    return gross * (1.0 - rate)


# ─────────────────────────────────────────────────────────
# Healthcare cost estimates
# ─────────────────────────────────────────────────────────

def healthcare_annual(age_a: int, age_b: int) -> float:
    """
    Pre-65  : ACA marketplace ~ $1 200/mo per person (no subsidy assumed).
    65+     : Medicare + Medigap ~ $450/mo per person.
    """
    cost = 0.0
    for age in (age_a, age_b):
        cost += 5_400 if age >= 65 else 14_400
    return cost


# ─────────────────────────────────────────────────────────
# Kids cost estimates
# ─────────────────────────────────────────────────────────

def kids_cost_annual(years_from_now: int, count: int, start_year: int) -> float:
    """
    Cost per child (today's dollars):
      Ages  0–5   $20 K/yr
      Ages  6–17  $15 K/yr
      Ages 18–21  $40 K/yr  (college)
    Children staggered by 1 year each.
    """
    total = 0.0
    for k in range(count):
        birth_yr = start_year + k
        kid_age  = years_from_now - birth_yr
        if   kid_age < 0:   pass
        elif kid_age <= 5:  total += 20_000
        elif kid_age <= 17: total += 15_000
        elif kid_age <= 21: total += 40_000
    return total


# ─────────────────────────────────────────────────────────
# Data classes — inputs
# ─────────────────────────────────────────────────────────

@dataclass
class PersonParams:
    name: str   = "Person A"
    age: int    = 36
    retire_age: int = 50

    # Compensation (gross annual)
    base_salary: float      = 200_000
    bonus_target_pct: float = 0.15      # fraction; realistic payout = 80 % of target

    # RSUs (unvested, today's dollar value)
    unvested_rsu: float    = 200_000
    rsu_vesting_years: int = 4          # years until fully vested

    # Account balances
    k401_balance: float = 200_000
    roth_balance: float =  50_000
    hsa_balance: float  =  10_000

    # Annual contributions
    k401_contribution: float = 23_500   # 2026 IRS limit
    hsa_contribution: float  =  4_275   # half of $8 550 family limit

    # Social Security (today's dollars, at full retirement age, before haircut)
    ss_benefit: float = 24_000


@dataclass
class HouseholdParams:
    person_a: PersonParams = field(default_factory=PersonParams)
    person_b: PersonParams = field(
        default_factory=lambda: PersonParams(name="Person B", age=36, retire_age=50,
                                             base_salary=180_000, unvested_rsu=150_000,
                                             k401_balance=150_000, roth_balance=40_000,
                                             ss_benefit=20_000)
    )

    life_expectancy: int = 90
    state: str = "CA"

    # Shared liquid assets
    brokerage_balance: float = 300_000
    cash_balance: float      = 100_000

    # Primary residence
    home_value: float               = 1_500_000
    mortgage_balance: float         =   800_000
    mortgage_monthly_payment: float =     5_000
    mortgage_years_remaining: int   =        25
    sell_home_at_retirement: bool   = False

    # Expenses (today's dollars)
    annual_expenses_current: float    = 120_000   # current total HH spend (excl mortgage principal)
    annual_expenses_retirement: float = 200_000   # target retirement spend

    # Market assumptions
    annual_return: float = 0.07
    inflation: float     = 0.03
    swr: float           = 0.035

    # Social Security
    ss_start_age: int = 67

    # Healthcare modelling
    model_healthcare: bool = True

    # Kids (optional)
    include_kids: bool    = False
    kids_count: int       = 1
    kids_start_years: int = 2      # years from now until first child

    # Geographic arbitrage COL reduction
    geo_col_reduction: float = 0.35


# ─────────────────────────────────────────────────────────
# Data classes — outputs
# ─────────────────────────────────────────────────────────

@dataclass
class YearSnapshot:
    year: int            # years from now
    age_a: int
    age_b: int
    portfolio: float     # nominal
    real_portfolio: float
    contribution: float  # net portfolio addition (accumulation phase)
    withdrawal: float    # net portfolio subtraction (retirement phase)
    a_retired: bool
    b_retired: bool
    fire_reached: bool   = False
    depleted: bool       = False
    rsu_income: float    = 0.0
    healthcare_cost: float = 0.0


@dataclass
class ScenarioResult:
    name: str
    description: str
    fire_number: float
    fire_reached_year: Optional[int]    # years from now; None if never
    fire_age_a: Optional[int]
    fire_age_b: Optional[int]
    depletion_age_a: Optional[int]
    coast_fire_number: float
    coast_fire_reached: bool
    end_portfolio: float
    end_portfolio_real: float
    forfeited_rsu: float
    years: list[YearSnapshot] = field(default_factory=list)


# ─────────────────────────────────────────────────────────
# Portfolio helpers
# ─────────────────────────────────────────────────────────

def liquid_portfolio(p: HouseholdParams) -> float:
    """Starting liquid investable assets (home equity excluded)."""
    return (
        p.person_a.k401_balance + p.person_a.roth_balance + p.person_a.hsa_balance
        + p.person_b.k401_balance + p.person_b.roth_balance + p.person_b.hsa_balance
        + p.brokerage_balance + p.cash_balance
    )


def _rsu_net_this_year(person: PersonParams, yr: int, state: str) -> float:
    if person.rsu_vesting_years <= 0 or yr >= person.rsu_vesting_years:
        return 0.0
    gross = person.unvested_rsu / person.rsu_vesting_years
    return rsu_after_tax(gross, state)


def _w2_net_annual(person: PersonParams, state: str) -> float:
    """After-tax W-2 income (base + realistic bonus), after 401 k + HSA deductions."""
    bonus    = person.base_salary * person.bonus_target_pct * 0.80
    gross    = person.base_salary + bonus
    taxable  = gross - person.k401_contribution - person.hsa_contribution
    net      = income_after_tax(taxable, state)
    # 401 k + HSA are still saved (pre-tax); add back as portfolio contributions
    return net + person.k401_contribution + person.hsa_contribution


def _rsu_forfeited(person: PersonParams, retire_age: int) -> float:
    if person.rsu_vesting_years <= 0:
        return 0.0
    years_worked = retire_age - person.age
    unvested_pct = max(0.0, 1.0 - years_worked / person.rsu_vesting_years)
    return person.unvested_rsu * unvested_pct


# ─────────────────────────────────────────────────────────
# Core simulation engine
# ─────────────────────────────────────────────────────────

def simulate(
    p: HouseholdParams,
    name: str        = "S1 Base",
    description: str = "",
    # ── Scenario overrides ──
    retire_age_a_override: Optional[int]   = None,
    retire_age_b_override: Optional[int]   = None,
    retirement_expense_override: Optional[float] = None,
    annual_return_override: Optional[float] = None,
    crash_on_year: Optional[int]            = None,   # year-index of 35 % crash
    layoff_who: Optional[str]               = None,   # "a" | "b" | "both"
    layoff_start_yr: int                    = 1,
    layoff_duration: int                    = 1,
    home_sale_override: Optional[bool]      = None,
    kids_override: Optional[bool]           = None,
) -> ScenarioResult:

    pa = p.person_a
    pb = p.person_b

    retire_a   = retire_age_a_override   if retire_age_a_override   is not None else pa.retire_age
    retire_b   = retire_age_b_override   if retire_age_b_override   is not None else pb.retire_age
    ret_exp    = retirement_expense_override if retirement_expense_override is not None else p.annual_expenses_retirement
    r_nominal  = annual_return_override  if annual_return_override   is not None else p.annual_return
    sell_home  = home_sale_override      if home_sale_override       is not None else p.sell_home_at_retirement
    do_kids    = kids_override           if kids_override            is not None else p.include_kids

    fire_number        = ret_exp / p.swr
    years_to_retire_a  = max(retire_a - pa.age, 1)
    coast_fire_number  = fire_number / ((1 + r_nominal) ** years_to_retire_a)

    portfolio     = liquid_portfolio(p)
    mortgage_bal  = p.mortgage_balance
    home_sold     = False

    coast_reached      = portfolio >= coast_fire_number
    fire_reached_year: Optional[int] = None
    fire_age_a:        Optional[int] = None
    fire_age_b:        Optional[int] = None
    depletion_year:    Optional[int] = None

    years: list[YearSnapshot] = []
    end_age = max(p.life_expectancy, retire_a, retire_b)

    for yr in range(end_age - pa.age + 2):
        age_a = pa.age + yr
        age_b = pb.age + yr
        if age_a > p.life_expectancy and age_b > p.life_expectancy:
            break

        infl   = (1 + p.inflation) ** yr
        a_ret  = age_a >= retire_a
        b_ret  = age_b >= retire_b
        both   = a_ret and b_ret

        a_off  = (layoff_who in ("a", "both") and layoff_start_yr <= yr < layoff_start_yr + layoff_duration)
        b_off  = (layoff_who in ("b", "both") and layoff_start_yr <= yr < layoff_start_yr + layoff_duration)

        # RSU vesting (forfeited if retired or laid off)
        rsu_a = 0.0 if (a_ret or a_off) else _rsu_net_this_year(pa, yr, p.state)
        rsu_b = 0.0 if (b_ret or b_off) else _rsu_net_this_year(pb, yr, p.state)

        # Annual return (crash scenario)
        this_r = -0.35 if (crash_on_year is not None and yr == crash_on_year) else r_nominal

        # Mortgage amortisation
        if mortgage_bal > 0:
            payment      = min(p.mortgage_monthly_payment * 12, mortgage_bal)
            mortgage_bal = max(0.0, mortgage_bal - payment)
        else:
            payment = 0.0

        # Healthcare cost (in retirement only)
        hc_cost = healthcare_annual(age_a, age_b) * infl if (both and p.model_healthcare) else 0.0

        # ── Accumulation phase ───────────────────────────────
        if not both:
            inc_a = _w2_net_annual(pa, p.state) if (not a_ret and not a_off) else 0.0
            inc_b = _w2_net_annual(pb, p.state) if (not b_ret and not b_off) else 0.0

            kids_cost = kids_cost_annual(yr, p.kids_count, p.kids_start_years) * infl if do_kids else 0.0
            total_expenses = p.annual_expenses_current * infl + kids_cost

            # Mortgage principal repayment is a balance-sheet transfer, not an expense;
            # only add the mortgage payment as cash outflow if it's not already in expenses.
            # (Assume annual_expenses_current includes the interest portion.)
            net_contrib = inc_a + inc_b + rsu_a + rsu_b - total_expenses

            portfolio = portfolio * (1 + this_r) + net_contrib
            contribution = max(0.0, net_contrib)
            withdrawal   = 0.0

        # ── Withdrawal phase ─────────────────────────────────
        else:
            # One-time home sale at start of retirement
            if sell_home and not home_sold:
                net_proceeds = max(0.0, p.home_value - p.mortgage_balance) * 0.92
                portfolio   += net_proceeds
                home_sold    = True

            ss_a = pa.ss_benefit * infl * 0.80 if age_a >= p.ss_start_age else 0.0
            ss_b = pb.ss_benefit * infl * 0.80 if age_b >= p.ss_start_age else 0.0

            gross_need    = ret_exp * infl + hc_cost + payment
            net_withdraw  = max(0.0, gross_need - ss_a - ss_b)

            portfolio    = portfolio * (1 + this_r) - net_withdraw
            contribution = 0.0
            withdrawal   = net_withdraw

        # ── Milestones ───────────────────────────────────────
        fire_nom       = fire_number * infl
        fire_this_year = False
        if fire_reached_year is None and portfolio >= fire_nom:
            fire_reached_year = yr
            fire_age_a        = age_a
            fire_age_b        = age_b
            fire_this_year    = True

        depleted = False
        if depletion_year is None and both and portfolio <= 0:
            depletion_year = yr
            depleted       = True
            portfolio      = 0.0

        real_port = portfolio / infl

        years.append(YearSnapshot(
            year=yr,
            age_a=age_a,
            age_b=age_b,
            portfolio=max(0.0, portfolio),
            real_portfolio=max(0.0, real_port),
            contribution=contribution,
            withdrawal=withdrawal,
            a_retired=a_ret,
            b_retired=b_ret,
            fire_reached=fire_this_year,
            depleted=depleted,
            rsu_income=rsu_a + rsu_b,
            healthcare_cost=hc_cost,
        ))

    forfeited = _rsu_forfeited(pa, retire_a) + _rsu_forfeited(pb, retire_b)
    end_snap  = years[-1] if years else None
    dep_age_a = (pa.age + depletion_year) if depletion_year is not None else None

    return ScenarioResult(
        name=name,
        description=description,
        fire_number=fire_number,
        fire_reached_year=fire_reached_year,
        fire_age_a=fire_age_a,
        fire_age_b=fire_age_b,
        depletion_age_a=dep_age_a,
        coast_fire_number=coast_fire_number,
        coast_fire_reached=coast_reached,
        end_portfolio=end_snap.portfolio      if end_snap else 0.0,
        end_portfolio_real=end_snap.real_portfolio if end_snap else 0.0,
        forfeited_rsu=forfeited,
        years=years,
    )


# ─────────────────────────────────────────────────────────
# All 10 scenarios
# ─────────────────────────────────────────────────────────

def run_all_scenarios(p: HouseholdParams) -> dict[str, ScenarioResult]:
    pa, pb = p.person_a, p.person_b
    lean   = p.annual_expenses_retirement * 0.70
    fat    = max(p.annual_expenses_retirement * 1.50, 150_000)
    geo    = p.annual_expenses_retirement * (1 - p.geo_col_reduction)
    # Mortgage-free retirement: rough estimate (remove mortgage interest portion ~60 % of payment)
    no_mtg = max(p.annual_expenses_retirement - p.mortgage_monthly_payment * 12 * 0.60, lean)
    crash_yr = max(pa.retire_age - pa.age, 1)

    return {
        "s1": simulate(p,
            "S1 · Base Case",
            "Both work until portfolio hits FIRE number. No kids."),

        "s2": simulate(p,
            "S2 · Sequential FIRE",
            f"{pa.name} retires at {pa.retire_age}; {pb.name} works 3 more years.",
            retire_age_b_override=pb.retire_age + 3),

        "s3": simulate(p,
            "S3 · With Kids",
            f"{p.kids_count} child starting in {p.kids_start_years} yr(s). "
            "$20 K ages 0–5 · $15 K ages 6–17 · $40 K college.",
            kids_override=True),

        "s4": simulate(p,
            "S4 · Lean FIRE",
            f"Retirement spend reduced to ${lean:,.0f}/yr (−30 %).",
            retirement_expense_override=lean),

        "s5": simulate(p,
            "S5 · Fat FIRE",
            f"Target ${fat:,.0f}/yr retirement spend.",
            retirement_expense_override=fat),

        "s6": simulate(p,
            "S6 · Sequence-of-Returns Risk",
            "35 % market crash in year 1 of retirement.",
            crash_on_year=crash_yr),

        "s7": simulate(p,
            "S7 · Coast FIRE",
            "Base projection — coast FIRE status flagged in summary."),

        "s8": simulate(p,
            "S8 · Geographic Arbitrage",
            f"{int(p.geo_col_reduction * 100)} % COL reduction → ${geo:,.0f}/yr.",
            retirement_expense_override=geo),

        "s9": simulate(p,
            "S9 · Mortgage Paid Off",
            f"Mortgage cleared before retiring; retirement spend ≈ ${no_mtg:,.0f}/yr.",
            retirement_expense_override=no_mtg),

        "s10": simulate(p,
            "S10 · Layoff Disruption",
            f"{pa.name} laid off 12 months (year 1). No income or RSU vesting.",
            layoff_who="a", layoff_start_yr=1, layoff_duration=1),
    }


# ─────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────

def _scenario_to_dict(r: ScenarioResult) -> dict:
    return {
        "name":               r.name,
        "description":        r.description,
        "fire_number":        r.fire_number,
        "fire_reached_year":  r.fire_reached_year,
        "fire_age_a":         r.fire_age_a,
        "fire_age_b":         r.fire_age_b,
        "depletion_age_a":    r.depletion_age_a,
        "coast_fire_number":  r.coast_fire_number,
        "coast_fire_reached": r.coast_fire_reached,
        "end_portfolio":      r.end_portfolio,
        "end_portfolio_real": r.end_portfolio_real,
        "forfeited_rsu":      r.forfeited_rsu,
        "years": [
            {
                "year":           y.year,
                "age_a":          y.age_a,
                "age_b":          y.age_b,
                "portfolio":      y.portfolio,
                "real_portfolio": y.real_portfolio,
                "contribution":   y.contribution,
                "withdrawal":     y.withdrawal,
                "a_retired":      y.a_retired,
                "b_retired":      y.b_retired,
                "fire_reached":   y.fire_reached,
                "depleted":       y.depleted,
                "rsu_income":     y.rsu_income,
                "healthcare_cost":y.healthcare_cost,
            }
            for y in r.years
        ],
    }


def results_to_dict(p: HouseholdParams, scenarios: dict[str, ScenarioResult]) -> dict:
    """Package household summary + all scenario results for JSON."""
    pa, pb   = p.person_a, p.person_b
    base     = scenarios["s1"]
    liq_nw   = liquid_portfolio(p)
    hc_pre65 = healthcare_annual(pa.age, pb.age)   # today's estimate

    return {
        "household": {
            "liquid_net_worth":    liq_nw,
            "home_equity":         p.home_value - p.mortgage_balance,
            "total_net_worth":     liq_nw + (p.home_value - p.mortgage_balance),
            "unvested_rsu_total":  pa.unvested_rsu + pb.unvested_rsu,
            "fire_number_base":    p.annual_expenses_retirement / p.swr,
            "gap_to_fire":         max(0.0, p.annual_expenses_retirement / p.swr - liq_nw),
            "annual_savings_est":  (
                _w2_net_annual(pa, p.state) + _w2_net_annual(pb, p.state)
                - p.annual_expenses_current
            ),
            "healthcare_pre65_annual": hc_pre65,
            "coast_fire_number":   base.coast_fire_number,
            "coast_fire_reached":  base.coast_fire_reached,
        },
        "scenarios": {k: _scenario_to_dict(v) for k, v in scenarios.items()},
    }


# ─────────────────────────────────────────────────────────
# Parse API payload → HouseholdParams
# ─────────────────────────────────────────────────────────

def dict_to_household(d: dict) -> HouseholdParams:
    """
    Build HouseholdParams from an API request dict.
    Priority: request values → config.json → hardcoded fallbacks.
    config.json stores fractions for % fields (0.07 = 7 %); the API receives
    the same fraction format (collectParams divides by 100 before POSTing).
    """
    cfg  = _load_config()
    ca   = cfg.get("person_a",  {})
    cb   = cfg.get("person_b",  {})
    chh  = cfg.get("household", {})

    def va(key, fb):   return d.get(key,         ca.get(key,  fb))
    def vb(key, fb):   return d.get(key,         cb.get(key,  fb))
    def vh(key, fb):   return d.get(key,         chh.get(key, fb))

    pa = PersonParams(
        name              = "Person A",
        age               = int(va("age_a",             36)),
        retire_age        = int(va("retire_age_a",       50)),
        base_salary       = float(va("base_a",      200_000)),
        bonus_target_pct  = float(va("bonus_pct_a",    0.15)),
        unvested_rsu      = float(va("rsu_a",       200_000)),
        rsu_vesting_years = int(va("rsu_years_a",         4)),
        k401_balance      = float(va("k401_a",      200_000)),
        roth_balance      = float(va("roth_a",       50_000)),
        hsa_balance       = float(va("hsa_a",        10_000)),
        k401_contribution = float(va("k401_contrib_a", 23_500)),
        hsa_contribution  = float(ca.get("hsa_contribution", 4_275)),
        ss_benefit        = float(va("ss_a",          24_000)),
    )
    pb = PersonParams(
        name              = "Person B",
        age               = int(vb("age_b",             36)),
        retire_age        = int(vb("retire_age_b",       50)),
        base_salary       = float(vb("base_b",      180_000)),
        bonus_target_pct  = float(vb("bonus_pct_b",    0.15)),
        unvested_rsu      = float(vb("rsu_b",       150_000)),
        rsu_vesting_years = int(vb("rsu_years_b",         4)),
        k401_balance      = float(vb("k401_b",      150_000)),
        roth_balance      = float(vb("roth_b",       40_000)),
        hsa_balance       = float(vb("hsa_b",         8_000)),
        k401_contribution = float(vb("k401_contrib_b", 23_500)),
        hsa_contribution  = float(cb.get("hsa_contribution", 4_275)),
        ss_benefit        = float(vb("ss_b",          20_000)),
    )
    return HouseholdParams(
        person_a                 = pa,
        person_b                 = pb,
        life_expectancy          = int(vh("life_expectancy",       90)),
        state                    = str(vh("state",               "CA")),
        brokerage_balance        = float(vh("brokerage",      300_000)),
        cash_balance             = float(vh("cash",           100_000)),
        home_value               = float(vh("home_value",   1_500_000)),
        mortgage_balance         = float(vh("mortgage_bal",   800_000)),
        mortgage_monthly_payment = float(vh("mortgage_pmt",     5_000)),
        mortgage_years_remaining = int(chh.get("mortgage_years_remaining", 25)),
        sell_home_at_retirement  = bool(vh("sell_home",          False)),
        annual_expenses_current  = float(vh("expenses_now",   120_000)),
        annual_expenses_retirement = float(vh("expenses_ret", 200_000)),
        annual_return            = float(vh("annual_return",     0.07)),
        inflation                = float(vh("inflation",         0.03)),
        swr                      = float(vh("swr",               0.035)),
        ss_start_age             = int(vh("ss_start_age",           67)),
        model_healthcare         = bool(vh("model_healthcare",    True)),
        include_kids             = bool(vh("include_kids",        False)),
        kids_count               = int(vh("kids_count",              1)),
        kids_start_years         = int(vh("kids_start_years",        2)),
        geo_col_reduction        = float(vh("geo_col_reduction",  0.35)),
    )

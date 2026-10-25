"""Simultaneous reserve products share one physical response trajectory."""

from pathlib import Path

import pulp as pl
import pytest

from mms.stochastic.data import PRODUCTS, load
from mms.stochastic.model import build_model


ROOT = Path(__file__).resolve().parents[1]


def reserve_case(deadlines, amounts, direction="plus", linked=True):
    data = load(ROOT / "examples/small_stochastic.json")
    data["stochastic"]["reserve_link"] = linked
    for product, deadline in zip(PRODUCTS, deadlines):
        data["stochastic"]["reserve_products"][product]["response_minutes"] = deadline
    model = build_model(data)
    for product, amount in zip(PRODUCTS, amounts):
        model.problem += model.shared[f"{product}_ActPR_{direction}1_1"] == amount
    model.problem.solve(pl.HiGHS(msg=False, threads=1, gapRel=0))
    return model


@pytest.mark.parametrize("direction", ["plus", "minus"])
def test_equal_deadline_products_cannot_reuse_ramp_capability(direction):
    # Each individual 1 MW reserve fits a 1 MW/min ramp in one minute;
    # the simultaneous 3 MW call cannot be delivered in that minute.
    model = reserve_case([1, 1, 1], [1, 1, 1], direction)
    assert model.problem.status == pl.LpStatusInfeasible


def test_faster_product_consumes_later_deadline_capability():
    # 0.75 + 1.5 MW by minute two exceeds 2 MW, although each individual
    # bound and the final minute-four aggregate bound would be satisfied.
    model = reserve_case([1, 2, 4], [0.75, 1.5, 0])
    assert model.problem.status == pl.LpStatusInfeasible


def test_later_products_do_not_consume_earlier_deadline_capability():
    # Correctly group by deadline rather than putting all 4 MW in minute one.
    model = reserve_case([1, 2, 4], [0.5, 1.5, 2])
    assert model.problem.status == pl.LpStatusOptimal


def test_reserve_response_strengthening_requires_explicit_linkage():
    model = reserve_case([1, 1, 1], [1, 1, 1], linked=False)
    assert model.problem.status == pl.LpStatusOptimal
    assert not any("reserve_response_" in name for name in model.problem.constraints)

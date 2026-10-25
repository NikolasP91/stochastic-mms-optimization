"""Numerical and model-building utilities shared by the PuLP MIP formulation."""

import re
import time
import warnings
from contextlib import contextmanager


def _collect_numeric_values(value):
    """Recursively collect absolute numeric values from nested input data."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [abs(value)]
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_collect_numeric_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_collect_numeric_values(item))
        return values
    return []


def estimate_big_m(input_data, data, intervals):
    """Estimate a scenario-scaled fallback big-M from physical and cost magnitudes."""
    load_bound = max(_collect_numeric_values(input_data.get("Load_forecast", [])) or [0])
    availability_by_period = []
    for t in intervals[1:]:
        period_availability = 0
        for unit in data:
            availability = unit.get("availability", [])
            if isinstance(availability, list) and t - 1 < len(availability):
                period_availability += abs(availability[t - 1])
        availability_by_period.append(period_availability)
    total_availability_bound = max(availability_by_period or [0])

    unit_physical_values = []
    transition_cost_values = []
    for unit in data:
        for key in (
            "availability",
            "max_power(MW)",
            "min_power(MW)",
            "current_Power(MW)",
            "Production_Forecast",
            "Primary_Active_Power_Reserves(MW)",
            "Secondary_Active_Power_Reserves(MW)",
            "Tertiary_Active_Power_Reserves(MW)",
        ):
            unit_physical_values.extend(_collect_numeric_values(unit.get(key)))
        for operating_state in unit.get("operating-states", []):
            for key in ("max-power", "min-power", "user_max_power", "user_min_power"):
                unit_physical_values.extend(_collect_numeric_values(operating_state.get(key)))
        for transition in unit.get("operating-state-transitions", []):
            for to_state in transition.get("transitions", []):
                transition_cost_values.extend(_collect_numeric_values(to_state.get("transition-cost")))

    bound_source = max(
        [load_bound, total_availability_bound]
        + unit_physical_values
        + transition_cost_values
        + [1]
    )
    return max(1000.0, 1.25 * bound_source)


def _clean_name(value):
    """Convert arbitrary text into a safe constraint-name fragment."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "section"


@contextmanager
def _suppress_pulp_constraint_mapping_warnings():
    """Temporarily silence PuLP mapping deprecation warnings during constraint bookkeeping."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using LpProblem.constraints as a dict mapping is deprecated.*",
            category=DeprecationWarning,
        )
        yield


class ConstraintBuildTracker:
    """Track and name constraints added by model-building sections."""

    def __init__(self, prob, prefix="mms"):
        self.prob = prob
        self.prefix = prefix
        self._records = []

    @contextmanager
    def section(self, name):
        safe_name = _clean_name(name)
        with _suppress_pulp_constraint_mapping_warnings():
            before_constraints = set(self.prob.constraints)
            before_num_constraints = self.prob.numConstraints()
            before_num_variables = self.prob.numVariables()
        start_time = time.time()
        yield
        elapsed_seconds = time.time() - start_time

        with _suppress_pulp_constraint_mapping_warnings():
            new_constraint_names = [
                constraint_name
                for constraint_name in list(self.prob.constraints)
                if constraint_name not in before_constraints
            ]
            renamed = self._rename_new_anonymous_constraints(
                new_constraint_names,
                f"{self.prefix}_{safe_name}",
            )
            constraints_added = self.prob.numConstraints() - before_num_constraints
            variables_added = self.prob.numVariables() - before_num_variables
        self._records.append(
            {
                "section": safe_name,
                "constraints_added": constraints_added,
                "variables_added": variables_added,
                "anonymous_constraints_named": renamed,
                "build_seconds": round(elapsed_seconds, 6),
            }
        )

    def summary(self):
        return list(self._records)

    def _rename_new_anonymous_constraints(self, constraint_names, prefix):
        with _suppress_pulp_constraint_mapping_warnings():
            existing_names = set(self.prob.constraints)
            reserved_names = set()
            rename_map = {}
            local_index = 1
            for old_name in constraint_names:
                if old_name not in self.prob.constraints or not old_name.startswith("_C"):
                    continue

                new_name = self._unique_name(
                    f"{prefix}_{local_index:06d}",
                    existing_names | reserved_names,
                )
                rename_map[old_name] = new_name
                reserved_names.add(new_name)
                local_index += 1

            if not rename_map:
                return 0

            constraint_items = list(self.prob.constraints.items())
            self.prob.constraints.clear()
            for constraint_name, constraint in constraint_items:
                new_name = rename_map.get(constraint_name)
                if new_name:
                    constraint.name = new_name
                    self.prob.constraints[new_name] = constraint
                else:
                    self.prob.constraints[constraint_name] = constraint

        return len(rename_map)

    @staticmethod
    def _unique_name(base_name, unavailable_names):
        candidate = base_name
        suffix = 1
        while candidate in unavailable_names:
            suffix += 1
            candidate = f"{base_name}_{suffix}"
        return candidate


def name_auto_constraints(prob, prefix="mms_auto"):
    """Assign stable names to any remaining anonymous PuLP constraints."""
    with _suppress_pulp_constraint_mapping_warnings():
        renamed = {}
        renamed_count = 0
        auto_index = 1
        for name, constraint in list(prob.constraints.items()):
            if name.startswith("_C"):
                new_name = f"{prefix}_{auto_index:06d}"
                while new_name in prob.constraints:
                    auto_index += 1
                    new_name = f"{prefix}_{auto_index:06d}"
                constraint.name = new_name
                renamed[new_name] = constraint
                renamed_count += 1
                auto_index += 1
            else:
                renamed[name] = constraint
        prob.constraints.clear()
        prob.constraints.update(renamed)
    return renamed_count

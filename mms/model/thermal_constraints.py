"""Thermal-unit ramping, availability, mode, forbidden-zone, and variable-cost constraints."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import numpy as np
import pandas as pd
import pulp as pl

from mms.cost_curves import cost_curve_time_multiplier, parse_thermal_cost_curve
from mms.model.bounds import forbidden_zone_big_m


def create_forbidden_zones_constraint(prob, objective_terms, input_data, power, data, intervals, CONV, M):
    """Add thermal forbidden-zone disjunctions and relaxation penalties."""
    y_zone = [[[pl.LpVariable(f'y_zone_{i + 1}_{t}_{idx}', 0, 1, cat='Binary') for idx, _ in
                enumerate(gen["forbidden_zones"])] for t in intervals] for i, gen in enumerate(data)]
    s_forbidden_zones_plus = [[pl.LpVariable(name=f's_forbidden_zones_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]
    s_forbidden_zones_minus = [[pl.LpVariable(name=f's_forbidden_zones_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]

    # M = 10000
    for i, gen in enumerate(data):
        for t in intervals[1:]:
            if i in CONV:
                if data[i]["forbidden_zones"] == []:
                    pass  # Do nothing if there are no forbidden zones
                else:
                    for idx, zone in enumerate(data[i]["forbidden_zones"]):
                        # if len(zone) == 2:
                        # print(zone[0])
                        # print(zone[1])
                        lower_bound = zone[0]  # Unpack the bounds of the forbidden zone
                        upper_bound = zone[1]
                        zone_m = forbidden_zone_big_m(data[i], zone, t - 1, M)
                        prob += power[i][t] - s_forbidden_zones_minus[i][t] <= lower_bound + zone_m * y_zone[i][t][idx]  # prob += power[i][t] <= lower_bound - 0.001 + M * y_zone[i][t][idx]
                        prob += power[i][t] + s_forbidden_zones_plus[i][t] >= upper_bound - zone_m * (1 - y_zone[i][t][idx])  # prob += power[i][t] >= upper_bound + 0.001 - M * (1 - y_zone[i][t][idx])
                        # else:
                        #
                        #     print(f"Warning: Skipping invalid forbidden zone {zone} for unit {i}"
                    objective_terms += s_forbidden_zones_plus[i][t] * input_data["Cost_parameters"]["x_forbidden_zones"] + s_forbidden_zones_minus[i][t] * input_data["Cost_parameters"]["x_forbidden_zones"]
    return prob, objective_terms, y_zone, s_forbidden_zones_plus, s_forbidden_zones_minus


def create_ramp_up_down_constraints(input_data, prob, power, data, intervals, objective_terms):
    """Add thermal ramp-up and ramp-down constraints with relaxation variables."""
    ramp_relax = [[pl.LpVariable(name=f'ramp_relax_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]

    for i, gen in enumerate(data):
        for t in intervals[1:]:
            prob += power[i][t] - power[i][t - 1] <= gen['ramp_up_rate(kW/min)'] * (input_data["Time_granularity"]/1000) + ramp_relax[i][t]
            prob += power[i][t - 1] - power[i][t] <= gen['ramp_down_rate(kW/min)'] * (input_data["Time_granularity"]/1000) + ramp_relax[i][t]
            # prob += ramp_relax[i][t] == 0
            objective_terms += ramp_relax[i][t] * input_data["Cost_parameters"]["x_ramp"]
    return prob, ramp_relax, objective_terms


def create_mustRun_constraints(prob, objective_terms, input_data, data, intervals, state):
    """Add must-run unit constraints and their diagnostic slacks."""
    s_must_run = [[pl.LpVariable(name=f's_must_run_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    for gen in data:
        gen_id = gen["gen_id"]
        for t in intervals[1:]:
            if data[gen_id]["mustRun"][t - 1] == 1:
                prob += state[gen_id][t] + s_must_run[gen_id][t] == 1
                #  >= data[i]["mustRun"][t - 1] constraint changed to explicit from implicit
            objective_terms += s_must_run[gen_id][t] * input_data["Cost_parameters"]["x_must_run"]
    return prob, objective_terms, s_must_run


def create_variable_cost_curve_calculation_constraints(input_data, prob, objective_terms, power, data, intervals, M, state, CONV):
    """Add thermal piecewise-linear variable production-cost constraints."""
    cost_multiplier = cost_curve_time_multiplier(input_data)
    u_1 = [[[] for _ in intervals] for _ in data]
    delta_ = [[[] for _ in intervals] for _ in data]

    for i, gen in enumerate(data):
        if i in CONV:
            breakpoints, coefficients, widths, is_convex = parse_thermal_cost_curve(gen)
            if (
                not breakpoints
                or len(coefficients) != len(breakpoints)
                or not widths
                or any(width <= 0 for width in widths)
                or any(coefficient < 0 for coefficient in coefficients)
            ):
                raise ValueError(
                    f"Thermal unit {gen.get('gen_id', i)} has an invalid var_gen_cost(euro/MW) curve."
                )
            slopes = coefficients[1:]
            segment_count = len(widths)
            for t in intervals[1:]:
                delta_[i][t] = [
                    pl.LpVariable(name=f'delta_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None)
                    for s_index in range(segment_count)
                ]
                prob += power[i][t] == pl.lpSum(delta_[i][t]) + breakpoints[0] * state[i][t]

                if is_convex:
                    # Convex PWL costs do not need segment-selection binaries: with nondecreasing
                    # slopes, cost minimization naturally fills cheaper segments first.
                    for s_index, width in enumerate(widths):
                        prob += delta_[i][t][s_index] <= width * state[i][t]
                else:
                    # Nonconvex/decreasing slopes need ordered-fill binaries so later cheaper
                    # segments cannot be used before all preceding segments are full.
                    u_1[i][t] = [
                        pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary')
                        for s_index in range(max(0, segment_count - 1))
                    ]
                    prob += delta_[i][t][0] <= widths[0] * state[i][t]
                    for s_index in range(1, segment_count):
                        prob += delta_[i][t][s_index] <= widths[s_index] * u_1[i][t][s_index - 1]
                    for s_index in range(segment_count - 1):
                        prob += delta_[i][t][s_index] >= widths[s_index] * u_1[i][t][s_index]

                objective_terms += (
                    pl.lpSum(slopes[s_index] * delta_[i][t][s_index] for s_index in range(segment_count))
                    + coefficients[0] * state[i][t]
                ) * cost_multiplier
    # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         # for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):

    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
    #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
    #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
        # M = 10000
    # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
    #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
    # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
    # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
    #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]

    # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
    #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
            # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
            # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed

    #     # M = 10000
    # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
    #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
    # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
    # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
    #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]
    #
    # # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
    #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
    #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
    #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
    return prob, objective_terms, u_1


def create_power_state_baseline_deviations_calculation_constraints(input_data, prob, objective_terms, data, intervals, power, state,
                                                                   RDAS_power_df,
                                                                   RDAS_state_df, CONV, M):
    """Add RDAS baseline deviation variables and penalties for legacy experiments."""
    deviation_1 = [[pl.LpVariable(name=f'dev_1_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in
                   enumerate(data)]
    deviation_2 = [[pl.LpVariable(name=f'dev_2_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in
                   enumerate(data)]
    y_4 = [[pl.LpVariable(name=f'y_4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in
           enumerate(data)]
    y_5 = [[pl.LpVariable(name=f'y_5_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in
           enumerate(data)]
    # M = 10000
    for i in CONV:
        for t in intervals[1:]:
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] <= + M * y_4[i][t]  # + dev_1[i][t]
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] >= - M * (1 - y_4[i][t])  # - dev_1[i][t]
            # Constraint 1: If y=1, then d=d1 else d=-d1
            prob += (power[i][t] - RDAS_power_df.iat[i, t - 1]) - deviation_1[i][t] <= M * (1 - y_4[i][t])
            prob += (power[i][t] - RDAS_power_df.iat[i, t - 1]) - deviation_1[i][t] >= - M * (1 - y_4[i][t])
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] + deviation_1[i][t] <= M * y_4[i][t]
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] + deviation_1[i][t] >= - M * y_4[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] <= M * y_5[i][t]  # + dev_1[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] >= - M * (1 - y_5[i][t])  # - dev_1[i][t]
            # Constraint 1: If y=1, then d=d1 else d=-d1
            prob += (state[i][t] - RDAS_state_df.iat[i, t - 1]) - deviation_2[i][t] <= M * (1 - y_5[i][t])
            prob += (state[i][t] - RDAS_state_df.iat[i, t - 1]) - deviation_2[i][t] >= - M * (1 - y_5[i][t])
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] + deviation_2[i][t] <= M * y_5[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] + deviation_2[i][t] >= - M * y_5[i][t]
            # if i in CONV:
            objective_terms += deviation_1[i][t] * 100 * input_data["Time_granularity"] + deviation_2[i][t] * 1000 * input_data["Time_granularity"]
    return prob, objective_terms, deviation_1, deviation_2, y_4, y_5


def create_testing_mode_constraints(prob, objective_terms, input_data, data, power, intervals, CONV):
    """Add testing-mode power constraints and violation slacks."""
    s_power_testing_mode_plus = [[pl.LpVariable(name=f's_power_testing_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    s_power_testing_mode_minus = [[pl.LpVariable(name=f's_power_testing_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]

    for i in CONV:  # CONV + dispatchable RES (in all dispatchable units)
        for t in intervals[1:]:
            if data[i]['testing_mode_enabled'][t-1] == 1:
                prob += power[i][t] - s_power_testing_mode_minus[i][t] + s_power_testing_mode_plus[i][t] == data[i]['power_production_in_testing_mode'][t-1]
            else:
                pass
            objective_terms += s_power_testing_mode_minus[i][t] * input_data["Cost_parameters"]["x_testing_mode"] + s_power_testing_mode_plus[i][t] * input_data["Cost_parameters"]["x_testing_mode"]

    return prob, objective_terms


def create_availability_program(prob, objective_terms, input_data, data, power, intervals, CONV):
    # s_avail = [[pl.LpVariable(name=f's_avail_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    """Add availability program constraints for conventional units."""
    for i in range(len(data)):
        for t in intervals[1:]:
            prob += power[i][t] <= data[i]["availability"][t-1]  # - s_avail[i][t]
        # print(data[gen_id].get('gen_declaration'), float('inf'))

            # objective_terms += s_avail[i][t] * input_data["Cost_parameters"]["x_availability"]
            # prob += s_avail[i][t] == 0
    return prob, objective_terms


def create_OOS_mode_constraints(prob, objective_terms, input_data, data, power, intervals, PV_no_SP):
    """Add out-of-sequence mode constraints and violation slacks."""
    s_power_OOS_less_plus = [[pl.LpVariable(name=f's_power_OOS_less_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    s_power_OOS_more_minus = [[pl.LpVariable(name=f's_power_OOS_more_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]

    for i in range(len(data)):  # CONV + dispatchable RES (in all dispatchable units)
        if i in PV_no_SP:
            pass
        else:
            for t in intervals[1:]:
                if data[i]['OOS_mode_less_than_enabled'][t - 1] == 1:
                    prob += power[i][t] - s_power_OOS_less_plus[i][t] <= data[i]['power_production_in_OOS_mode_less_than'][t - 1]
                if data[i]['OOS_mode_more_than_enabled'][t - 1] == 1:
                    prob += power[i][t] + s_power_OOS_more_minus[i][t] >= data[i]['power_production_in_OOS_mode_more_than'][t - 1]


                objective_terms += s_power_OOS_less_plus[i][t] * input_data["Cost_parameters"]["x_OOS_less_than"] + s_power_OOS_more_minus[i][t] * input_data["Cost_parameters"]["x_OOS_more_than"]



    return prob, objective_terms


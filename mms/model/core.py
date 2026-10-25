"""Core dispatch variables and system-level constraints for the MMS optimization model."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import numpy as np
import pandas as pd
import pulp as pl


def create_global_variables(prob, data, intervals):
    # Power output for each generator for each hour
    """Create core dispatch, commitment, startup, shutdown, and RES aggregation variables."""
    power = [[pl.LpVariable(name=f'power_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]
    # State for each generator for each hour
    state = [[pl.LpVariable(name=f'state_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _
             in
             enumerate(data)]
    # total PV + RES production for each hour
    RES_sum = [pl.LpVariable(name=f'RES_sum_{t}', lowBound=0, upBound=None) for t in intervals]
    # Startup variables
    startup = [[pl.LpVariable(name=f'startup_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for
               i, _
               in enumerate(data)]
    # Shutdown variables
    shutdown = [[pl.LpVariable(name=f'shutdown_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
                for i
                in range(len(data))]
    for i, gen in enumerate(data):
        prob += state[i][0] == gen['state']  # the state value of the hour = 0 (the last hour before our day starts)
        prob += 100 * power[i][0] == 100 * gen['current_Power(MW)']  # the energy production of the hour = 0
    return prob, power, state, RES_sum, startup, shutdown


def create_largest_online_capacity_bounds(prob, CONV, state, data, intervals):
    """Create envelope variables for largest-online-unit reserve sizing terms."""
    largest_online_capacity = [
        pl.LpVariable(name=f'largest_online_capacity_{t}', lowBound=0, upBound=None)
        for t in intervals
    ]
    largest_two_online_capacity = [
        pl.LpVariable(name=f'largest_two_online_capacity_{t}', lowBound=0, upBound=None)
        for t in intervals
    ]

    prob += largest_online_capacity[0] == 0
    prob += largest_two_online_capacity[0] == 0

    for t in intervals[1:]:
        total_online_capacity = pl.lpSum(
            data[i]['availability'][t - 1] * state[i][t]
            for i in CONV
        )

        for i in CONV:
            prob += largest_online_capacity[t] >= data[i]['availability'][t - 1] * state[i][t]
            prob += largest_two_online_capacity[t] >= data[i]['availability'][t - 1] * state[i][t]

        for left_index, i in enumerate(CONV):
            for j in CONV[left_index + 1:]:
                prob += largest_two_online_capacity[t] >= (
                        data[i]['availability'][t - 1] * state[i][t]
                        + data[j]['availability'][t - 1] * state[j][t]
                )

        prob += largest_online_capacity[t] <= total_online_capacity
        prob += largest_two_online_capacity[t] <= total_online_capacity

    return largest_online_capacity, largest_two_online_capacity


def produce_min_max_t(data, intervals):
    """Expand scalar min/max power values into per-period arrays used by constraints."""
    k = len(intervals)-1

    for i, _ in enumerate(data):
        data[i]["max_power(MW)"] = k * [data[i]["max_power(MW)"]]
        data[i]["min_power(MW)"] = k * [data[i]["min_power(MW)"]]
        for operating_states in data[i]["operating-states"]:
            operating_states["max-power"] = k * [operating_states["max-power"]]
            operating_states["min-power"] = k * [operating_states["min-power"]]
    return data


def min_max_handling(prob, data, input_data, CONV, Partially_Controllable, on_AGC, intervals, u_1, state, power):

    """Apply unit and operating-state min/max power limits before dispatch constraints are built."""
    if input_data["constraints"]["min_max_constraint"]:
        # only for dispatchable units check 5.2.4.4 Constraints paragraph in "Διακήρυξη" pdf
        for gen in data:
            gen_id = gen['gen_id']
            if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
                for operating_state in data[gen_id]["operating-states"]:
                    if operating_state["isOperational"]:
                        for t in intervals[1:]:
                            # if constraint enabled -- we cannot go to the zone above technical maximum
                            # prob += u_1[gen_id][t][-1] == 0
                            operating_state["max-power"][t-1] = operating_state["user_max_power"]
                            operating_state["min-power"][t-1] = operating_state["user_min_power"]
                    else:
                        pass
    else:
        # for gen in data:
        #     gen_id = gen['gen_id']
        #     if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
        #         for operating_state in data[gen_id]["operating-states"]:
        #             if operating_state["isOperational"]:
        #                 for t in intervals[1:]:
        #                     operating_state["max-power"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
        #                     operating_state["min-power"][t-1] = 0
        #             else:
        #                 for t in intervals[1:]:
        #                     operating_state["max-power"][t-1] = operating_state["min-power"][t-1] = 0
        #         for t in intervals[1:]:
        #             data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
        #             data[gen_id]["min_power(MW)"][t-1] = 0
        #     else:
        pass

    for i, _ in enumerate(data):
        # these units can provide secondary reserves - regulation
        # for i in CONV:
        agc_configuration = data[i].get("agc_configuration", {})
        if agc_configuration.get("isConnected", 0) == 1:
            on_AGC.append(i)
            for operating_states in data[i]["operating-states"]:
                if operating_states["isOperational"]:
                    for t in intervals[1:]:
                        operating_states["max-power"][t-1] = min(agc_configuration.get("maxLoad", operating_states["max-power"][t-1]), operating_states["max-power"][t-1])
                        operating_states["min-power"][t-1] = max(agc_configuration.get("minLoad", operating_states["min-power"][t-1]), operating_states["min-power"][t-1])
                else:
                    pass
        else:
            pass
    #
    # for i, _ in enumerate(data):
    #     if i in Partially_Controllable:
    #         print("Partially_Controllable Unit:", i)
    #         for t in intervals[1:]:
    #             for operating_states in data[i]["operating-states"]:
    #                 if operating_states["isOperational"]:
    #                     if operating_states["max-power"][t-1] > data[i]["production_program"][t-1]:
    #                         if operating_states["min-power"][t-1] > data[i]["production_program"][t-1]:
    #                             for operating_states_2 in data[i]["operating-states"]:
    #                                 operating_states_2["max-power"][t - 1] = operating_states_2["min-power"][t-1] = 0
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[gen_id]["min_power(MW)"][t - 1] = 0
    #                             prob += state[gen_id][t] == 0
    #                         else:
    #                             operating_states["max-power"][t - 1] = data[i]["production_program"][t-1]
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #                     else:
    #                         if data[gen_id]["max_power(MW)"][t - 1] < data[i]["production_program"][t-1]:
    #                             pass
    #                         else:
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #                 else:
    #                     pass
    # print(data[5])
    # print(data)

    return prob, data, on_AGC


def create_res_sum_calculation_constraint(prob, power, intervals, RES_sum, RES, PV, Partially_Controllable):
    # Create RES_sum[t] calculation constraint
    """Constrain the aggregate RES/PV production variable by period."""
    for t in intervals[0:]:
        prob += RES_sum[t] == pl.lpSum(power[i][t] for i in RES + PV + Partially_Controllable)
    return prob


def create_production_load_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV,
                                              x_load):
    # decision variables generation
    # production - load balance relaxation variable (need to increase load)
    """Add load-balance equations and load slack penalties."""
    s_load_plus = [pl.LpVariable(name=f's_load_plus_{t}', lowBound=0, upBound=None) for t in intervals]
    # production - load balance relaxation variable (need to decrease load)
    s_load_minus = [pl.LpVariable(name=f's_load_minus_{t}', lowBound=0, upBound=None) for t in intervals]
    # respective constraint
    for t in intervals[1:]:
        # Total generation must be equal to the load forecast for each hour
        prob += pl.lpSum(power[i][t] for i in range(len(data))) - s_load_plus[t] + s_load_minus[t] == Load_forecast[t]
        prob += s_load_plus[t] == 0
        # prob += s_load_minus[t] == 0
        # for i in CONV:
        objective_terms += s_load_plus[t] * x_load + s_load_minus[t] * x_load
    return prob, objective_terms, s_load_minus, s_load_plus


def create_ensure_variables_correctness_constraint(prob, data, intervals, state, startup, shutdown):
    """Link commitment, startup, and shutdown binaries across periods."""
    for i, gen in enumerate(data):
        for t in intervals[1:]:
            # we ensure the correctness of startup & shutdown values
            prob += startup[i][t] >= state[i][t] - state[i][
                t - 1]  # If the generator switches on, this will enforce startup[i][t] to be 1.
            prob += startup[i][t] <= 1 - state[i][
                t - 1]  # If the generator was on at t-1, this will enforce startup[i][t] to be 0.
            prob += startup[i][t] <= state[i][
                t]  # If the generator is off at t, this will enforce startup[i][t] to be 0.
            prob += shutdown[i][t] >= state[i][t - 1] - state[i][
                t]  # If the generator switches off, this will enforce shutdown[i][t] to be 1.
            prob += shutdown[i][t] <= 1 - state[i][
                t]  # If the generator is on at t, this will enforce shutdown[i][t] to be 0.
            prob += shutdown[i][t] <= state[i][
                t - 1]  # If the generator was off at t-1, this will enforce shutdown[i][t] to be 0.
    return prob


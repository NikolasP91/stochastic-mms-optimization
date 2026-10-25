"""RES/PV dispatch, setpoint, grid-capacity, and curtailment formulation pieces."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import numpy as np
import pandas as pd
import pulp as pl

from mms.model.bounds import res_pv_dispatch_bounds, res_pv_unit_dispatch_bounds


def create_res_pv_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast,
                                                 RES_forecast, RES_sum, M, s_power_minus):
    """Build the legacy RES/PV dispatch-variable formulation."""
    setpoint = [[pl.LpVariable(name=f'setpoint{i + 1}_{t}', lowBound=0, upBound=1) for t in intervals] for i in range(len(data))]
    Min_grid_capacity_1 = [pl.LpVariable(name=f'Min_grid_capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]  # for non-dispatchable res
    Min_grid_capacity_2 = [pl.LpVariable(name=f'Min_grid_capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    Min_Power_Calc = [[pl.LpVariable(name=f'Min_Power_Calc_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]

    s_Grid_Capacity_1 = [pl.LpVariable(name=f's_Grid_Capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_2 = [pl.LpVariable(name=f's_Grid_Capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_3 = [pl.LpVariable(name=f's_Grid_Capacity_3_{t}', lowBound=0, upBound=None) for t in intervals]

    m = [[pl.LpVariable(name=f'm_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]
    rel_var = [pl.LpVariable(name=f'rel_var_{t}', lowBound=0, upBound=None) for t in
               intervals]  # for non-dispatchable res
    g1 = [pl.LpVariable(name=f'g1_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g2 = [pl.LpVariable(name=f'g2_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g3 = [[pl.LpVariable(name=f'g3_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g4 = [[pl.LpVariable(name=f'g4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]

    Grid_Capacity1 = [pl.LpVariable(name=f'Grid_Capacity1_{t}', lowBound=0, upBound=None) for t in intervals]
    Grid_Capacity2 = [pl.LpVariable(name=f'Grid_Capacity2_{t}', lowBound=0, upBound=None) for t in intervals]
    Grid_Capacity3 = [pl.LpVariable(name=f'Grid_Capacity3_{t}', lowBound=0, upBound=None) for t in intervals]
    # M = 10000
    # for t in intervals[1:]:
    #     for i in PV:
    #         prob += power[i][t] == RES_forecast[t - 1][i]
    for t in intervals[1:]:
        prob += Grid_Capacity2[t] == input_data["Other_coefficients"]["x_res_pv_dynamic"] * pl.lpSum(data[i]['max_power(MW)'][t-1] * state[i][t] for i in CONV)  # P_Kt
        prob += Grid_Capacity1[t] == pl.lpSum(power[i][t] for i in CONV + RES_SP + PV_SP) - pl.lpSum(data[i]['min_power(MW)'][t-1] * state[i][t] for i in CONV)  #+0.003 # P_TEt Load_forecast[t] not including PV_power
        prob += Grid_Capacity3[t] == pl.lpSum(data[i]['max_power(MW)'][t-1] for i in RES+PV)  ###### από όσες RES+PV είναι διαθέσιμες
        ###############
        prob += (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * g2[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) <= M * (1 - g2[t]) * 10
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) >= -M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) <= M * g2[t] * 10   # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) >= -M * g2[t] * 10  # "a_equals_c_if_g_is_0_neg"
        ################
        #
        prob += RES_sum[t] <= Grid_Capacity1[t] + s_Grid_Capacity_1[t]  # the actual power we expect the res + pv units to produce
        prob += RES_sum[t] <= Grid_Capacity2[t] + s_Grid_Capacity_2[t]
        prob += RES_sum[t] <= Grid_Capacity3[t] + s_Grid_Capacity_3[t]
        #
        prob += (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) - Min_grid_capacity_2[t] <= M * g1[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += Min_grid_capacity_2[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) <= M * (1 - g1[t]) * 10
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] <= M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] >= -M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_1[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) <= M * g1[t] * 10  # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_1[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) >= -M * g1[t] * 10  # "a_equals_c_if_g_is_0_neg"
        # prob += pl.lpSum(state[i][t] * data[i]["min_power(MW)"] for i in RES) <= Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV)  # for wind parks από όσες RES είναι διαθέσιμες (και έχουν ισχύ > min - όχι η παρένθεση)
        for i in RES_SP + PV_SP:
            # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
            prob += power[i][t] <= setpoint[i][t] * data[i]['max_power(MW)'][t-1]
            # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
            ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
            prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['max_power(MW)'][t-1] <= M * g3[i][t] * 10
            prob += setpoint[i][t] * data[i]['max_power(MW)'][t-1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * (1 - g3[i][t]) * 10
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t-1] <= M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1"
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t-1] >= -M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1_neg"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * g3[i][t] * 10  # "a_equals_c_if_g_is_0"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -M * g3[i][t] * 10  # "a_equals_c_if_g_is_0_neg"
            # calculate the power of RES with setpoint based on the setpoint and the respective forecast
            # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
            prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t-1] <= M * g4[i][t] * 10
            prob += data[i]['min_power(MW)'][t-1] - Min_Power_Calc[i][t] <= M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= M * g4[i][t] * 10
            prob += power[i][t] >= Min_Power_Calc[i][t] - M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= Min_Power_Calc[i][t] + M * (1 - g4[i][t]) * 10
            prob += power[i][t] >= 0
            ##########
            # objective_terms += setpoint[i][t] * (-50) * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]
        prob += Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP) >= pl.lpSum(data[i]['max_power(MW)'][t-1] * setpoint[i][t] for i in RES_SP + PV_SP)  # ###### από όσες RES είναι διαθέσιμες και (έχουν ισχύ > min)  #  + rel_var[t]  # last term added for the case when all states of res are 0 (off)
        objective_terms += (s_Grid_Capacity_1[t] + s_Grid_Capacity_2[t] + s_Grid_Capacity_3[t]) * input_data["Cost_parameters"]["x_Grid_Capacity"]
            # m = setpoint * state
            # prob += m[i][t] <= setpoint[i][t]
            # prob += m[i][t] <= M * state[i][t]
            # prob += m[i][t] >= setpoint[i][t] - M * (1 - state[i][t])
            # prob += m[i][t] >= 0
        first_i = RES_SP[0]  # Take the first unit of the RES_SP as the reference
        for i in RES_SP[1:] + PV_SP:  # Compare every other unit to the first one
            prob += setpoint[first_i][t] == setpoint[i][t]  # equal setpoints for the same RES category (now we have one category - Non dispatchable res)
        for i in CONV + RES_no_SP + PV_no_SP:
            prob += setpoint[i][t] == 0.0
            # prob += m[i][t] == 0.0
    return prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_1, s_Grid_Capacity_2, s_Grid_Capacity_3


def create_res_pv_2_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast,
                                                 RES_forecast, RES_sum, M, s_power_minus):
    """Build the active RES/PV dispatch and setpoint formulation."""
    setpoint = [[pl.LpVariable(name=f'setpoint{i + 1}_{t}', lowBound=0, upBound=1) for t in intervals] for i in range(len(data))]
    Min_grid_capacity_1 = [pl.LpVariable(name=f'Min_grid_capacity_1_{t}', lowBound=None, upBound=None) for t in intervals]  # for non-dispatchable res
    Min_grid_capacity_2 = [pl.LpVariable(name=f'Min_grid_capacity_2_{t}', lowBound=None, upBound=None) for t in intervals]
    Min_Power_Calc = [[pl.LpVariable(name=f'Min_Power_Calc_{i + 1}_{t}', lowBound=None, upBound=None) for t in intervals] for i in range(len(data))]
    P_sp = [pl.LpVariable(name=f'P_sp_{t}', lowBound=None, upBound=None) for t in intervals]
    P_sp_1 = [pl.LpVariable(name=f'P_s_1_{t}', lowBound=None, upBound=None) for t in intervals]

    # s_Grid_Capacity_1 = [pl.LpVariable(name=f's_Grid_Capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_2 = [pl.LpVariable(name=f's_Grid_Capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    # s_Grid_Capacity_3 = [pl.LpVariable(name=f's_Grid_Capacity_3_{t}', lowBound=0, upBound=None) for t in intervals]

    m = [[pl.LpVariable(name=f'm_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]
    rel_var = [pl.LpVariable(name=f'rel_var_{t}', lowBound=0, upBound=None) for t in
               intervals]  # for non-dispatchable res
    g1 = [pl.LpVariable(name=f'g1_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g2 = [pl.LpVariable(name=f'g2_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g3 = [[pl.LpVariable(name=f'g3_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g4 = [[pl.LpVariable(name=f'g4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g5 = [pl.LpVariable(name=f'g5_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]

    Grid_Capacity1 = [pl.LpVariable(name=f'Grid_Capacity1_{t}', lowBound=None, upBound=None) for t in intervals]
    Grid_Capacity2 = [pl.LpVariable(name=f'Grid_Capacity2_{t}', lowBound=None, upBound=None) for t in intervals]
    Grid_Capacity3 = [pl.LpVariable(name=f'Grid_Capacity3_{t}', lowBound=None, upBound=None) for t in intervals]

    # P_RES = [pl.LpVariable(name=f'P_RES_{t}', lowBound=0, upBound=None) for t in intervals]
    # P_PV = [pl.LpVariable(name=f'P_PV_{t}', lowBound=0, upBound=None) for t in intervals]

    if input_data["Other_coefficients"]["PV_dispatch_method"] == 1:
        input_data["Other_coefficients"]["x_res_pv_dynamic"] = 1
        input_data["Other_coefficients"]["PV_Participation_coefficient"] = 100
        for i in RES_SP:
            for t in intervals[1:]:
                data[i]['availability'][t - 1] = 0


    for t in intervals[1:]:
        dispatch_bounds = res_pv_dispatch_bounds(
            input_data, data, CONV, RES_SP, PV_SP, RES_no_SP, PV_no_SP, Load_forecast, t
        )
        s_Grid_Capacity_2[t].upBound = dispatch_bounds["grid_capacity2_slack_upper"]
        grid_capacity2_m = dispatch_bounds["grid_capacity2_big_m"]
        grid_capacity1_m = dispatch_bounds["grid_capacity1_big_m"]
        positive_part_m = dispatch_bounds["positive_part_big_m"]

        prob += Grid_Capacity2[t] == input_data["Other_coefficients"]["x_res_pv_dynamic"] * Load_forecast[t]  #pl.lpSum(power[i][t] for i in UNITS)
        # prob += Grid_Capacity1[t] == pl.lpSum(power[i][t] for i in UNITS) - pl.lpSum(data[i]['min_power(MW)'][t-1] * state[i][t] for i in CONV)  #+0.003 # P_TEt Load_forecast[t] not including PV_power
        prob += Grid_Capacity1[t] == Load_forecast[t] - pl.lpSum(data[i]['min_power(MW)'][t - 1] * state[i][t] for i in CONV) - input_data["Other_coefficients"]["include_PV"] * pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP)
        prob += Grid_Capacity3[t] == pl.lpSum(data[i]['availability'][t-1] for i in RES_SP) + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * pl.lpSum(data[i]['availability'][t-1] for i in PV_SP)  #+ pl.lpSum(data[i]['availability'][t-1] for i in PV_no_SP)  ###### από όσες RES+PV είναι διαθέσιμες
        ###############
        prob += Grid_Capacity3[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= grid_capacity2_m * g2[t]
        prob += (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) - Grid_Capacity3[t] <= grid_capacity2_m * (1 - g2[t])
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= grid_capacity2_m * (1 - g2[t])  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) >= -grid_capacity2_m * (1 - g2[t])  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_2[t] - Grid_Capacity3[t] <= grid_capacity2_m * g2[t]   # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_2[t] - Grid_Capacity3[t] >= -grid_capacity2_m * g2[t]  # "a_equals_c_if_g_is_0_neg"
        ################
        #
        # prob += RES_sum[t] <= Grid_Capacity1[t] + s_Grid_Capacity_1[t]  # the actual power we expect the res + pv units to produce
        # prob += RES_sum[t] <= Grid_Capacity2[t] + s_Grid_Capacity_2[t]
        # prob += RES_sum[t] <= Grid_Capacity3[t] + s_Grid_Capacity_3[t]
        #
        prob += Grid_Capacity1[t] - Min_grid_capacity_2[t] <= grid_capacity1_m * g1[t]
        prob += Min_grid_capacity_2[t] - Grid_Capacity1[t] <= grid_capacity1_m * (1 - g1[t])
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] <= grid_capacity1_m * (1 - g1[t])  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] >= -grid_capacity1_m * (1 - g1[t])  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_1[t] - Grid_Capacity1[t] <= grid_capacity1_m * g1[t]  # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_1[t] - Grid_Capacity1[t] >= -grid_capacity1_m * g1[t]  # "a_equals_c_if_g_is_0_neg"
        # prob += pl.lpSum(state[i][t] * data[i]["min_power(MW)"] for i in RES) <= Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV)  # for wind parks από όσες RES είναι διαθέσιμες (και έχουν ισχύ > min - όχι η παρένθεση)

        # max(Min_grid_capacity_1[t], 0)
        prob += P_sp_1[t] >= Min_grid_capacity_1[t]
        prob += P_sp_1[t] >= 0
        prob += P_sp_1[t] <= Min_grid_capacity_1[t] + positive_part_m * (1 - g5[t])
        prob += P_sp_1[t] <= positive_part_m * g5[t]
        prob += Min_grid_capacity_1[t] <= positive_part_m * g5[t]

        prob += P_sp[t] <= P_sp_1[t]

        # prob += P_RES[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))
        # prob += P_PV[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in PV_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))

        # prob += P_RES[t] == P_sp[t]  # - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP)
        # prob += P_PV[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in PV_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))


        # calculate setpoint with reference to installed capacity
        if input_data["Other_coefficients"]["PV_dispatch_method"] == 0:
            temp_sum = pl.lpSum(data[j]['availability'][t - 1] for j in RES_SP)
            temp_sum_2 = pl.lpSum(data[j]['availability'][t - 1] for j in PV_SP)
            for i in RES_SP:
                prob += setpoint[i][t] * (temp_sum + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * temp_sum_2) == P_sp[t]  #* data[i]['availability'][t-1]  #- pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP)
            for i in PV_SP:
                prob += setpoint[i][t] * (temp_sum + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * temp_sum_2) == P_sp[t] * (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100)  #* data[i]['availability'][t-1]

                # for i in PV_SP:
            #     prob += setpoint[i][t] * pl.lpSum(data[j]['availability'][t-1] for j in PV_SP) == P_PV[t]
        else:
            temp_sum_3 = pl.lpSum(data[j]['availability'][t - 1] for j in PV_SP)
            for i in RES_SP:
                prob += setpoint[i][t] == 0
            for i in PV_SP:
                prob += setpoint[i][t] * temp_sum_3 == P_sp[t]   #* data[i]['availability'][t-1]



        for i in RES_SP + PV_SP:
            unit_bounds = res_pv_unit_dispatch_bounds(data[i], RES_forecast[t - 1][i], t - 1, M)
            s_power_minus[i][t].upBound = unit_bounds["s_power_minus_upper"]
            setpoint_forecast_m = unit_bounds["setpoint_forecast_big_m"]
            power_m = unit_bounds["power_big_m"]
            # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
            prob += power[i][t] <= setpoint[i][t] * data[i]['availability'][t-1]
            # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
            ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
            prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['availability'][t-1] <= setpoint_forecast_m * g3[i][t]
            prob += setpoint[i][t] * data[i]['availability'][t-1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= setpoint_forecast_m * (1 - g3[i][t])
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['availability'][t-1] <= setpoint_forecast_m * (1 - g3[i][t])  # "a_equals_b_if_g_is_1"
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['availability'][t-1] >= -setpoint_forecast_m * (1 - g3[i][t])  # "a_equals_b_if_g_is_1_neg"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= setpoint_forecast_m * g3[i][t]  # "a_equals_c_if_g_is_0"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -setpoint_forecast_m * g3[i][t]  # "a_equals_c_if_g_is_0_neg"
            # calculate the power of RES with setpoint based on the setpoint and the respective forecast
            # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
            prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t-1] <= power_m * g4[i][t]
            prob += data[i]['min_power(MW)'][t-1] - Min_Power_Calc[i][t] <= power_m * (1 - g4[i][t])
            prob += power[i][t] <= power_m * g4[i][t]
            prob += power[i][t] >= Min_Power_Calc[i][t] - power_m * (1 - g4[i][t])
            prob += power[i][t] <= Min_Power_Calc[i][t] + power_m * (1 - g4[i][t])
            prob += power[i][t] >= 0
            ##########
            objective_terms += setpoint[i][t] * (-50)  # * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]
        # for i in PV_SP:
        #     # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
        #     prob += power[i][t] <= setpoint[i][t] * data[i]['max_power(MW)'][t - 1]
        #     # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
        #     ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
        #     prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] <= M * g3[i][t] * 10
        #     prob += setpoint[i][t] * data[i]['max_power(MW)'][t - 1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * (1 - g3[i][t]) * 10
        #     prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] <= M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1"
        #     prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] >= -M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1_neg"
        #     prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * g3[i][t] * 10  # "a_equals_c_if_g_is_0"
        #     prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -M * g3[i][t] * 10  # "a_equals_c_if_g_is_0_neg"
        #     # calculate the power of RES with setpoint based on the setpoint and the respective forecast
        #     # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
        #     prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t - 1] <= M * g4[i][t] * 10
        #     prob += data[i]['min_power(MW)'][t - 1] - Min_Power_Calc[i][t] <= M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] <= M * g4[i][t] * 10
        #     prob += power[i][t] >= Min_Power_Calc[i][t] - M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] <= Min_Power_Calc[i][t] + M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] >= 0
        #     ##########
        #     objective_terms += setpoint[i][t] * (-50)  # * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]

        # prob += Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV_no_SP + RES_no_SP) == pl.lpSum(data[i]['max_power(MW)'] * setpoint[i][t] for i in RES)  # ###### από όσες RES είναι διαθέσιμες και (έχουν ισχύ > min)  #  + rel_var[t]  # last term added for the case when all states of res are 0 (off)
        objective_terms += s_Grid_Capacity_2[t] * input_data["Cost_parameters"]["x_Grid_Capacity"]
            # m = setpoint * state
            # prob += m[i][t] <= setpoint[i][t]
            # prob += m[i][t] <= M * state[i][t]
            # prob += m[i][t] >= setpoint[i][t] - M * (1 - state[i][t])
            # prob += m[i][t] >= 0
        # first_i = RES[0]  # Take the first unit of the RES as the reference
        # for i in RES[1:]:  # Compare every other unit to the first one
        #     prob += setpoint[first_i][t] == setpoint[i][t]  # equal setpoints for the same RES category (now we have one category - Non dispatchable res)
        for i in CONV + RES_no_SP + PV_no_SP + Partially_Controllable:  #+ PV:
            prob += setpoint[i][t] == 0.0
            # prob += m[i][t] == 0.0
    return prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_2


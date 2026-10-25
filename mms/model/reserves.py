"""Primary, secondary, and tertiary active-power reserve constraints."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import numpy as np
import pandas as pd
import pulp as pl

from mms.model.bounds import reserve_activation_bound


def create_primary_active_power_reserves_constraint(prob, input_data, objective_terms, power, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M,  PV, largest_online_capacity, largest_two_online_capacity):
    # epsilon = 0.001
    # M=10000
    # decision variables generation
    """Add primary active-power reserve provision and shortage constraints."""
    primary_ActPR_plus = [[pl.LpVariable(name=f'primary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    primary_ActPR_minus = [[pl.LpVariable(name=f'primary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    # primary_y_plus = [[pl.LpVariable(name=f'primary_y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    # primary_y_minus = [[pl.LpVariable(name=f'primary_y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    primary_APRR = [[pl.LpVariable(name=f'primary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in intervals]
    s_primary_APR_upwards = [pl.LpVariable(name=f's_primary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_primary_APR_downwards = [pl.LpVariable(name=f's_primary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:

                for t in intervals[1:]:
                    primary_up_bound = reserve_activation_bound(
                        gen, "Primary_Active_Power_Reserves(MW)", 0, t - 1, operating_state
                    )
                    primary_down_bound = reserve_activation_bound(
                        gen, "Primary_Active_Power_Reserves(MW)", 1, t - 1, operating_state
                    )
                    if gen['availability'][t-1] == 0:
                        prob += primary_ActPR_plus[i][t] == 0
                        prob += primary_ActPR_minus[i][t] == 0

                    else:

                        if input_data["constraints"]["min_max_constraint"]:

                            prob += primary_ActPR_plus[i][t] <= min(gen['availability'][t-1], operating_state['user_max_power']) - power[i][t]
                            prob += primary_ActPR_plus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][0]

                            prob += primary_ActPR_minus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += primary_ActPR_minus[i][t] <= power[i][t] - operating_state['user_min_power'] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])

                            prob += primary_ActPR_plus[i][t] <= primary_up_bound * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += primary_ActPR_minus[i][t] <= primary_down_bound * u_2_dict[(gen_id, t, operating_state_id)]

                        else:
                            prob += primary_ActPR_plus[i][t] <= gen['availability'][t - 1] - power[i][t]
                            prob += primary_ActPR_plus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][0]

                            prob += primary_ActPR_minus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][1] + M * (
                                        1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += primary_ActPR_minus[i][t] <= power[i][t] - gen['min_power(MW)'][t - 1] + M * (
                                        1 - u_2_dict[(gen_id, t, operating_state_id)])

                            prob += primary_ActPR_plus[i][t] <= primary_up_bound * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += primary_ActPR_minus[i][t] <= primary_down_bound * u_2_dict[(gen_id, t, operating_state_id)]



        for t in intervals[1:]:  # calculate the cost of APR only for this time horizon
            objective_terms += primary_ActPR_plus[i][t] * gen['Primary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + primary_ActPR_minus[i][t] * gen['Primary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]
    for t in intervals[1:]:
        prob += pl.lpSum(primary_ActPR_minus[i][t] for i in range(len(data))) == primary_APRR[t][1] - s_primary_APR_downwards[t]
        prob += pl.lpSum(primary_ActPR_plus[i][t] for i in range(len(data))) == primary_APRR[t][0] - s_primary_APR_upwards[t]


        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        objective_terms += s_primary_APR_upwards[t] * input_data["Cost_parameters"]["x_primary_APR_up"] + s_primary_APR_downwards[t] * input_data["Cost_parameters"]["x_primary_APR_down"]
    return prob, objective_terms, primary_ActPR_plus, primary_ActPR_minus, primary_APRR, s_primary_APR_upwards, s_primary_APR_downwards


def create_secondary_active_power_reserves_constraint(prob, input_data, objective_terms, power, primary_ActPR_plus, primary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, largest_online_capacity, largest_two_online_capacity):
    """Add secondary active-power reserve provision and shortage constraints."""
    secondary_ActPR_plus = [[pl.LpVariable(name=f'secondary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    secondary_ActPR_minus = [[pl.LpVariable(name=f'secondary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    y_plus = [[pl.LpVariable(name=f'y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    y_minus = [[pl.LpVariable(name=f'y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    secondary_APRR = [[pl.LpVariable(name=f'secondary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in intervals]
    s_secondary_APR_upwards = [pl.LpVariable(name=f's_secondary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_secondary_APR_downwards = [pl.LpVariable(name=f's_secondary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:

                for t in intervals[1:]:
                    secondary_up_bound = reserve_activation_bound(
                        gen, "Secondary_Active_Power_Reserves(MW)", 0, t - 1, operating_state
                    )
                    secondary_down_bound = reserve_activation_bound(
                        gen, "Secondary_Active_Power_Reserves(MW)", 1, t - 1, operating_state
                    )
                    if i in on_AGC:  # provision of secondary reserves
                        if gen['availability'][t-1] == 0:
                            prob += secondary_ActPR_plus[i][t] == 0
                            prob += secondary_ActPR_minus[i][t] == 0
                        else:

                            prob += secondary_ActPR_plus[i][t] <= min(operating_state["max-power"][t-1], gen['availability'][t-1]) - (power[i][t] + primary_ActPR_plus[i][t]) + M * y_plus[i][t]

                            prob += secondary_ActPR_plus[i][t] <= gen["Secondary_Active_Power_Reserves(MW)"][0] + M * y_plus[i][t]


                            prob += secondary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]

                            prob += secondary_ActPR_minus[i][t] <= gen["Secondary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]



#                                   ########################### if y_plus==1 --> secondary_ActPR_plus == 0

                            prob += (power[i][t] + primary_ActPR_plus[i][t]) - operating_state["max-power"][t - 1] >= - M * (1 - y_plus[i][t])
                            prob += (power[i][t] + primary_ActPR_plus[i][t]) - operating_state["max-power"][t - 1] <= M * y_plus[i][t]
                            prob += secondary_ActPR_plus[i][t] <= secondary_up_bound * (1 - y_plus[i][t])

#                                                             # if y_minus==1 --> secondary_ActPR_minus == 0
                            prob += (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] <= M * (1 - y_minus[i][t])
                            prob += (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] >= - M * y_minus[i][t]
                            prob += secondary_ActPR_minus[i][t] <= secondary_down_bound * (1 - y_minus[i][t])

#                                    #########################

                            prob += secondary_ActPR_minus[i][t] <= secondary_down_bound * u_2_dict[(gen_id, t, operating_state_id)]  # power[i][t] - gen['min_power(MW)'] < 0 ---> primary_ActPR_minus[i][t] == 0
                            prob += secondary_ActPR_plus[i][t] <= secondary_up_bound * u_2_dict[(gen_id, t, operating_state_id)]  # power[i][t] - gen['min_power(MW)'] < 0 ---> primary_ActPR_plus[i][t] == 0
                    else:  # no provision of secondary reserves
                        prob += secondary_ActPR_plus[i][t] == 0
                        prob += secondary_ActPR_minus[i][t] == 0
                        # prob += secondary_y_plus[i][t] == 0
                        # prob += secondary_y_minus[i][t] == 0
        for t in intervals[1:]:
            objective_terms += secondary_ActPR_plus[i][t] * gen['Secondary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + secondary_ActPR_minus[i][t] * gen['Secondary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]

    for t in intervals[1:]:
        prob += pl.lpSum(secondary_ActPR_minus[i][t] for i in range(len(data))) == secondary_APRR[t][1] - s_secondary_APR_downwards[t]
        prob += pl.lpSum(secondary_ActPR_plus[i][t] for i in range(len(data))) == secondary_APRR[t][0] - s_secondary_APR_upwards[t]

        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        # objective_terms += (secondary_APRR[t][0] + secondary_APRR[t][1]) * 100

        # prob += secondary_APRR[t][0] == 0.1 * RES_sum[t] + 0.04 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        # prob += secondary_APRR[t][1] == 0.1 * RES_sum[t] + 0.04 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        objective_terms += s_secondary_APR_upwards[t] * input_data["Cost_parameters"]["x_secondary_APR_up"] + s_secondary_APR_downwards[t] * input_data["Cost_parameters"]["x_secondary_APR_down"]
    return prob, objective_terms, y_plus, y_minus, secondary_ActPR_plus, secondary_ActPR_minus, secondary_APRR, s_secondary_APR_upwards, s_secondary_APR_downwards


def create_tertiary_active_power_reserves_constraint(prob, input_data, objective_terms, y_plus, y_minus, power, primary_ActPR_plus, primary_ActPR_minus, secondary_ActPR_plus, secondary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, largest_online_capacity, largest_two_online_capacity):
    """Add tertiary active-power reserve provision and shortage constraints."""
    tertiary_ActPR_plus = [
        [pl.LpVariable(name=f'tertiary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen
        in
        enumerate(data)]
    tertiary_ActPR_minus = [
        [pl.LpVariable(name=f'tertiary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen
        in
        enumerate(data)]
    # tertiary_y_plus = [[pl.LpVariable(name=f'tertiary_y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    # tertiary_y_minus = [[pl.LpVariable(name=f'tertiary_y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    tertiary_APRR = [[pl.LpVariable(name=f'tertiary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in
                     intervals]
    s_tertiary_APR_upwards = [pl.LpVariable(name=f's_tertiary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_tertiary_APR_downwards = [pl.LpVariable(name=f's_tertiary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:
                for t in intervals[1:]:
                    tertiary_up_bound = reserve_activation_bound(
                        gen, "Tertiary_Active_Power_Reserves(MW)", 0, t - 1, operating_state
                    )
                    tertiary_down_bound = reserve_activation_bound(
                        gen, "Tertiary_Active_Power_Reserves(MW)", 1, t - 1, operating_state
                    )
                    if i in on_AGC:
                        if gen['availability'][t - 1] == 0:
                            prob += tertiary_ActPR_plus[i][t] == 0
                            prob += tertiary_ActPR_minus[i][t] == 0
                        else:

                            prob += tertiary_ActPR_plus[i][t] <= min(operating_state['max-power'][t-1], gen['availability'][t-1]) - (power[i][t] + primary_ActPR_plus[i][t] + secondary_ActPR_plus[i][t]) + M * y_plus[i][t]
                            prob += tertiary_ActPR_plus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][0] + M * y_plus[i][t]

                            prob += tertiary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t] - secondary_ActPR_minus[i][t]) - operating_state['min-power'][t - 1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]
                            prob += tertiary_ActPR_minus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]

###########################################################

                            prob += tertiary_ActPR_plus[i][t] <= tertiary_up_bound * (1 - y_plus[i][t])

                            prob += tertiary_ActPR_minus[i][t] <= tertiary_down_bound * (1 - y_minus[i][t])

##########################################################
                            # take into account only spinning active power reserves (for now)
                            prob += tertiary_ActPR_plus[i][t] <= tertiary_up_bound * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += tertiary_ActPR_minus[i][t] <= tertiary_down_bound * u_2_dict[(gen_id, t, operating_state_id)]
                    else:
                        if gen['availability'][t - 1] == 0:
                            prob += tertiary_ActPR_plus[i][t] == 0
                            prob += tertiary_ActPR_minus[i][t] == 0
                        else:


                            prob += tertiary_ActPR_plus[i][t] <= min(gen['availability'][t-1], operating_state["max-power"][t-1]) - (power[i][t] + primary_ActPR_plus[i][t] + secondary_ActPR_plus[i][t])
                            prob += tertiary_ActPR_plus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][0]


                            prob += tertiary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t] - secondary_ActPR_minus[i][t]) - operating_state["min-power"][t-1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += tertiary_ActPR_minus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])


                            # take into account only spinning active power reserves (for now)
                            prob += tertiary_ActPR_plus[i][t] <= tertiary_up_bound * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += tertiary_ActPR_minus[i][t] <= tertiary_down_bound * u_2_dict[(gen_id, t, operating_state_id)]

        for t in intervals[1:]:  # calculate the cost of APR only for this time horizon (2nd dispatch period up to the first of the next time horizon)
            objective_terms += tertiary_ActPR_plus[i][t] * gen['Tertiary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + tertiary_ActPR_minus[i][t] * gen['Tertiary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]

    for t in intervals[1:]:
        prob += pl.lpSum(tertiary_ActPR_minus[i][t] for i in range(len(data))) == tertiary_APRR[t][1] - s_tertiary_APR_downwards[t]
        prob += pl.lpSum(tertiary_ActPR_plus[i][t] for i in range(len(data))) == tertiary_APRR[t][0] - s_tertiary_APR_upwards[t]

        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][2]/100) * largest_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][3]/100) * largest_two_online_capacity[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        # objective_terms += (tertiary_APRR[t][0] + tertiary_APRR[t][1]) * 100
        objective_terms += s_tertiary_APR_upwards[t] * input_data["Cost_parameters"]["x_tertiary_APR_up"] + s_tertiary_APR_downwards[t] * input_data["Cost_parameters"]["x_tertiary_APR_down"]
        # prob += tertiary_APRR[t][0] == 0.2 * RES_sum[t] + 0.08 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        # prob += tertiary_APRR[t][1] == 0.2 * RES_sum[t] + 0.08 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
    return prob, objective_terms, tertiary_ActPR_plus, tertiary_ActPR_minus, tertiary_APRR, s_tertiary_APR_upwards, s_tertiary_APR_downwards


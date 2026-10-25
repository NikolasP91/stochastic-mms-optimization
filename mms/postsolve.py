"""Post-solve variable parsing, violation summaries, and legacy output assembly."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original post-solve processing.

import re
import time

import numpy as np
import pandas as pd

def extract_numbers_4(item):
    """Extract numbers 4 values from solver variable names or tables."""
    match = re.search(r'_(\d+)_(\d+)_(\d+)', item[0])
    generator_number = int(match.group(1))
    hour = int(match.group(2))
    n = int(match.group(3))
    return generator_number, hour, n

def extract_numbers(item):
    """Extract numbers values from solver variable names or tables."""
    match = re.search(r'_(\d+)_(\d+)$', item[0])
    generator_number = int(match.group(1)) if match else 0
    hour = int(match.group(2)) if match else 0
    return generator_number, hour

def extract_single_value(item):
    """Extract single value values from solver variable names or tables."""
    match = re.search(r'_(\d+)$', item[0])
    value = int(match.group(1)) if match else 0
    return value

def extract_all_numbers(item):
    """Extract all numbers values from solver variable names or tables."""
    return tuple(int(value) for value in re.findall(r'\d+', item[0]))

def extract_numbers_3(item):
    """Extract numbers 3 values from solver variable names or tables."""
    match = re.search(r'_(\d+)_(\d+)_(\d+)_(\d+)$', item[0])
    unit = int(match.group(2)) if match else 0
    hour = int(match.group(3)) if match else 0
    level = int(match.group(4)) if match else 0
    return unit, hour, level

def extract_numbers_2(item):
    """Extract numbers 2 values from solver variable names or tables."""
    match = re.search(r'(\d+)_(\d+)$', item[0])
    unit = int(match.group(1)) if match else 0
    hour = int(match.group(2)) if match else 0
    return unit, hour

def extract_gen_hour(df):
    """Extract gen hour values from solver variable names or tables."""
    df['Generator'], df['Hour'] = zip(*df['Variable'].map(lambda x: map(int, re.findall(r'\d+', x))))
    return df

def pivot_df(df):
    """Handle pivot df logic for post-solve variable parsing, violation summaries, and legacy output assembly."""
    return df.pivot(index='Generator', columns='Hour', values='Value')

def solution_processing(solution, input_data):
    # solution data processing & manipulation
    # --------------------------------------------------------------------------------------------------------------------#
    # Create a dataframe containing the RDAS solution
    """Parse PuLP variable names into structured DataFrames for post-solve reporting."""
    import re
    import pandas as pd
    start_time_2 = time.time()
    # Create empty lists to hold decision variable data
    power_values = []
    startup_values = []
    shutdown_values = []
    state_values = []

    s_power_plus_values = []
    s_power_minus_values = []

    #     y_up_values = []
    #     y_down_values = []
    # s_ru_values = []
    # s_rd_values = []




    #     on_prev_values = []
    #     remaining_run_values = []
    z_1_values = []
    u_1_values = []
    u_2_values = []
    delta_values = []
    # z_3_values = []
    # y_res_1_values = []
    unit_cost_values = []
    # Count_values = []
    RES_sum_values = []



    # s_res_values = []
    # y_res_3_values = []
    # y_res_2_values = []
    # k_value = []
    #
    # Percentage_of_Usage_values = []

    # Grid_Capacity_values = []




    if 1:  #input_data["constraints"]["availability_constraint"]:
        s_avail_values = []
        for v in solution:
            if v.name.startswith('s_avail'):
                s_avail_values.append((v.name, v.varValue))
        s_avail_values = sorted(s_avail_values, key=extract_numbers)
        s_avail_values_df = pd.DataFrame(s_avail_values, columns=['Variable', 'Value'])
    else:
        s_avail_values_df = pd.DataFrame()

    if input_data["constraints"]["OOS_mode_constraints"]:
        s_power_OOS_less_plus_values = []
        s_power_OOS_more_minus_values = []
        for v in solution:
            if v.name.startswith('s_power_OOS_less_plus_'):
                s_power_OOS_less_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_power_OOS_more_minus_'):
                s_power_OOS_more_minus_values.append((v.name, v.varValue))
        s_power_OOS_less_plus_values = sorted(s_power_OOS_less_plus_values, key=extract_numbers)
        s_power_OOS_more_minus_values = sorted(s_power_OOS_more_minus_values, key=extract_numbers)
        s_power_OOS_less_plus_df = pd.DataFrame(s_power_OOS_less_plus_values, columns=['Variable', 'Value'])
        s_power_OOS_more_minus_df = pd.DataFrame(s_power_OOS_more_minus_values, columns=['Variable', 'Value'])

        s_power_OOS_less_plus_df = extract_gen_hour(s_power_OOS_less_plus_df)
        s_power_OOS_less_plus_df = pivot_df(s_power_OOS_less_plus_df)

        s_power_OOS_more_minus_df = extract_gen_hour(s_power_OOS_more_minus_df)
        s_power_OOS_more_minus_df = pivot_df(s_power_OOS_more_minus_df)

    else:
        # Create empty DataFrame to return
        s_power_OOS_less_plus_df = s_power_OOS_more_minus_df = pd.DataFrame()

    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        s_min_a_left_values = []
        s_min_a_1_values = []
        for v in solution:
            if v.name.startswith('s_min_a_left'):
                s_min_a_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_a_1'):
                s_min_a_1_values.append((v.name, v.varValue))
        s_min_a_left_values = sorted(s_min_a_left_values, key=extract_numbers)
        s_min_a_1_values = sorted(s_min_a_1_values, key=extract_numbers)
        s_min_a_left_df = pd.DataFrame(s_min_a_left_values, columns=['Variable', 'Value'])
        s_min_a_1_df = pd.DataFrame(s_min_a_1_values, columns=['Variable', 'Value'])
        # s_min_a_left_df = extract_gen_hour(s_min_a_left_df)
        # s_min_a_left_df = pivot_df(s_min_a_left_df)
        #
        # s_min_a_1_df = extract_gen_hour(s_min_a_1_df)
        # s_min_a_1_df = pivot_df(s_min_a_1_df)
    else:
        # Create empty DataFrame to return
        s_min_a_left_df = s_min_a_1_df = pd.DataFrame()

    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        s_min_b_left_values = []
        s_min_b_1_values = []

        for v in solution:
            if v.name.startswith('s_min_b_left'):
                s_min_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_b_1'):
                s_min_b_1_values.append((v.name, v.varValue))
        s_min_b_left_values = sorted(s_min_b_left_values, key=extract_numbers)
        s_min_b_1_values = sorted(s_min_b_1_values, key=extract_numbers)
        s_min_b_left_df = pd.DataFrame(s_min_b_left_values, columns=['Variable', 'Value'])
        s_min_b_1_df = pd.DataFrame(s_min_b_1_values, columns=['Variable', 'Value'])
    else:
        s_min_b_left_df = s_min_b_1_df = pd.DataFrame()

    if input_data["constraints"].get("operating_states_max_time_constraint", False):
        s_max_oper_state_time_left_values = []
        s_max_oper_state_time_1_values = []
        for v in solution:
            if v.name.startswith('s_max_oper_state_time_left'):
                s_max_oper_state_time_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_max_oper_state_time_1'):
                s_max_oper_state_time_1_values.append((v.name, v.varValue))
        s_max_oper_state_time_left_values = sorted(s_max_oper_state_time_left_values, key=extract_all_numbers)
        s_max_oper_state_time_1_values = sorted(s_max_oper_state_time_1_values, key=extract_all_numbers)
        s_max_oper_state_time_left_df = pd.DataFrame(s_max_oper_state_time_left_values, columns=['Variable', 'Value'])
        s_max_oper_state_time_1_df = pd.DataFrame(s_max_oper_state_time_1_values, columns=['Variable', 'Value'])
    else:
        s_max_oper_state_time_left_df = s_max_oper_state_time_1_df = pd.DataFrame()

    if (
        input_data["constraints"].get("operating_states_max_transition_time_between_states_constraint_b", False)
        or input_data["constraints"].get("operating_states_max_time_constraint_b", False)
    ):
        s_max_oper_state_time_b_left_values = []
        s_max_oper_state_time_b_1_values = []
        for v in solution:
            if v.name.startswith('s_max_oper_state_time_b_left'):
                s_max_oper_state_time_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_max_oper_state_time_b_1'):
                s_max_oper_state_time_b_1_values.append((v.name, v.varValue))
        s_max_oper_state_time_b_left_values = sorted(s_max_oper_state_time_b_left_values, key=extract_all_numbers)
        s_max_oper_state_time_b_1_values = sorted(s_max_oper_state_time_b_1_values, key=extract_all_numbers)
        s_max_oper_state_time_b_left_df = pd.DataFrame(s_max_oper_state_time_b_left_values, columns=['Variable', 'Value'])
        s_max_oper_state_time_b_1_df = pd.DataFrame(s_max_oper_state_time_b_1_values, columns=['Variable', 'Value'])
    else:
        s_max_oper_state_time_b_left_df = s_max_oper_state_time_b_1_df = pd.DataFrame()

    if input_data["constraints"].get("operating_states_min_time_constraint_a", False):
        s_min_oper_state_time_a_left_values = []
        s_min_oper_state_time_a_1_values = []
        for v in solution:
            if v.name.startswith('s_min_oper_state_time_a_left'):
                s_min_oper_state_time_a_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_oper_state_time_a_1'):
                s_min_oper_state_time_a_1_values.append((v.name, v.varValue))
        s_min_oper_state_time_a_left_values = sorted(s_min_oper_state_time_a_left_values, key=extract_all_numbers)
        s_min_oper_state_time_a_1_values = sorted(s_min_oper_state_time_a_1_values, key=extract_all_numbers)
        s_min_oper_state_time_a_left_df = pd.DataFrame(s_min_oper_state_time_a_left_values, columns=['Variable', 'Value'])
        s_min_oper_state_time_a_1_df = pd.DataFrame(s_min_oper_state_time_a_1_values, columns=['Variable', 'Value'])
    else:
        s_min_oper_state_time_a_left_df = s_min_oper_state_time_a_1_df = pd.DataFrame()

    # Generic operating-state minimum dwell-time slacks. The preferred flag is
    # operating_states_min_time_constraint; the old _b flag is accepted as a
    # legacy alias, while historical slack variable names still include "_b".
    if (
        input_data["constraints"].get("operating_states_min_time_constraint", False)
        or input_data["constraints"].get("operating_states_min_time_constraint_b", False)
    ):
        s_min_oper_state_time_b_left_values = []
        s_min_oper_state_time_b_1_values = []
        for v in solution:
            if v.name.startswith('s_min_oper_state_time_b_left'):
                s_min_oper_state_time_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_oper_state_time_b_1'):
                s_min_oper_state_time_b_1_values.append((v.name, v.varValue))
        s_min_oper_state_time_b_left_values = sorted(s_min_oper_state_time_b_left_values, key=extract_all_numbers)
        s_min_oper_state_time_b_1_values = sorted(s_min_oper_state_time_b_1_values, key=extract_all_numbers)
        s_min_oper_state_time_b_left_df = pd.DataFrame(s_min_oper_state_time_b_left_values, columns=['Variable', 'Value'])
        s_min_oper_state_time_b_1_df = pd.DataFrame(s_min_oper_state_time_b_1_values, columns=['Variable', 'Value'])
    else:
        s_min_oper_state_time_b_left_df = s_min_oper_state_time_b_1_df = pd.DataFrame()

    if input_data["constraints"].get("state_min_time_constraint", input_data["constraints"].get("states_time_constraint", False)):
        s_min_state_b_left_values = []
        s_min_state_b_1_values = []
        for v in solution:
            if v.name.startswith('s_min_state_b_left'):
                s_min_state_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_state_b_1'):
                s_min_state_b_1_values.append((v.name, v.varValue))
        s_min_state_b_left_values = sorted(s_min_state_b_left_values, key=extract_numbers)
        s_min_state_b_1_values = sorted(s_min_state_b_1_values, key=extract_numbers)
        s_min_state_b_left_df = pd.DataFrame(s_min_state_b_left_values, columns=['Variable', 'Value'])
        s_min_state_b_1_df = pd.DataFrame(s_min_state_b_1_values, columns=['Variable', 'Value'])
    else:
        s_min_state_b_left_df = s_min_state_b_1_df = pd.DataFrame()


    # if input_data["constraints"]["rdas_deviations_calculation_constraints"]:
    #     deviation_1_values = []
    #     y_4_values = []
    #     deviation_2_values = []
    #     y_5_values = []
    #     for v in solution:
    #         if v.name.startswith('dev_1'):
    #             deviation_1_values.append((v.name, v.varValue))
    #         elif v.name.startswith('y_4'):
    #             y_4_values.append((v.name, v.varValue))
    #         elif v.name.startswith('dev_2'):
    #             deviation_2_values.append((v.name, v.varValue))
    #         elif v.name.startswith('y_5'):
    #             y_5_values.append((v.name, v.varValue))
    #     y_4_values = sorted(y_4_values, key=extract_numbers)
    #     y_5_values = sorted(y_5_values, key=extract_numbers)
    #     deviation_1_values = sorted(deviation_1_values, key=extract_numbers)
    #     deviation_2_values = sorted(deviation_2_values, key=extract_numbers)
    #     deviation_1_df = pd.DataFrame(deviation_1_values, columns=['Variable', 'Value'])
    #     y_4_df = pd.DataFrame(y_4_values, columns=['Variable', 'Value'])
    #     deviation_2_df = pd.DataFrame(deviation_2_values, columns=['Variable', 'Value'])
    #     y_5_df = pd.DataFrame(y_5_values, columns=['Variable', 'Value'])
    # else:
    #     # Create empty DataFrame to return
    #     deviation_1_df = deviation_2_df = y_4_df = y_5_df = pd.DataFrame()
    if input_data["constraints"]["load_production_balance_constraint"] or input_data["constraints"]["load_production_Energy_balance_constraint"]:
        s_load_plus_values = []
        s_load_minus_values = []
        for v in solution:
            if v.name.startswith('s_load_plus'):
                s_load_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_load_minus'):
                s_load_minus_values.append((v.name, v.varValue))
        s_load_minus_values = sorted(s_load_minus_values, key=extract_single_value)
        s_load_plus_values = sorted(s_load_plus_values, key=extract_single_value)
        s_load_plus_df = pd.DataFrame(s_load_plus_values, columns=['Variable', 'Value'])
        s_load_minus_df = pd.DataFrame(s_load_minus_values, columns=['Variable', 'Value'])
    else:
        # Create empty DataFrame to return
        s_load_plus_df = s_load_minus_df = pd.DataFrame()

    if input_data["constraints"]["must_run_units_constraint"]:
        s_must_run_values = []
        for v in solution:
            if v.name.startswith('s_must_run'):
                s_must_run_values.append((v.name, v.varValue))
        s_must_run_values = sorted(s_must_run_values, key=extract_numbers)
        s_must_run_df = pd.DataFrame(s_must_run_values, columns=['Variable', 'Value'])
        s_must_run_df = extract_gen_hour(s_must_run_df)
        s_must_run_df = pivot_df(s_must_run_df)
    else:
        s_must_run_df = pd.DataFrame()
    # print(s_must_run_values)

    if input_data["constraints"]["primary_active_power_reserves_constraint"] or input_data["constraints"]["secondary_active_power_reserves_constraint"] or input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        N_1_values = []
        N_2_values = []
        s_N_1_values = []
        s_N_2_values = []

        for v in solution:
            if v.name.startswith('N_1_'):
                N_1_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('N_2_'):
                N_2_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('s_N_1_'):
                s_N_1_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('s_N_2_'):
                s_N_2_values.append((v.name, round(float(v.varValue), 8)))

        N_1_values = sorted(N_1_values, key=extract_numbers_2)
        N_2_values = sorted(N_2_values, key=extract_numbers_2)
        s_N_1_values = sorted(s_N_1_values, key=extract_numbers_2)
        s_N_2_values = sorted(s_N_2_values, key=extract_numbers_2)


        N_1_df = pd.DataFrame(N_1_values, columns=['Variable', 'Value'])
        N_2_df = pd.DataFrame(N_2_values, columns=['Variable', 'Value'])
        s_N_1_df = pd.DataFrame(s_N_1_values, columns=['Variable', 'Value'])
        s_N_2_df = pd.DataFrame(s_N_2_values, columns=['Variable', 'Value'])


    else:
        N_1_df = N_2_df = s_N_1_df = s_N_2_df = pd.DataFrame()


    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        primary_ActPR_plus_values = []
        primary_ActPR_minus_values = []
        primary_APRR_values = []
        s_primary_APR_upwards_values = []
        s_primary_APR_downwards_values = []
        binary_primary_values = []
        for v in solution:
            if v.name.startswith('primary_ActPR_plus'):
                primary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('primary_ActPR_minus'):
                primary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('primary_APRR'):
                primary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_primary_APR_upwards'):
                s_primary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_primary_APR_downwards'):
                s_primary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_primary'):
                binary_primary_values.append((v.name, round(float(v.varValue), 8)))
        s_primary_APR_upwards_values = sorted(s_primary_APR_upwards_values, key=extract_single_value)
        # print(s_primary_APR_upwards_values)
        s_primary_APR_downwards_values = sorted(s_primary_APR_downwards_values, key=extract_single_value)
        # print(s_primary_APR_downwards_values)
        s_primary_APR_upwards_df = pd.DataFrame(s_primary_APR_upwards_values, columns=['Variable', 'Value'])
        s_primary_APR_downwards_df = pd.DataFrame(s_primary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_primary_values = sorted(binary_primary_values, key=extract_numbers_4)

        primary_ActPR_minus_values = sorted(primary_ActPR_minus_values, key=extract_numbers_2)
        primary_ActPR_plus_values = sorted(primary_ActPR_plus_values, key=extract_numbers_2)
        primary_APRR_values = sorted(primary_APRR_values, key=extract_numbers)
        primary_ActPR_plus_df = pd.DataFrame(primary_ActPR_plus_values, columns=['Variable', 'Value'])
        primary_ActPR_minus_df = pd.DataFrame(primary_ActPR_minus_values, columns=['Variable', 'Value'])
        primary_APRR_df = pd.DataFrame(primary_APRR_values, columns=['Variable', 'Value'])
        binary_primary_df = pd.DataFrame(binary_primary_values, columns=['Variable', 'Value'])
        primary_ActPR_plus_df = extract_gen_hour(primary_ActPR_plus_df)
        primary_ActPR_minus_df = extract_gen_hour(primary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        primary_ActPR_plus_df = primary_ActPR_minus_df = primary_APRR_df = s_primary_APR_upwards_df = s_primary_APR_downwards_df = binary_primary_df = pd.DataFrame()
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:

        secondary_ActPR_plus_values = []
        secondary_ActPR_minus_values = []
        secondary_APRR_values = []
        s_secondary_APR_upwards_values = []
        s_secondary_APR_downwards_values = []
        binary_secondary_values = []

        for v in solution:
            if v.name.startswith('secondary_ActPR_plus'):
                secondary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('secondary_ActPR_minus'):
                secondary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('secondary_APRR'):
                secondary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_secondary_APR_upwards'):
                s_secondary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_secondary_APR_downwards'):
                s_secondary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_secondary'):
                binary_secondary_values.append((v.name, round(v.varValue, 8)))
        s_secondary_APR_upwards_values = sorted(s_secondary_APR_upwards_values, key=extract_single_value)
        s_secondary_APR_downwards_values = sorted(s_secondary_APR_downwards_values, key=extract_single_value)
        s_secondary_APR_upwards_df = pd.DataFrame(s_secondary_APR_upwards_values, columns=['Variable', 'Value'])
        s_secondary_APR_downwards_df = pd.DataFrame(s_secondary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_secondary_values = sorted(binary_secondary_values, key=extract_numbers_4)

        secondary_ActPR_minus_values = sorted(secondary_ActPR_minus_values, key=extract_numbers_2)
        secondary_ActPR_plus_values = sorted(secondary_ActPR_plus_values, key=extract_numbers_2)
        secondary_APRR_values = sorted(secondary_APRR_values, key=extract_numbers)
        secondary_ActPR_plus_df = pd.DataFrame(secondary_ActPR_plus_values, columns=['Variable', 'Value'])
        secondary_ActPR_minus_df = pd.DataFrame(secondary_ActPR_minus_values, columns=['Variable', 'Value'])
        secondary_APRR_df = pd.DataFrame(secondary_APRR_values, columns=['Variable', 'Value'])
        binary_secondary_df = pd.DataFrame(binary_secondary_values, columns=['Variable', 'Value'])
        secondary_ActPR_plus_df = extract_gen_hour(secondary_ActPR_plus_df)
        secondary_ActPR_minus_df = extract_gen_hour(secondary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        secondary_ActPR_plus_df = secondary_ActPR_minus_df = secondary_APRR_df = s_secondary_APR_upwards_df = s_secondary_APR_downwards_df = binary_secondary_df = pd.DataFrame()
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        tertiary_ActPR_plus_values = []
        tertiary_ActPR_minus_values = []
        tertiary_APRR_values = []
        s_tertiary_APR_upwards_values = []
        s_tertiary_APR_downwards_values = []
        binary_tertiary_values = []

        for v in solution:
            if v.name.startswith('tertiary_ActPR_plus'):
                tertiary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('tertiary_ActPR_minus'):
                tertiary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('tertiary_APRR'):
                tertiary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_tertiary_APR_upwards'):
                s_tertiary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_tertiary_APR_downwards'):
                s_tertiary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_tertiary'):
                binary_tertiary_values.append((v.name, round(v.varValue, 8)))
        s_tertiary_APR_upwards_values = sorted(s_tertiary_APR_upwards_values, key=extract_single_value)
        s_tertiary_APR_downwards_values = sorted(s_tertiary_APR_downwards_values, key=extract_single_value)
        s_tertiary_APR_upwards_df = pd.DataFrame(s_tertiary_APR_upwards_values, columns=['Variable', 'Value'])
        s_tertiary_APR_downwards_df = pd.DataFrame(s_tertiary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_tertiary_values = sorted(binary_tertiary_values, key=extract_numbers_4)

        tertiary_ActPR_minus_values = sorted(tertiary_ActPR_minus_values, key=extract_numbers_2)
        tertiary_ActPR_plus_values = sorted(tertiary_ActPR_plus_values, key=extract_numbers_2)
        tertiary_APRR_values = sorted(tertiary_APRR_values, key=extract_numbers)
        tertiary_ActPR_plus_df = pd.DataFrame(tertiary_ActPR_plus_values, columns=['Variable', 'Value'])
        tertiary_ActPR_minus_df = pd.DataFrame(tertiary_ActPR_minus_values, columns=['Variable', 'Value'])
        tertiary_APRR_df = pd.DataFrame(tertiary_APRR_values, columns=['Variable', 'Value'])
        binary_tertiary_df = pd.DataFrame(binary_tertiary_values, columns=['Variable', 'Value'])
        tertiary_ActPR_plus_df = extract_gen_hour(tertiary_ActPR_plus_df)
        tertiary_ActPR_minus_df = extract_gen_hour(tertiary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        tertiary_ActPR_plus_df = tertiary_ActPR_minus_df = tertiary_APRR_df = s_tertiary_APR_upwards_df = s_tertiary_APR_downwards_df = binary_tertiary_df = pd.DataFrame()
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        setpoint_values = []
        Min_grid_capacity_1_values = []
        Min_grid_capacity_2_values = []
        Min_Power_Calc_values = []
        Grid_Capacity1_values = []
        Grid_Capacity2_values = []
        Grid_Capacity3_values = []
        g1_values = []
        g2_values = []
        g3_values = []
        g4_values = []
        g5_values = []

        m_values = []

        s_Grid_Capacity_1_values = []
        s_Grid_Capacity_2_values = []
        s_Grid_Capacity_3_values = []

        P_RES_values = []
        P_PV_values = []
        P_sp_values = []
        for v in solution:
            if v.name.startswith('setpoint'):
                setpoint_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_grid_capacity_1'):
                Min_grid_capacity_1_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_grid_capacity_2'):
                Min_grid_capacity_2_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_Power_Calc'):
                Min_Power_Calc_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity1'):
                Grid_Capacity1_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity2'):
                Grid_Capacity2_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity3'):
                Grid_Capacity3_values.append((v.name, v.varValue))
            elif v.name.startswith('m'):
                m_values.append((v.name, v.varValue))
            elif v.name.startswith('g1'):
                g1_values.append((v.name, v.varValue))
            elif v.name.startswith('g2'):
                g2_values.append((v.name, v.varValue))
            elif v.name.startswith('g3'):
                g3_values.append((v.name, v.varValue))
            elif v.name.startswith('g4'):
                g4_values.append((v.name, v.varValue))
            elif v.name.startswith('g5'):
                g5_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_1'):
                s_Grid_Capacity_1_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_2'):
                s_Grid_Capacity_2_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_3'):
                s_Grid_Capacity_3_values.append((v.name, v.varValue))

            elif v.name.startswith('P_RES_'):
                P_RES_values.append((v.name, v.varValue))
            elif v.name.startswith('P_PV_'):
                P_PV_values.append((v.name, v.varValue))
            elif v.name.startswith('P_sp_'):
                P_sp_values.append((v.name, v.varValue))



        setpoint_values = sorted(setpoint_values, key=extract_numbers)
        Min_grid_capacity_1_values = sorted(Min_grid_capacity_1_values, key=extract_single_value)
        Min_grid_capacity_2_values = sorted(Min_grid_capacity_2_values, key=extract_single_value)
        Min_Power_Calc_values = sorted(Min_Power_Calc_values, key=extract_numbers)

        Grid_Capacity1_values = sorted(Grid_Capacity1_values, key=extract_single_value)
        Grid_Capacity2_values = sorted(Grid_Capacity2_values, key=extract_single_value)
        Grid_Capacity3_values = sorted(Grid_Capacity3_values, key=extract_single_value)
        g1_values = sorted(g1_values, key=extract_single_value)
        g2_values = sorted(g2_values, key=extract_single_value)
        g3_values = sorted(g3_values, key=extract_numbers)
        g4_values = sorted(g4_values, key=extract_numbers)
        g5_values = sorted(g5_values, key=extract_single_value)

        m_values = sorted(m_values, key=extract_numbers)

        s_Grid_Capacity_1_values = sorted(s_Grid_Capacity_1_values, key=extract_single_value)
        s_Grid_Capacity_2_values = sorted(s_Grid_Capacity_2_values, key=extract_single_value)
        s_Grid_Capacity_3_values = sorted(s_Grid_Capacity_3_values, key=extract_single_value)

        P_RES_values = sorted(P_RES_values, key=extract_single_value)
        P_PV_values = sorted(P_PV_values, key=extract_single_value)
        P_sp_values = sorted(P_sp_values, key=extract_single_value)


        setpoint_df = pd.DataFrame(setpoint_values, columns=['Variable', 'Value'])
        Min_Power_Calc_df = pd.DataFrame(Min_Power_Calc_values, columns=['Variable', 'Value'])
        g3_df = pd.DataFrame(g3_values, columns=['Variable', 'Value'])
        g4_df = pd.DataFrame(g4_values, columns=['Variable', 'Value'])
        g5_df = pd.DataFrame(g5_values, columns=['Variable', 'Value'])

        s_Grid_Capacity_1_df = pd.DataFrame(s_Grid_Capacity_1_values, columns=['Variable', 'Value'])
        s_Grid_Capacity_2_df = pd.DataFrame(s_Grid_Capacity_2_values, columns=['Variable', 'Value'])
        s_Grid_Capacity_3_df = pd.DataFrame(s_Grid_Capacity_3_values, columns=['Variable', 'Value'])

        P_RES_df = pd.DataFrame(P_RES_values, columns=['Variable', 'Value'])
        P_PV_df = pd.DataFrame(P_PV_values, columns=['Variable', 'Value'])
        P_sp_df = pd.DataFrame(P_sp_values, columns=['Variable', 'Value'])

        Min_grid_capacity_1_df = pd.DataFrame(Min_grid_capacity_1_values, columns=['Variable', 'Value'])
        Min_grid_capacity_2_df = pd.DataFrame(Min_grid_capacity_2_values, columns=['Variable', 'Value'])
        Grid_Capacity1_df = pd.DataFrame(Grid_Capacity1_values, columns=['Variable', 'Value'])
        Grid_Capacity2_df = pd.DataFrame(Grid_Capacity2_values, columns=['Variable', 'Value'])
        Grid_Capacity3_df = pd.DataFrame(Grid_Capacity3_values, columns=['Variable', 'Value'])
        g1_df = pd.DataFrame(g1_values, columns=['Variable', 'Value'])
        g2_df = pd.DataFrame(g2_values, columns=['Variable', 'Value'])
        m_df = pd.DataFrame(m_values, columns=['Variable', 'Value'])
        setpoint_df = extract_gen_hour(setpoint_df)
        setpoint_df = pivot_df(setpoint_df)
        Min_Power_Calc_df = extract_gen_hour(Min_Power_Calc_df )
        Min_Power_Calc_df = pivot_df(Min_Power_Calc_df)
        # g3_df = pd.DataFrame(g3_values, columns=['Variable', 'Value'])
        # g3_df = extract_gen_hour(g3_df)
        # g3_df = pivot_df(g3_df)
    else:
        Min_grid_capacity_1_df = Min_grid_capacity_2_df = Min_Power_Calc_df = Grid_Capacity1_df = Grid_Capacity2_df = Grid_Capacity3_df = g1_df = g2_df = g3_df = g4_df = g5_df = m_df = setpoint_df = s_Grid_Capacity_1_df = s_Grid_Capacity_2_df = s_Grid_Capacity_3_df = P_RES_df = P_PV_df = P_sp_df = pd.DataFrame()
    # total_actual_cost_values = []
    #
    # actual_cost_2_values = []


    if input_data["constraints"]["forbidden_zones_constraint"]:
        y_zone_values = []
        s_forbidden_zones_plus_values = []
        s_forbidden_zones_minus_values = []
        for v in solution:
            if v.name.startswith('y_zone'):
                y_zone_values.append((v.name, v.varValue))
            elif v.name.startswith('s_forbidden_zones_plus'):
                s_forbidden_zones_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_forbidden_zones_minus'):
                s_forbidden_zones_minus_values.append((v.name, v.varValue))

        y_zone_values = sorted(y_zone_values, key=extract_numbers_4)
        y_zone_df = pd.DataFrame(y_zone_values, columns=['Variable', 'Value'])
        s_forbidden_zones_plus_values = sorted(s_forbidden_zones_plus_values, key=extract_numbers)
        s_forbidden_zones_plus_df = pd.DataFrame(s_forbidden_zones_plus_values, columns=['Variable', 'Value'])
        s_forbidden_zones_minus_values = sorted(s_forbidden_zones_minus_values, key=extract_numbers)
        s_forbidden_zones_minus_df = pd.DataFrame(s_forbidden_zones_minus_values, columns=['Variable', 'Value'])
    else:
        y_zone_df = pd.DataFrame()
        s_forbidden_zones_plus_df = pd.DataFrame()
        s_forbidden_zones_minus_df = pd.DataFrame()

    if input_data["constraints"]["testing_mode_constraints"]:
        s_power_testing_mode_plus_values = []
        s_power_testing_mode_minus_values = []
        for v in solution:
            if v.name.startswith('s_power_testing_plus_'):
                s_power_testing_mode_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_power_testing_minus_'):
                s_power_testing_mode_minus_values.append((v.name, v.varValue))
        s_power_testing_mode_plus_values = sorted(s_power_testing_mode_plus_values, key=extract_numbers)
        s_power_testing_mode_minus_values = sorted(s_power_testing_mode_minus_values, key=extract_numbers)

        s_power_testing_mode_plus_df = pd.DataFrame(s_power_testing_mode_plus_values, columns=['Variable', 'Value'])
        s_power_testing_mode_minus_df = pd.DataFrame(s_power_testing_mode_minus_values, columns=['Variable', 'Value'])

        s_power_testing_mode_plus_df = extract_gen_hour(s_power_testing_mode_plus_df)
        s_power_testing_mode_plus_df = pivot_df(s_power_testing_mode_plus_df)

        s_power_testing_mode_minus_df = extract_gen_hour(s_power_testing_mode_minus_df)
        s_power_testing_mode_minus_df = pivot_df(s_power_testing_mode_minus_df)
    else:
        s_power_testing_mode_plus_df = s_power_testing_mode_minus_df = pd.DataFrame()

    # Extract decision variable values from solution
    for v in solution:
        if v.name.startswith('power'):
            power_values.append((v.name, v.varValue))
        elif v.name.startswith('startup'):
            startup_values.append((v.name, v.varValue))
        elif v.name.startswith('shutdown'):
            shutdown_values.append((v.name, v.varValue))
        elif v.name.startswith('state'):
            state_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_ru'):
        #     s_ru_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_rd'):
        #     s_rd_values.append((v.name, v.varValue))
        elif v.name.startswith('z_1'):
            z_1_values.append((v.name, v.varValue))
        elif v.name.startswith('u_1'):
            u_1_values.append((v.name, v.varValue))
        elif v.name.startswith('u_2'):
            u_2_values.append((v.name, v.varValue))
        elif v.name.startswith('delta_'):
            delta_values.append((v.name, v.varValue))
        elif v.name.startswith('unit_cost_'):
            unit_cost_values.append((v.name, v.varValue))
        # elif v.name.startswith('z_3'):
        #     z_3_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_APR_up'):
        #     s_APR_upwards_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('s_APR_down'):
        #     s_APR_downwards_values.append((v.name, v.varValue))

        # elif v.name.startswith('y_res_1'):
        #     y_res_1_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('y_res_2'):
        #     y_res_2_values.append((v.name, v.varValue))

        # elif v.name.startswith('Count'):
        #     Count_values.append((v.name, v.varValue))
        elif v.name.startswith('RES_sum'):
            RES_sum_values.append((v.name, v.varValue))
        elif v.name.startswith('s_power_plus'):
            s_power_plus_values.append((v.name, v.varValue))
        elif v.name.startswith('s_power_minus'):
            s_power_minus_values.append((v.name, v.varValue))

        # elif v.name.startswith('s_res'):
        #     s_res_values.append((v.name, v.varValue))
        # elif v.name.startswith('k'):
        #     k_value.append((v.name, v.varValue))
        # elif v.name.startswith('y_res_3'):
        #     y_res_3_values.append((v.name, v.varValue))
        # elif v.name.startswith('Percentage_of_Usage'):
        #     Percentage_of_Usage_values.append((v.name, v.varValue))
        # elif v.name.startswith('mult'):
        #     mult_values.append((v.name, v.varValue))
        # elif v.name.startswith('Grid'):
        #     Grid_Capacity_values.append((v.name, v.varValue))
        #         elif v.name.startswith('y_up'):
        #             y_up_values.append((v.name, v.varValue))
        #         elif v.name.startswith('y_down'):
        #             y_down_values.append((v.name, v.varValue))

        #         elif v.name.startswith('on_prev'):
        #             on_prev_values.append((v.name, v.varValue))

        # elif v.name.startswith('remaining_run'):
        #     remaining_run_values.append((v.name, v.varValue))
        # elif v.name.startswith('total_actual_cost'):
        #     total_actual_cost_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('actual_cost_2'):
        #     actual_cost_2_values.append((v.name, v.varValue))
    power_values = sorted(power_values, key=extract_numbers)
    startup_values = sorted(startup_values, key=extract_numbers)
    shutdown_values = sorted(shutdown_values, key=extract_numbers)
    state_values = sorted(state_values, key=extract_numbers)

    s_power_plus_values = sorted(s_power_plus_values, key=extract_numbers)
    s_power_minus_values = sorted(s_power_minus_values, key=extract_numbers)

    # total_actual_cost_values = sorted(total_actual_cost_values, key=extract_single_value)
    # actual_cost_2_values = sorted(actual_cost_2_values, key=extract_single_value)
    # y_res_1_values = sorted(y_res_1_values, key=extract_numbers_2)
    # y_res_1_values = sorted(y_res_1_values, key=extract_numbers_2)
    # s_ru_values = sorted(s_ru_values, key=extract_numbers)
    #
    # s_rd_values = sorted(s_rd_values, key=extract_numbers)
    # s_APR_upwards_values = sorted(s_APR_upwards_values, key=extract_single_value)
    #
    # s_APR_downwards_values = sorted(s_APR_downwards_values, key=extract_single_value)
    RES_sum_values = sorted(RES_sum_values, key=extract_single_value)
    # s_res_values = sorted(s_res_values, key=extract_numbers)
    z_1_values = sorted(z_1_values, key=extract_numbers_3)
    # z_3_values = sorted(z_3_values, key=extract_numbers_3)
    u_1_values = sorted(u_1_values, key=extract_numbers_3)
    delta_values = sorted(delta_values, key=extract_numbers_4)
    unit_cost_values = sorted(unit_cost_values, key=extract_numbers)
    u_2_values = sorted(u_2_values, key=extract_numbers_3)
    # Convert lists into DataFrames
    power_df = pd.DataFrame(power_values, columns=['Variable', 'Value'])
    startup_df = pd.DataFrame(startup_values, columns=['Variable', 'Value'])
    state_df = pd.DataFrame(state_values, columns=['Variable', 'Value'])

    s_power_plus_df = pd.DataFrame(s_power_plus_values, columns=['Variable', 'Value'])
    s_power_minus_df = pd.DataFrame(s_power_minus_values, columns=['Variable', 'Value'])

    #     y_up_df = pd.DataFrame(y_up_values, columns=['Variable', 'Value'])
    #     y_down_df = pd.DataFrame(y_down_values, columns=['Variable', 'Value'])
    # total_actual_cost_values_df = pd.DataFrame(total_actual_cost_values, columns=['Variable', 'Value'])
    # actual_cost_2_values_df = pd.DataFrame(actual_cost_2_values, columns=['Variable', 'Value'])
    # setpoint_df, Min_grid_capacity_df, Grid_Capacity1_df, Grid_Capacity2_df, g_df, m_df
    # s_ru_df = pd.DataFrame(s_ru_values, columns=['Variable', 'Value'])
    # s_rd_df = pd.DataFrame(s_rd_values, columns=['Variable', 'Value'])
    z_1_df = pd.DataFrame(z_1_values, columns=['Variable', 'Value'])
    u_1_df = pd.DataFrame(u_1_values, columns=['Variable', 'Value'])
    delta_df = pd.DataFrame(delta_values, columns=['Variable', 'Value'])
   # unit_cost_df = pd.DataFrame(unit_cost_values, columns=['Variable', 'Value'])
    # y_res_1_df = pd.DataFrame(y_res_1_values, columns=['Variable', 'Value'])
    #
    # y_res_2_df = pd.DataFrame(y_res_2_values, columns=['Variable', 'Value'])

    # Count_df = pd.DataFrame(Count_values, columns=['Variable', 'Value'])
    RES_sum_df = pd.DataFrame(RES_sum_values, columns=['Variable', 'Value'])
    # s_res_df = pd.DataFrame(s_res_values, columns=['Variable', 'Value'])
    # s_APR_upwards_df = pd.DataFrame(s_APR_upwards_values, columns=['Variable', 'Value'])
    # s_APR_downwards_df = pd.DataFrame(s_APR_downwards_values, columns=['Variable', 'Value'])
    # y_res_3_df = pd.DataFrame(y_res_3_values, columns=['Variable', 'Value'])
    # Percentage_of_Usage_df = pd.DataFrame(Percentage_of_Usage_values, columns=['Variable', 'Value'])
    # Grid_Capacity_df = pd.DataFrame(Grid_Capacity_values, columns=['Variable', 'Value'])
    shutdown_df = pd.DataFrame(shutdown_values, columns=['Variable', 'Value'])
    #     on_prev_df = pd.DataFrame(on_prev_values, columns=['Variable', 'Value'])
    #     remaining_run_df = pd.DataFrame(remaining_run_values, columns=['Variable', 'Value'])
    # mult_df = pd.DataFrame(mult_values, columns=['Variable', 'Value'])
    # z_3_df = pd.DataFrame(z_3_values, columns=['Variable', 'Value'])
    u_2_df = pd.DataFrame(u_2_values, columns=['Variable', 'Value'])
    # # Merge all DataFrames into one
    # solution_df = pd.concat([power_df, startup_df, state_df, y_up_df, y_down_df]).reset_index(drop=True)

    # # print(solution_df)
    power_df = extract_gen_hour(power_df)
   # unit_cost_df = extract_gen_hour(unit_cost_df)
    startup_df = extract_gen_hour(startup_df)
    shutdown_df = extract_gen_hour(shutdown_df)
    state_df = extract_gen_hour(state_df)

    s_power_plus_df = extract_gen_hour(s_power_plus_df)
    s_power_minus_df = extract_gen_hour(s_power_minus_df)

    # mult_df = extract_gen_hour(mult_df)
    #     y_up_df = extract_gen_hour(y_up_df)
    #     y_down_df = extract_gen_hour(y_down_df)
    # s_ru_df = extract_gen_hour(s_ru_df)
    # s_rd_df = extract_gen_hour(s_rd_df)
    #     s_load_plus_df  = extract_gen_hour(s_load_plus_df)
    #     s_load_minus_df  = extract_gen_hour(s_load_minus_df)
    #     z_df = extract_gen_hour(z_df)
    #     u_df = extract_gen_hour(u_df)
    #     on_prev_df = extract_gen_hour(on_prev_df)
    #     remaining_run_df = extract_gen_hour(remaining_run_df)

    # Pivot DataFrames to get one column per hour and one row per generator
    power_df = pivot_df(power_df)
    startup_df = pivot_df(startup_df)
    shutdown_df = pivot_df(shutdown_df)
    state_df = pivot_df(state_df)
    #unit_cost_df = pivot_df(unit_cost_df)

    s_power_plus_df = pivot_df(s_power_plus_df)
    s_power_minus_df = pivot_df(s_power_minus_df)

    if input_data["constraints"]["ramp_up_down_constraints"]:
        ramp_relax_values = []
        for v in solution:
            if v.name.startswith('ramp_relax'):
                ramp_relax_values.append((v.name, v.varValue))
                ramp_relax_values = sorted(ramp_relax_values, key=extract_numbers)
                ramp_relax_df = pd.DataFrame(ramp_relax_values, columns=['Variable', 'Value'])
                ramp_relax_df = extract_gen_hour(ramp_relax_df)
                ramp_relax_df = pivot_df(ramp_relax_df)
    else:
        ramp_relax_df = pd.DataFrame()



    # mult_df = pivot_df(mult_df)
    #     y_up_df = pivot_df(y_up_df)
    #     y_down_df = pivot_df(y_down_df)

    # s_ru_df = pivot_df(s_ru_df)
    # s_rd_df = pivot_df(s_rd_df)

    #     ActPR_plus_df  = pivot_df(ActPR_plus_df)

    #     s_load_plus_df  = pivot_df(s_load_plus_df )
    #     s_load_minus_df  = pivot_df(s_load_minus_df)

    #     z_df = pivot_df(z_df)
    #     u_df = pivot_df(u_df)

    #     on_prev_df = pivot_df(on_prev_df)
    #     remaining_run_df = pivot_df(remaining_run_df)

    # print(power_df)
    # print(startup_df)
    # print(state_df)

    # Create an empty DataFrame with the same columns as your existing ones
    # final_df = pd.DataFrame(columns=power_df.columns)
    #
    # # Loop through all the generator IDs and append Power, State, and Startup for each generator
    # for gen_id in power_df.index:
    #     if gen_id != 'Total_dispatched' and gen_id != 'Load Forecast':
    #         final_df.loc[f'Gen_{gen_id} Power'] = power_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} State'] = state_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} Startup'] = startup_df.loc[gen_id]
    #         #             final_df.loc[f'Gen_{gen_id} y_up'] = y_up_df.loc[gen_id]
    #         #             final_df.loc[f'Gen_{gen_id} y_down'] = y_down_df.loc[gen_id]
    #
    #         final_df.loc[f'Gen_{gen_id} s_ru'] = s_ru_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} s_rd'] = s_rd_df.loc[gen_id]

    #             final_df.loc[f'Gen_{gen_id} on_prev'] = on_prev_df.loc[gen_id]
    #             final_df.loc[f'Gen_{gen_id} remaining_run'] = remaining_run_df.loc[gen_id]

    # Add rows for total state (number of units ON), total startup units and total power
    # total_state = state_df.apply(lambda x: (x == 1.0).sum()).rename('# Units ON')
    # total_startup = startup_df.sum().rename('# Startup Units')
    # total_power = power_df.sum()

    # final_df = pd.concat([final_df, total_state, total_startup, total_power], axis=0)
    # final_df = final_df.append(state_df.apply(lambda x: (x == 1.0).sum()).rename('# Units ON'))
    # final_df = final_df.append(startup_df.sum().rename('# Startup Units'))
    # final_df.loc['Total Power Dispatched'] = power_df.sum()
    #
    # # Add load forecast to the DataFrame
    # final_df.loc['Load Forecast'] = Load_forecast
    end_time_2 = time.time()
    execution_time_2 = end_time_2 - start_time_2
    print("solution_processing function execution time:", round(execution_time_2, 3), "seconds")
    print('')
    return (
        power_df, state_df, startup_df, shutdown_df,  ramp_relax_df, s_load_plus_df, s_load_minus_df,
        z_1_df, u_1_df, primary_ActPR_plus_df, primary_ActPR_minus_df, s_primary_APR_upwards_df, s_primary_APR_downwards_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, s_tertiary_APR_upwards_df,
        s_tertiary_APR_downwards_df, secondary_ActPR_plus_df, secondary_ActPR_minus_df, s_secondary_APR_upwards_df, s_secondary_APR_downwards_df, RES_sum_df,
        primary_APRR_df, binary_primary_df, tertiary_APRR_df, binary_tertiary_df, secondary_APRR_df, binary_secondary_df, u_2_df, setpoint_df, Min_grid_capacity_1_df, Min_grid_capacity_2_df, Min_Power_Calc_df, Grid_Capacity1_df, Grid_Capacity2_df, Grid_Capacity3_df, g1_df, g2_df, g3_df, g4_df,
        m_df, y_zone_df, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df, s_must_run_df, s_min_a_left_df, s_min_a_1_df, s_min_b_left_df, s_min_b_1_df,
        s_max_oper_state_time_left_df, s_max_oper_state_time_1_df,
        s_max_oper_state_time_b_left_df, s_max_oper_state_time_b_1_df,
        s_min_oper_state_time_a_left_df, s_min_oper_state_time_a_1_df,
        s_min_oper_state_time_b_left_df, s_min_oper_state_time_b_1_df,
        s_min_state_b_left_df, s_min_state_b_1_df, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df,
        s_power_plus_df, s_power_minus_df, N_1_df, N_2_df, P_RES_df, P_PV_df, s_avail_values_df, s_N_1_df, s_N_2_df, P_sp_df, g5_df, delta_df, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df
    )  # y_up_df, y_down_df,

def setpoint_calculation(input_data, RES, PV, RES_forecast, Sum_RES_forecast, data, power_df, setpoint_df, state_df):
    """Reconstruct RES/PV setpoints from dispatch and selector variables."""
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:

        num_rows = len(RES_forecast)
        column_lengths = len(RES_forecast[0])

        # Convert the array to a DataFrame and transpose
        RES_forecast_df = pd.DataFrame(RES_forecast).transpose()

        # Set the column labels starting from 1
        RES_forecast_df.columns = [f' {i + 1}' for i in range(RES_forecast_df.shape[1])]

        # Adjust index to start from 1
        RES_forecast_df.index = RES_forecast_df.index + 1

        # Creating a MultiIndex with "Hour" as the top-level label
        hours = [str(i) for i in RES_forecast_df.index]
        RES_forecast_df.index = hours
        RES_forecast_df.columns = pd.MultiIndex.from_product([['Hour'], RES_forecast_df.columns])
        RES_forecast_df.index = pd.MultiIndex.from_product([['Generator'], RES_forecast_df.index])
        # Creating a MultiIndex with "Hour" as the top-level label for columns

        #     RES_forecast_df

        Setpoints = np.zeros((num_rows, column_lengths))
        Setpoints_df = pd.DataFrame(Setpoints).transpose()

        # Set the column labels starting from 1
        Setpoints_df.columns = [f' {i + 1}' for i in range(Setpoints_df.shape[1])]

        # Adjust index to start from 1
        Setpoints_df.index = Setpoints_df.index + 1

        # Creating a MultiIndex with "Hour" as the top-level label
        Setpoints_df.columns = pd.MultiIndex.from_product([['Hour'], Setpoints_df.columns])
        Setpoints_df.index = pd.MultiIndex.from_product([['Generator'], Setpoints_df.index])

        #     Setpoints_df

        # for i in range(len(Setpoints_df)):
        #     for j in Setpoints_df.columns:
        #         print(Setpoints_df.loc[i][j])

        for row_labels in RES + PV:
            for col in range(len(RES_forecast)):
                # if y_res_1_df.iloc[col][1] == 1:
                #     Setpoints_df.iloc[row_labels, col] = Grid_Capacity_df.iloc[col][1] * (
                #             RES_forecast_df.iloc[row_labels][col] / Sum_RES_forecast[col + 1]) * (
                #                                                  1 / data[row_labels]['max_power(MW)'])
                # else:

                if setpoint_df.iloc[row_labels, col] > 1:
                    Setpoints_df.iloc[row_labels, col] = round(setpoint_df.iloc[row_labels, col], 3)
                else:
                    Setpoints_df.iloc[row_labels, col] = round(setpoint_df.iloc[row_labels, col], 3)
                # if state_df.iloc[row_labels, col] == 0:
                #     Setpoints_df.iloc[row_labels, col - 1] = 0.0
                # else:
                #     pass

                #  (UN-)COMMENT THE NEXT CONDITIONAL STATEMENT (4 LINES) BELLOW FOR DIFFERENT CALCULATION OF SETPOINTS

                # if power_df.iloc[row_labels, col]/data[row_labels]['max_power(MW)'] < Setpoints_df.iloc[row_labels, col-1]:
                #     Setpoints_df.iloc[row_labels, col-1] = power_df.iloc[row_labels, col]/data[row_labels]['max_power(MW)']
                # else:
                #     pass

                # print('indexes: ', row_labels, ', ', col)
                # print('power: ', power_df.iloc[row_labels, col])
                # print('Max power: ', round(data[row_labels]['max_power(MW)'], 2))
                # print('Setpoints: ', round(Setpoints_df.iloc[row_labels, col-1], 2))
                # print('')
    else:
        Setpoints_df = setpoint_df




        #         print(y_res_1_df.iloc[row_labels][1])
        #         Setpoints_df.iloc[row_labels, col]=0
        #         print(Setpoints_df.iloc[row_labels, col])
    # print(Setpoints_df)
    # print(setpoint_df)
    #
    # print(power_df)
    # print(state_df)

    return round(Setpoints_df, 3)

def units_matrices(u_2_df, data):
    # import pandas as pd

    # Extract unit, row, and column indices
    """Build per-unit operating-state matrices from parsed u_2 variables."""
    u_2_df[['unit', 'row', 'col']] = u_2_df['Variable'].str.extract(r'u_2_(\d+)_(\d+)_(\d+)')

    # Convert extracted strings to integers
    u_2_df['unit'] = u_2_df['unit'].astype(int)
    u_2_df['row'] = u_2_df['row'].astype(int)
    u_2_df['col'] = u_2_df['col'].astype(int)

    # Dictionary to store matrices
    unit_matrices = {}

    # Iterate over each unit and create matrix
    for unit in range(1, len(data) + 1):
        subset = u_2_df[u_2_df['unit'] == unit]
        matrix = subset.pivot(index='row', columns='col', values='Value')
        unit_matrices[unit] = matrix

    return unit_matrices

def matrices_to_dfs(unit_matrices):
    """Convert operating-state matrices into DataFrames for legacy output assembly."""
    dfs = {}
    for key, matrix in unit_matrices.items():
        # Convert matrix to DataFrame
        df = pd.DataFrame(matrix)

        # Create multi-index for columns
        columns = pd.MultiIndex.from_product([['Thermal_states'], df.columns])
        df.columns = columns

        # Create multi-index for rows
        rows = pd.MultiIndex.from_product([['hours'], range(df.shape[0])])
        df.index = rows
        dfs[key] = df

    return dfs

def load_curtailment(input_data, s_load_plus_df, s_load_minus_df):
    """Compute load curtailment or augmentation from load slack variables."""
    LC = []
    LA = []
    if input_data["constraints"]["load_production_balance_constraint"] or input_data["constraints"]["load_production_Energy_balance_constraint"]:
        for i in range(0, len(s_load_minus_df)):
            LC.append(abs(round(s_load_minus_df['Value'][i], 3)))
            LA.append(abs(round(s_load_plus_df['Value'][i], 3)))  # Load Augmentation
        if any(LC):
            print('Load Curtailment is required !!!')
        else:
            print('----- No Load Cutrailment is required -----')
        if any(LA):
            print('Load Augmentation is required !!!')
        else:
            print('----- No Load Augmentation is required -----')
    else:
        LC = 'Nan'
    return LC

def APRR_violation(input_data, s_primary_APR_upwards_df, s_primary_APR_downwards_df, s_secondary_APR_upwards_df, s_secondary_APR_downwards_df, s_tertiary_APR_upwards_df, s_tertiary_APR_downwards_df):
    """Extract reserve requirement violation arrays from APR slack variables."""
    primary_upwards_APRV = []
    primary_downwards_APRV = []
    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        for i in range(0, len(s_primary_APR_upwards_df)):
            primary_upwards_APRV.append(abs(round(s_primary_APR_upwards_df['Value'][i], 5)))
            primary_downwards_APRV.append(abs(round(s_primary_APR_downwards_df['Value'][i], 5)))
        if any(primary_upwards_APRV):
            print('----- WARNING: upwards primary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No upwards primary APRR constraint violated-----')
        if any(primary_downwards_APRV):
            print('----- WARNING: downwards primary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No downwards primary APRR constraint violated-----')
    else:
        primary_upwards_APRV = 'Nan'
        primary_downwards_APRV = 'Nan'

    secondary_upwards_APRV = []
    secondary_downwards_APRV = []
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        for i in range(0, len(s_secondary_APR_upwards_df)):
            # print('len(df)', len(s_secondary_APR_upwards_df))
            secondary_upwards_APRV.append(abs(round(s_secondary_APR_upwards_df['Value'][i], 5)))
            secondary_downwards_APRV.append(abs(round(s_secondary_APR_downwards_df['Value'][i], 5)))
        if any(secondary_upwards_APRV):
            print('----- WARNING: upwards secondary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No upwards secondary APRR constraint violated-----')
        if any(secondary_downwards_APRV):
            print('----- WARNING: downwards secondary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No downwards secondary APRR constraint violated-----')
    else:
        secondary_upwards_APRV = 'Nan'
        secondary_downwards_APRV = 'Nan'

    tertiary_upwards_APRV = []
    tertiary_downwards_APRV = []
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        for i in range(0, len(s_tertiary_APR_upwards_df)):
            tertiary_upwards_APRV.append(abs(round(s_tertiary_APR_upwards_df['Value'][i], 5)))
            tertiary_downwards_APRV.append(abs(round(s_tertiary_APR_downwards_df['Value'][i], 5)))
        if any(tertiary_upwards_APRV):
            print('----- WARNING: upwards tertiary APRR constraint violated!!! -----')
        else:
            pass  # print('----- No upwards tertiary APRR constraint violated-----')
        if any(tertiary_downwards_APRV):
            print('----- WARNING: downwards tertiary APRR constraint violated!!! -----')
        else:
            pass  # print('----- No downwards tertiary APRR constraint violated-----')
    else:
        tertiary_upwards_APRV = 'Nan'
        tertiary_downwards_APRV = 'Nan'

    return primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV, tertiary_upwards_APRV, tertiary_downwards_APRV

def forbidden_zones_violations(input_data, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df):
    # List to store (i-1, t) pairs
    """Print or summarize forbidden zones violation slacks after solve."""
    fz_violated_constraints = []
    if input_data["constraints"]["forbidden_zones_constraint"]:
        # Iterate over each row of the dataframe
        for index, row in s_forbidden_zones_plus_df.iterrows():
            variable = row['Variable']
            value = row['Value']

            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_forbidden_zones_plus_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    fz_violated_constraints.append((int(i) - 1, int(t)))
                    # Print the warning message
                    # Iterate over each row of the dataframe
        for index, row in s_forbidden_zones_minus_df.iterrows():
            variable = row['Variable']
            value = row['Value']

            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_forbidden_zones_minus_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    fz_violated_constraints.append((int(i) - 1, int(t)))
                    # Print the warning message

        # Remove duplicates by converting the list to a set and back to a list
        fz_violated_constraints = list(set(fz_violated_constraints))

        # Sort the list first by unit (i) and then by dispatch period (t)
        fz_violated_constraints.sort(key=lambda x: (x[0], x[1]))

        # Print the warning message for each pair in the sorted list
        for i, t in fz_violated_constraints:
            print(f"----- WARNING: forbidden zones constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def ramp_up_down_violations(input_data, ramp_relax_df):
    # List to store (i-1, t) pairs
    """Print or summarize ramp up down violation slacks after solve."""
    ramp_up_down_violated_constraints = []
    if input_data["constraints"]["ramp_up_down_constraints"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(ramp_relax_df > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(f"----- WARNING: ramp up/ramp down constraint violated at unit {row}, dispatch period {ramp_relax_df.columns[col]} ----- ")
            print("")
    return None

def mustRun_violations(input_data, s_must_run_df):
    """Print or summarize mustRun violation slacks after solve."""
    if input_data["constraints"]["must_run_units_constraint"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_must_run_df > 0)
        # Printing row and column information for each non-zero value
        for row, col in zip(*non_zero_positions):
            print(f"----- WARNING: must run constraint violated at unit {row}, dispatch period {s_must_run_df.columns[col]} ----- ")
        print("")
    return None

def min_transition_time_between_states_constraints_a_violations(input_data, s_min_a_left_df, s_min_a_1_df):
    """Print or summarize min transition time between states constraints a violation slacks after solve."""
    min_a_left_violated_constraints = []
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        # Iterate over each row of the dataframe
        for index, row in s_min_a_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_a_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_a_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_a_left_violated_constraints = list(set(min_a_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_a_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_a_left_violated_constraints:
            print(
                f"----- WARNING: min-time-a-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
        min_a_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_a_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_a_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_a_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_a_1_violated_constraints = list(set(min_a_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_a_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_a_1_violated_constraints:
            print(
                f"----- WARNING: min-time-a-1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def min_transition_time_between_states_constraints_b_violations(input_data, s_min_b_left_df, s_min_b_1_df):
    """Print or summarize min transition time between states constraints b violation slacks after solve."""
    min_b_left_violated_constraints = []
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        # Iterate over each row of the dataframe
        for index, row in s_min_b_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_b_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_b_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_b_left_violated_constraints = list(set(min_b_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_b_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_b_left_violated_constraints:
            print(
                f"----- WARNING: min-time-b-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
        min_b_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_b_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_b_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_b_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_b_1_violated_constraints = list(set(min_b_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_b_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_b_1_violated_constraints:
            print(
                f"----- WARNING: min-time-b-1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def operating_state_min_time_constraints_violations(
    input_data,
    s_min_oper_state_time_a_left_df,
    s_min_oper_state_time_a_1_df,
    s_min_oper_state_time_b_left_df,
    s_min_oper_state_time_b_1_df,
):
    """Print or summarize operating state min time constraints violation slacks after solve."""
    def print_violations(frame, prefix, label):
        violated_constraints = []
        for index, row in frame.iterrows():
            variable = row['Variable']
            value = row['Value']
            if value != 0:
                match = re.search(rf'{prefix}_(\d+)_(\d+)_(\d+)', variable)
                if match:
                    i = int(match.group(1)) - 1
                    operating_state_id = int(match.group(2))
                    t = int(match.group(3))
                    violated_constraints.append((i, operating_state_id, t))

        violated_constraints = list(set(violated_constraints))
        violated_constraints.sort(key=lambda x: (x[0], x[1], x[2]))
        for i, operating_state_id, t in violated_constraints:
            print(
                f"----- WARNING: operating-state {label} constraint violated "
                f"for unit: {i}, operating state: {operating_state_id}, dispatch period: {t} ----- "
            )
        print(' ')

    if input_data["constraints"].get("operating_states_min_time_constraint_a", False):
        print_violations(
            s_min_oper_state_time_a_left_df,
            "s_min_oper_state_time_a_left",
            "min-time-a-left",
        )
        print_violations(
            s_min_oper_state_time_a_1_df,
            "s_min_oper_state_time_a_1",
            "min-time-a",
        )
    if (
        input_data["constraints"].get("operating_states_min_time_constraint", False)
        or input_data["constraints"].get("operating_states_min_time_constraint_b", False)
    ):
        print_violations(
            s_min_oper_state_time_b_left_df,
            "s_min_oper_state_time_b_left",
            "operating-state-min-time-left",
        )
        print_violations(
            s_min_oper_state_time_b_1_df,
            "s_min_oper_state_time_b_1",
            "operating-state-min-time",
        )
    return None


def operating_state_max_time_constraints_violations(
    input_data,
    s_max_oper_state_time_left_df,
    s_max_oper_state_time_1_df,
    s_max_oper_state_time_b_left_df,
    s_max_oper_state_time_b_1_df,
):
    """Print or summarize operating state max time constraints violation slacks after solve."""
    def print_violations(frame, prefix, label, include_from_state=False):
        violated_constraints = []
        for index, row in frame.iterrows():
            variable = row['Variable']
            value = row['Value']
            if value != 0:
                if include_from_state:
                    match = re.search(rf'{prefix}_(\d+)_(\d+)_(\d+)_(\d+)', variable)
                    if match:
                        i = int(match.group(1)) - 1
                        from_operating_state_id = int(match.group(2))
                        operating_state_id = int(match.group(3))
                        t = int(match.group(4))
                        violated_constraints.append((i, from_operating_state_id, operating_state_id, t))
                else:
                    match = re.search(rf'{prefix}_(\d+)_(\d+)_(\d+)', variable)
                    if match:
                        i = int(match.group(1)) - 1
                        operating_state_id = int(match.group(2))
                        t = int(match.group(3))
                        violated_constraints.append((i, None, operating_state_id, t))

        violated_constraints = list(set(violated_constraints))
        violated_constraints.sort(key=lambda x: (x[0], x[1] if x[1] is not None else -1, x[2], x[3]))
        for i, from_operating_state_id, operating_state_id, t in violated_constraints:
            from_text = (
                f", from operating state: {from_operating_state_id}"
                if from_operating_state_id is not None
                else ""
            )
            print(
                f"----- WARNING: operating-state {label} constraint violated "
                f"for unit: {i}{from_text}, operating state: {operating_state_id}, "
                f"dispatch period: {t} ----- "
            )
        print(' ')

    if input_data["constraints"].get("operating_states_max_time_constraint", False):
        print_violations(
            s_max_oper_state_time_left_df,
            "s_max_oper_state_time_left",
            "max-time-left",
        )
        print_violations(
            s_max_oper_state_time_1_df,
            "s_max_oper_state_time_1",
            "max-time",
        )
    if (
        input_data["constraints"].get("operating_states_max_transition_time_between_states_constraint_b", False)
        or input_data["constraints"].get("operating_states_max_time_constraint_b", False)
    ):
        print_violations(
            s_max_oper_state_time_b_left_df,
            "s_max_oper_state_time_b_left",
            "max-time-b-left",
            include_from_state=True,
        )
        print_violations(
            s_max_oper_state_time_b_1_df,
            "s_max_oper_state_time_b_1",
            "max-time-b",
            include_from_state=True,
        )
    return None


def min_state_transition_constraints_b_violations(input_data, s_min_state_b_left_df,  s_min_state_b_1_df):
    """Print or summarize min state transition constraints b violation slacks after solve."""
    if input_data["constraints"].get("state_min_time_constraint", input_data["constraints"].get("states_time_constraint", False)):
        min_state_b_left_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_state_b_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_state_b_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_state_b_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_state_b_left_violated_constraints = list(set(min_state_b_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_state_b_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_state_b_left_violated_constraints:
            print(
                f"----- WARNING: min-state-b-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')

        min_state_b_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_state_b_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_state_b_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_state_b_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_state_b_1_violated_constraints = list(set(min_state_b_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_state_b_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_state_b_1_violated_constraints:
            print(
                f"----- WARNING: min-state-b1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')

    return None

def res_pv_constraints_violations(input_data, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df):

    # if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
    #     Grid_Capacity_1_violated_constraints = []
    #     # Iterate over each row of the dataframe
    #     for index, row in s_Grid_Capacity_1_df.iterrows():
    #         variable = row['Variable']
    #         value = row['Value']
    #         # Check if the value is non-zero
    #         if round(value, 8) != 0:
    #             # Extract i and t using regex
    #             match = re.search(r's_Grid_Capacity_1_(\d+)', variable)
    #             if match:
    #                 t = match.group(1)  # Extract the first number as t
    #                 Grid_Capacity_1_violated_constraints.append(t)
    #     # Print the warning message
    #     # Iterate over each row of the dataframe
    #     # Remove duplicates by converting the list to a set and back to a list
    #     Grid_Capacity_1_violated_constraints = list(set(Grid_Capacity_1_violated_constraints))
    #     # Sort the list first by unit (i) and then by dispatch period (t)
    #     # Grid_Capacity_1_violated_constraints.sort(key=lambda x: (x[0]))
    #     # Print the warning message for each number in the sorted list
    """Print or summarize res pv constraints violation slacks after solve."""
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        Grid_Capacity_1_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_1_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_1_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_1_violated_constraints = sorted(Grid_Capacity_1_violated_constraints)
        for t in Grid_Capacity_1_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_1 constraint violated for dispatch period: {t} ----- ")
        print(' ')

        Grid_Capacity_2_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_2_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_2_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_2_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_2_violated_constraints = sorted(Grid_Capacity_2_violated_constraints)
        # Print the warning message for each number in the sorted list
        for t in Grid_Capacity_2_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_2 constraint violated for dispatch period: {t} ----- ")
        print(' ')

        Grid_Capacity_3_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_3_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_3_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_3_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_3_violated_constraints = sorted(Grid_Capacity_3_violated_constraints)
        # Print the warning message for each number in the sorted list
        for t in Grid_Capacity_3_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_3 constraint violated for dispatch period: {t} ----- ")
        print(' ')

    return None

def testing_mode_constraints_violations(input_data, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df):

    """Print or summarize testing mode constraints violation slacks after solve."""
    if input_data["constraints"]["testing_mode_constraints"]:
        # print(s_power_testing_mode_plus_df)
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_testing_mode_plus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: testing mode plus constraint violated at unit {row}, dispatch period {s_power_testing_mode_plus_df.columns[col]} ----- ")
            print("")

        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_testing_mode_minus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: testing mode minus constraint violated at unit {row}, dispatch period {s_power_testing_mode_minus_df.columns[col]} ----- ")
            print("")
    return None

def OOS_mode_constraints_violations(input_data, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df):

    """Print or summarize OOS mode constraints violation slacks after solve."""
    if input_data["constraints"]["OOS_mode_constraints"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_OOS_less_plus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: OOS mode 'less than' constraint violated at unit {row}, dispatch period {s_power_OOS_less_plus_df.columns[col]} ----- ")
            print("")

        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_OOS_more_minus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: OOS mode 'more than' constraint violated at unit {row}, dispatch period {s_power_OOS_more_minus_df.columns[col]} ----- ")
            print("")
    return None

def RES_PV_power_constraints_violations(s_power_plus_df, s_power_minus_df):
    """Print or summarize RES PV power constraints violation slacks after solve."""
    non_zero_positions = np.where(s_power_plus_df.round(6) > 0)
    # Printing row and column information for each non-zero value
    if non_zero_positions:
        for row, col in zip(*non_zero_positions):
            print(
                 f"----- WARNING: RES-PV power plus constraint violated at unit {s_power_plus_df.index[row] - 1}, dispatch period {s_power_plus_df.columns[col]} ----- ")
        print("")

    # Finding the positions of non-zero values
    non_zero_positions = np.where(s_power_minus_df.round(6) > 0)
    # Printing row and column information for each non-zero value
    if non_zero_positions:
        for row, col in zip(*non_zero_positions):
            print(
                 f"----- WARNING: RES-PV power minus constraint violated at unit {s_power_minus_df.index[row] - 1}, dispatch period {s_power_minus_df.columns[col]} ----- ")
        print("")
    return None

def availability_violations(s_avail_values_df):
    # Convert all values to numeric, coercing errors to NaN
    """Print or summarize availability violation slacks after solve."""
    s_avail_values_df = s_avail_values_df.apply(pd.to_numeric, errors='coerce')
    non_zero_positions = np.where(s_avail_values_df.round(6) > 0)

    # Check if there are any non-zero elements
    if len(non_zero_positions[0]) > 0:
        for row, col in zip(*non_zero_positions):
            print(
                f"----- WARNING: Availability constraint violated at unit {s_avail_values_df.index[row] - 1}, dispatch period {s_avail_values_df.columns[col]} -----"
            )
        print("")  # Print an empty line for better formatting

    return None

def output_json(data, input_data, json_template, power_df, Setpoints_df, unit_thermal_states_dfs, state_df, LC,
                Solution_Status,
                primary_ActPR_plus_df, primary_ActPR_minus_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df,
                secondary_ActPR_plus_df, secondary_ActPR_minus_df, CONV, RES, PV, shutdown_df, startup_df,
                primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV,
                tertiary_upwards_APRV, tertiary_downwards_APRV):
    """Assemble the legacy optimization output JSON payload."""
    data_output = {}

    data_output["Generating_Units"] = json_template

    data_output["primary_upwards_APRV"] = primary_upwards_APRV
    data_output["primary_downwards_APRV"] = primary_downwards_APRV
    data_output["secondary_upwards_APRV"] = secondary_upwards_APRV
    data_output["secondary_downwards_APRV"] = secondary_downwards_APRV
    data_output["tertiary_upwards_APRV"] = tertiary_upwards_APRV
    data_output["tertiary_downwards_APRV"] = tertiary_downwards_APRV

    data_output["Load_Cutrailment"] = LC

    data_output["Solution_Status"] = Solution_Status

    Units_Setpoints = [list(row) for row in Setpoints_df.values]

    power_df = power_df.drop(0, axis=1)

    Units_Power = [list(row) for row in np.around(power_df.values, 3)]
    #     Unit_thermal_states = []
    state_df = state_df.drop(0, axis=1)
    # Units_states = [list(row) for row in state_df.values]
    Units_states = [[round(value, 3) for value in row] for row in state_df.values]

    # Units_Shutdown = [list(row) for row in shutdown_df.values]
    Units_Shutdown = [[round(value, 3) for value in row] for row in shutdown_df.values]

    # Units_Startup = [list(row) for row in startup_df.values]
    Units_Startup = [[round(value, 3) for value in row] for row in startup_df.values]


    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        # primary_ActPR_plus = [group['Value'].tolist() for _, group in primary_ActPR_plus_df.groupby('Generator')]
        primary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in primary_ActPR_plus_df.groupby('Generator')]


        # primary_ActPR_minus = [group['Value'].tolist() for _, group in primary_ActPR_minus_df.groupby('Generator')]
        primary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in primary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        # secondary_ActPR_plus = [group['Value'].tolist() for _, group in secondary_ActPR_plus_df.groupby('Generator')]
        secondary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in secondary_ActPR_plus_df.groupby('Generator')]

        # secondary_ActPR_minus = [group['Value'].tolist() for _, group in secondary_ActPR_minus_df.groupby('Generator')]
        secondary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in secondary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        # tertiary_ActPR_plus = [group['Value'].tolist() for _, group in tertiary_ActPR_plus_df.groupby('Generator')]
        tertiary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in tertiary_ActPR_plus_df.groupby('Generator')]

        # tertiary_ActPR_minus = [group['Value'].tolist() for _, group in tertiary_ActPR_minus_df.groupby('Generator')]
        tertiary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in tertiary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    for i in range(len(data)):
        data_output["Generating_Units"][i]["gen_id"] = data[i]['gen_id']
        data_output["Generating_Units"][i]["comments"] = data[i]['comments']
        data_output["Generating_Units"][i]["Power"] = Units_Power[i]
        if input_data["constraints"]["primary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][0] = primary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][1] = primary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][1] = 'Nan'
        if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][0] = secondary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][1] = secondary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][1] = 'Nan'
        if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][0] = tertiary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][1] = tertiary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][1] = 'Nan'

        data_output["Generating_Units"][i]["State"] = Units_states[i]
        data_output["Generating_Units"][i]["Shutdown"] = Units_Shutdown[i]
        data_output["Generating_Units"][i]["Startup"] = Units_Startup[i]
        unit_thermal_states_dfs[i + 1] = unit_thermal_states_dfs[i + 1].iloc[1:]
        # Unit_thermal_states_temp = [list(row) for row in unit_thermal_states_dfs[i + 1].values]
        Unit_thermal_states_temp = [[round(value, 3) for value in row] for row in unit_thermal_states_dfs[i + 1].values]
        data_output["Generating_Units"][i]["Operating-states"] = Unit_thermal_states_temp

        if i in RES + PV:
            if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
                data_output["Generating_Units"][i]['Setpoints'] = Units_Setpoints[i]
            else:
                data_output["Generating_Units"][i]['Setpoints'] = 'Nan'

    return data_output

def create_output_json_template(data, CONV, RES, PV, Partially_Controllable):
    """Create the base output structure for each filtered generating unit."""
    json_template = []
    for i in range(len(data)):
        if i in CONV:
            json_template.append({'gen_id': 0,
                                  'comments': 'Thermoelectric Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'Operating-states': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0]})
        elif i in PV:
            json_template.append({'gen_id': 0,
                                  'comments': 'PV (Aggregated) Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'State': [0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0],
                                  'Setpoints': [0.0, 0.0, 0.0, 0.0]})
        elif i in RES:
            json_template.append({'gen_id': 0,
                                  'comments': 'Wind Turbine Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'State': 0,
                                  'Power': [0.0, 0.0, 0.0, 0.0],
                                  'Setpoints': [0.0, 0.0, 0.0, 0.0]})
        elif i in Partially_Controllable:
            json_template.append({'gen_id': 0,
                                  'comments': 'Partially Controllable Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'Operating-states': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0]})
    return json_template


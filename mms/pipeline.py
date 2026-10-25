"""End-to-end optimization pipeline from prepared input to output JSON payload."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original optimization workflow.

import copy
from time import perf_counter

from mms.model.preprocessing import filter_generating_units, time_granularity, unit_categories
from mms.model.time_resolution import prepare_operating_state_time_resolution
from mms.model.problem import define_problem_and_solve_problem
from mms.postsolve import (
    APRR_violation,
    OOS_mode_constraints_violations,
    RES_PV_power_constraints_violations,
    availability_violations,
    create_output_json_template,
    forbidden_zones_violations,
    load_curtailment,
    matrices_to_dfs,
    min_state_transition_constraints_b_violations,
    min_transition_time_between_states_constraints_a_violations,
    min_transition_time_between_states_constraints_b_violations,
    mustRun_violations,
    operating_state_max_time_constraints_violations,
    operating_state_min_time_constraints_violations,
    output_json,
    ramp_up_down_violations,
    res_pv_constraints_violations,
    setpoint_calculation,
    solution_processing,
    testing_mode_constraints_violations,
    units_matrices,
)
from mms.slacks import build_slack_penalty_report

def parse_and_execute_optimization(input_data):
    """Build, solve, and post-process the optimization model for prepared input data."""
    pipeline_start = perf_counter()
    stage_timings = []

    def record_stage(stage, started_at):
        stage_timings.append(
            {
                "stage": stage,
                "seconds": round(perf_counter() - started_at, 6),
            }
        )

    preprocessing_start = perf_counter()
    # Read the original dispatch-period length in minutes before any timing values are converted.
    time_gran = input_data["Time_granularity"]
    # First decide whether explicitly transient sub-period operating states should be embedded or kept.
    input_data = prepare_operating_state_time_resolution(input_data)
    # Then convert all remaining minute-based timing fields into dispatch-period counts.
    input_data = time_granularity(input_data, time_gran)
    # Keep an audit snapshot of the exact preprocessed input used to build the MIP.
    preprocessed_mip_input = copy.deepcopy(input_data)
    # Read the generating-unit list after time-resolution preprocessing and timing conversion.
    data = input_data.get('Generating_Units', [])
    # Remove units that have no availability in the modeled horizon.
    data = filter_generating_units(data)
    # print(data)
    RES_forecast = []
    for i, gen in enumerate(data):
        #     print(gen['Production_Forecast'])
        RES_forecast.append(gen.get('Production_Forecast', []))

    RES_forecast = [list(row) for row in zip(*RES_forecast)]

    Load_forecast = input_data.get("Load_forecast", [])

    intervals = list(range(0, len(Load_forecast)))  # the 1st hour (index 0) is the 24th hour of the previous day#
    # print(intervals[0:-1])
    gen_ids = []
    for i in range(len(data)):
        gen_ids.append(data[i]['gen_id'])
    # Create a list ("RES") containing the index (corresponding to other lists - ie. decision variable lists) that corresponds to the RES units

    # CONV = []
    # RES = []
    # PV = []
    # Partially_Controllable = []

    # on_AGC = []
    # units_numbers = range(len(data))
    # for i, _ in enumerate(data):
    #     #     print(i['comments'])
    #     if data[i]['comments'][:5] == 'Therm':
    #         CONV.append(i)
    #     elif data[i]['comments'][:2] == 'PV':
    #         PV.append(i)
    #     elif "Partially Controllable" in data[i]['comments']:
    #         Partially_Controllable.append(i)
    #     else:
    #         RES.append(i)
    UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, Partially_Controllable = unit_categories(input_data, data)
    # print(PV)
        # these units can provide secondary reserves - regulation
        # for i in CONV:
        # agc_configuration = data[i].get("agc_configuration", {})
        # if agc_configuration.get("isConnected", 0) == 1:
        #     on_AGC.append(i)
        #     for operating_states in data[i]["operating-states"]:
        #         if operating_states["isOperational"]:
        #             operating_states["max-power"] = agc_configuration.get("maxLoad", operating_states["max-power"])
        #             operating_states["min-power"] = agc_configuration.get("minLoad", operating_states["min-power"])
        #         else:
        #             pass
        # else:
        #     pass

    optimization_parameters = input_data.get('optimization_parameters', {})
    warmstart_parameters = optimization_parameters.get('warmStart_parameters', {})
    warmStart = warmstart_parameters.get('warmStart', False)
    keepFiles = warmstart_parameters.get("keepFiles", False)
    logPath = warmstart_parameters.get("logPath", None)
    timeLimit = optimization_parameters.get("early_stopping", {}).get("time_limit", None)
    solver_name = optimization_parameters.get("solver", "highs")
    gapRel = optimization_parameters.get("gapRel", optimization_parameters.get("mip_gap", None))
    gapAbs = optimization_parameters.get("gapAbs", None)
    threads = optimization_parameters.get("threads", None)
    require_optimal = optimization_parameters.get("require_optimal", True)
    solver_options = optimization_parameters.get("highs_options", {})

    Sum_RES_forecast = [sum(row[i] for i in RES) for row in RES_forecast]
    Sum_RES_forecast.insert(0, 0)  # per 15' RES forecasted production - NOT PV INCLUDED -- insert O value (or any value) in indice 0

    # baseline_power_list = []
    # for i, gen in enumerate(input_data["Generating_Units"]):
    #     if input_data['constraints']['rdas_deviations_calculation_constraints']:
    #         baseline_power_list.append(gen['RDAS_power_results'])
    #
    # baseline_state_list = []
    # for i, gen in enumerate(input_data["Generating_Units"]):
    #     if input_data['constraints']['rdas_deviations_calculation_constraints']:
    #         baseline_state_list.append(gen['RDAS_state_results'])
    #
    # baseline_state_df = pd.DataFrame(baseline_state_list)
    # baseline_power_df = pd.DataFrame(baseline_power_list)

    x_load = input_data['Cost_parameters']['x_load']
    record_stage("preprocessing", preprocessing_start)

    # create .mps file through pulp
    solve_start = perf_counter()
    solution, RES, Solution_Status, solve_metadata = define_problem_and_solve_problem(data=data,
        input_data=input_data, UNITS=UNITS,
        RES=RES, PV=PV, CONV=CONV, RES_SP=RES_SP, RES_no_SP=RES_no_SP, PV_SP=PV_SP, PV_no_SP=PV_no_SP, Partially_Controllable=Partially_Controllable,
        RES_forecast=RES_forecast,
        Load_forecast=Load_forecast,
        intervals=intervals,
        x_load=x_load,
        on_AGC=on_AGC, warmStart=warmStart, keepFiles=keepFiles, logPath=logPath,
        timeLimit=timeLimit, solver_name=solver_name, gapRel=gapRel, gapAbs=gapAbs,
        threads=threads, solver_options=solver_options, require_optimal=require_optimal)
    record_stage("model_build_mps_and_solve", solve_start)


#----------------------------------------- .mps file created-------------------------------------------------
    # solution_dict, Solution_Status = define_and_solve_problem(binary_vars, integer_vars, continuous_vars)

    postsolve_start = perf_counter()
    (power_df, state_df, startup_df, shutdown_df, ramp_relax_df, s_load_plus_df, s_load_minus_df,
    z_1_df, u_1_df, primary_ActPR_plus_df, primary_ActPR_minus_df, s_primary_APR_upwards_df,
    s_primary_APR_downwards_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, s_tertiary_APR_upwards_df,
    s_tertiary_APR_downwards_df, secondary_ActPR_plus_df, secondary_ActPR_minus_df, s_secondary_APR_upwards_df,
    s_secondary_APR_downwards_df, RES_sum_df,
    primary_APRR_df, binary_primary_df, tertiary_APRR_df, binary_tertiary_df, secondary_APRR_df, binary_secondary_df, u_2_df, setpoint_df, Min_grid_capacity_1_df, Min_grid_capacity_2_df, Min_Power_Calc_df, Grid_Capacity1_df,
    Grid_Capacity2_df, Grid_Capacity3_df, g1_df, g2_df, g3_df, g4_df,
    m_df, y_zone_df, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df, s_must_run_df, s_min_a_left_df,
    s_min_a_1_df, s_min_b_left_df, s_min_b_1_df,
    s_max_oper_state_time_left_df, s_max_oper_state_time_1_df,
    s_max_oper_state_time_b_left_df, s_max_oper_state_time_b_1_df,
    s_min_oper_state_time_a_left_df, s_min_oper_state_time_a_1_df,
    s_min_oper_state_time_b_left_df, s_min_oper_state_time_b_1_df,
    s_min_state_b_left_df, s_min_state_b_1_df, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df,
    s_power_testing_mode_plus_df, s_power_testing_mode_minus_df,
    s_power_plus_df, s_power_minus_df, N_1_df, N_2_df, P_RES_df, P_PV_df, s_avail_values_df, s_N_1_df, s_N_2_df, P_sp_df, g5_df, delta_df,
    s_power_OOS_less_plus_df, s_power_OOS_more_minus_df) = solution_processing(solution, input_data)
    Setpoints_df = setpoint_calculation(input_data, RES, PV, RES_forecast, Sum_RES_forecast, data, power_df, setpoint_df, state_df)
    unit_matrices = units_matrices(u_2_df, data)
    unit_thermal_states_dfs = matrices_to_dfs(unit_matrices)
    LC = load_curtailment(input_data, s_load_plus_df, s_load_minus_df)
    primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV, tertiary_upwards_APRV, tertiary_downwards_APRV = APRR_violation(
    input_data, s_primary_APR_upwards_df, s_primary_APR_downwards_df, s_secondary_APR_upwards_df,
    s_secondary_APR_downwards_df, s_tertiary_APR_upwards_df, s_tertiary_APR_downwards_df)
    slack_penalty_report = build_slack_penalty_report(
        input_data,
        {
            "ramp_relax": ramp_relax_df,
            "s_load_plus": s_load_plus_df,
            "s_load_minus": s_load_minus_df,
            "s_primary_APR_upwards": s_primary_APR_upwards_df,
            "s_primary_APR_downwards": s_primary_APR_downwards_df,
            "s_secondary_APR_upwards": s_secondary_APR_upwards_df,
            "s_secondary_APR_downwards": s_secondary_APR_downwards_df,
            "s_tertiary_APR_upwards": s_tertiary_APR_upwards_df,
            "s_tertiary_APR_downwards": s_tertiary_APR_downwards_df,
            "s_Grid_Capacity_1": s_Grid_Capacity_1_df,
            "s_Grid_Capacity_2": s_Grid_Capacity_2_df,
            "s_Grid_Capacity_3": s_Grid_Capacity_3_df,
            "s_forbidden_zones_plus": s_forbidden_zones_plus_df,
            "s_forbidden_zones_minus": s_forbidden_zones_minus_df,
            "s_must_run": s_must_run_df,
            "s_min_a_left": s_min_a_left_df,
            "s_min_a_1": s_min_a_1_df,
            "s_min_b_left": s_min_b_left_df,
            "s_min_b_1": s_min_b_1_df,
            "s_max_oper_state_time_left": s_max_oper_state_time_left_df,
            "s_max_oper_state_time_1": s_max_oper_state_time_1_df,
            "s_max_oper_state_time_b_left": s_max_oper_state_time_b_left_df,
            "s_max_oper_state_time_b_1": s_max_oper_state_time_b_1_df,
            "s_min_oper_state_time_a_left": s_min_oper_state_time_a_left_df,
            "s_min_oper_state_time_a_1": s_min_oper_state_time_a_1_df,
            "s_min_oper_state_time_b_left": s_min_oper_state_time_b_left_df,
            "s_min_oper_state_time_b_1": s_min_oper_state_time_b_1_df,
            "s_min_state_b_left": s_min_state_b_left_df,
            "s_min_state_b_1": s_min_state_b_1_df,
            "s_power_testing_mode_plus": s_power_testing_mode_plus_df,
            "s_power_testing_mode_minus": s_power_testing_mode_minus_df,
            "s_power_plus": s_power_plus_df,
            "s_power_minus": s_power_minus_df,
            "s_power_OOS_less_plus": s_power_OOS_less_plus_df,
            "s_power_OOS_more_minus": s_power_OOS_more_minus_df,
        },
    )
    forbidden_zones_violations(input_data, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df)
    ramp_up_down_violations(input_data, ramp_relax_df)
    mustRun_violations(input_data, s_must_run_df)
    min_transition_time_between_states_constraints_a_violations(input_data, s_min_a_left_df, s_min_a_1_df)
    min_transition_time_between_states_constraints_b_violations(input_data, s_min_b_left_df, s_min_b_1_df)
    operating_state_max_time_constraints_violations(
        input_data,
        s_max_oper_state_time_left_df,
        s_max_oper_state_time_1_df,
        s_max_oper_state_time_b_left_df,
        s_max_oper_state_time_b_1_df,
    )
    operating_state_min_time_constraints_violations(
        input_data,
        s_min_oper_state_time_a_left_df,
        s_min_oper_state_time_a_1_df,
        s_min_oper_state_time_b_left_df,
        s_min_oper_state_time_b_1_df,
    )
    min_state_transition_constraints_b_violations(input_data, s_min_state_b_left_df, s_min_state_b_1_df)
    res_pv_constraints_violations(input_data, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df)
    testing_mode_constraints_violations(input_data, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df)

    OOS_mode_constraints_violations(input_data, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df)

    RES_PV_power_constraints_violations(s_power_plus_df, s_power_minus_df)
    availability_violations(s_avail_values_df)
    json_template = create_output_json_template(data, CONV, RES, PV, Partially_Controllable)
    data_output_json = output_json(data, input_data, json_template, power_df, Setpoints_df, unit_thermal_states_dfs,
                                   state_df, LC,
                                   Solution_Status, primary_ActPR_plus_df, primary_ActPR_minus_df,
                                   tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, secondary_ActPR_plus_df,
                                   secondary_ActPR_minus_df, CONV, RES, PV, shutdown_df, startup_df,
                                   primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV,
                                   secondary_downwards_APRV,
                                   tertiary_upwards_APRV, tertiary_downwards_APRV)
    data_output_json["Solve_Metadata"] = solve_metadata
    data_output_json["Slack_Penalty_Report"] = slack_penalty_report
    data_output_json["Time_Resolution_Report"] = input_data.get("Time_Resolution_Report", {})
    data_output_json["_Preprocessed_MIP_Input"] = preprocessed_mip_input

    record_stage("postsolve_output_assembly", postsolve_start)
    data_output_json["Performance_Profile"] = {
        "pipeline_seconds": round(perf_counter() - pipeline_start, 6),
        "pipeline_stages": stage_timings,
    }


    return data_output_json


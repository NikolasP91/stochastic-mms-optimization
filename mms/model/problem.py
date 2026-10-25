"""Top-level PuLP problem assembly, solver invocation, and solve metadata collection."""

# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import time

import pulp as pl

from mip_utils import ConstraintBuildTracker, estimate_big_m, name_auto_constraints
from mms.model.core import (
    create_ensure_variables_correctness_constraint,
    create_global_variables,
    create_largest_online_capacity_bounds,
    create_production_load_balance_constraint,
    create_res_sum_calculation_constraint,
    min_max_handling,
    produce_min_max_t,
)
from mms.model.operating_states import (
    create_allowed_operating_states_transition_constraints,
    create_operating_state_max_transition_time_between_states_constraints_b,
    create_min_transition_time_between_states_constraints_a,
    create_min_transition_time_between_states_constraints_b,
    create_operating_states_power_levels_constraints,
    create_state_min_time_constraints,
)
from mms.model.res_dispatch import create_res_pv_2_dispatch_variables_constraints
from mms.model.reserves import (
    create_primary_active_power_reserves_constraint,
    create_secondary_active_power_reserves_constraint,
    create_tertiary_active_power_reserves_constraint,
)
from mms.model.thermal_constraints import (
    create_OOS_mode_constraints,
    create_availability_program,
    create_forbidden_zones_constraint,
    create_mustRun_constraints,
    create_ramp_up_down_constraints,
    create_testing_mode_constraints,
    create_variable_cost_curve_calculation_constraints,
)

def define_problem_and_solve_problem(data, input_data, UNITS, RES, PV, CONV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_forecast, Load_forecast, intervals,
                             x_load, on_AGC, warmStart=False, keepFiles=False, logPath=None, timeLimit=None,
                             solver_name="highs", gapRel=None, gapAbs=None, threads=None,
                             solver_options=None, require_optimal=True, build_only=False):

    """Assemble the PuLP MIP, solve it, and return variables plus solve metadata."""
    big_m_setting = input_data.get("optimization_parameters", {}).get("big_m", "auto")
    if big_m_setting == "auto":
        M = estimate_big_m(input_data, data, intervals)
    else:
        M = float(big_m_setting)
    print(f"Using big-M value: {M:g}")
    start_time = time.time()
    # Define the problem
    prob = pl.LpProblem(name="Rdas_DispatchScheduling", sense=pl.LpMinimize)

    IntervalCount = len(intervals)

    # Define constraints
    build_tracker = ConstraintBuildTracker(prob)
    objective_terms = 0
    with build_tracker.section("initial_conditions"):
        prob, power, state, RES_sum, startup, shutdown = create_global_variables(prob, data, intervals)
    with build_tracker.section("res_sum_definition"):
        prob = create_res_sum_calculation_constraint(prob, power, intervals, RES_sum, RES, PV, Partially_Controllable)
    with build_tracker.section("commitment_transition_logic"):
        prob = create_ensure_variables_correctness_constraint(prob, data, intervals, state, startup, shutdown)
    with build_tracker.section("variable_cost_curve"):
        prob, objective_terms, u_1 = create_variable_cost_curve_calculation_constraints(input_data, prob, objective_terms, power,
                                                                                             data, intervals, M, state, CONV)
    # prob, objective_terms, z_3 = create_thermal_state_startup_cost_variable_constraint(prob, objective_terms, data, intervals, u_2, startup) # u_2 --> u_2_dict & z_3 --> z_3_dict done

    #
    # for i, _ in enumerate(data):
    #     data[i]["max_power(MW)"] = 24 * [data[i]["max_power(MW)"]]
    #     data[i]["min_power(MW)"] = 24 * [data[i]["min_power(MW)"]]
    #     for operating_states in data[i]["operating-states"]:
    #         operating_states["max-power"] = 24 * [operating_states["max-power"]]
    #         operating_states["min-power"] = 24 * [operating_states["min-power"]]
    # print(data)

    data = produce_min_max_t(data, intervals)

    with build_tracker.section("unit_max_power_limits"):
        for gen in data:
            gen_id = gen['gen_id']
            for t in intervals[1:]:
                prob += power[gen_id][t] <= gen['max_power(MW)'][t-1]


    with build_tracker.section("min_max_handling"):
        prob, data, on_AGC = min_max_handling(prob, data, input_data, CONV, Partially_Controllable, on_AGC, intervals, u_1, state, power)
    # if input_data["constraints"]["min_max_constraint"]:
    #     # only for dispatchable units check 5.2.4.4 Constraints paragraph in "Διακήρυξη" pdf
    #     for gen in data:
    #         gen_id = gen['gen_id']
    #         if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
    #             for t in intervals[1:]:
    #                 # if constraint enabled -- we cannot go to the zone above technical maximum
    #                 prob += u_1[gen_id][t][-1] == 0
    #         else:
    #             pass
    # else:
    #     for gen in data:
    #         gen_id = gen['gen_id']
    #         if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
    #             for operating_state in data[gen_id]["operating-states"]:
    #                 if operating_state["isOperational"]:
    #                     for t in intervals[1:]:
    #                         operating_state["max-power"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
    #                         operating_state["min-power"][t-1] = 0
    #                 else:
    #                     for t in intervals[1:]:
    #                         operating_state["max-power"][t-1] = operating_state["min-power"][t-1] = 0
    #             for t in intervals[1:]:
    #                 data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
    #                 data[gen_id]["min_power(MW)"][t-1] = 0
    #         else:
    #             pass
    #
    # for i, _ in enumerate(data):
    #     # these units can provide secondary reserves - regulation
    #     # for i in CONV:
    #     agc_configuration = data[i].get("agc_configuration", {})
    #     if agc_configuration.get("isConnected", 0) == 1:
    #         on_AGC.append(i)
    #         for operating_states in data[i]["operating-states"]:
    #             if operating_states["isOperational"]:
    #                 for t in intervals[1:]:
    #                     operating_states["max-power"][t-1] = agc_configuration.get("maxLoad", operating_states["max-power"][t-1])
    #                     operating_states["min-power"][t-1] = agc_configuration.get("minLoad", operating_states["min-power"][t-1])
    #             else:
    #                 pass
    #     else:
    #         pass
    #
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
    #
    #
    #                     # operating_states["max-power"][t-1] = min(operating_states["max-power"][t-1], data[i]["production_program"][t-1])
    #                     # data[gen_id]["max_power(MW)"][t - 1] = operating_states["max-power"][t - 1]
    #
    #                     # if operating_states["max-power"][t-1] < operating_states["min-power"][t-1]:
    #                     #     for operating_states in data[i]["operating-states"]:
    #                     #         operating_states["max-power"][t-1] = operating_states["min-power"][t-1] = data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["min_power(MW)"][t-1] = 0
    #                     # else:
    #
    #                 else:
    #                     pass
    # print(data[5])










# constraints for PV & RES apart from setpoints' constraints
    with build_tracker.section("res_pv_forecast_tracking"):
        s_power_plus = [[pl.LpVariable(name=f's_power_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
        s_power_minus = [[pl.LpVariable(name=f's_power_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
        for t in intervals[1:]:
            for i in RES_no_SP + PV_no_SP:
                prob += 100 * (power[i][t] - s_power_minus[i][t] + s_power_plus[i][t]) == 100 * RES_forecast[t - 1][i]
            for i in RES_SP + PV_SP:
                prob += power[i][t] - s_power_minus[i][t] <= RES_forecast[t - 1][i]
            for i in RES+PV:
                objective_terms += s_power_plus[i][t] * input_data["Cost_parameters"]["x_RES_PV_power_plus"] + s_power_minus[i][t] * input_data["Cost_parameters"]["x_RES_PV_power_minus"]
    #

        # objective_terms += s_min_a_left[gen_id][t] * 100000
    # print('data:', data)
    with build_tracker.section("operating_state_power_levels"):
        prob, objective_terms, u_2_dict, shutdown_states = create_operating_states_power_levels_constraints(input_data, prob, objective_terms, power, state, data, intervals, CONV, RES, PV, M)  # u_2 --> u_2_dict done
    # if input_data["constraints"]["availability_constraint"]:
    with build_tracker.section("availability_program"):
        prob, objective_terms = create_availability_program(prob, objective_terms, input_data, data, power, intervals, CONV)
    print('')
    # print(data)
    print('')
    #  prob = create_min_max_constraints(prob, power, data, intervals, state, u_2) # u_2 --> u_2_dict
    # if input_data["constraints"]["gen_declaration_constraint"]:
    #     prob = create_generation_declaration(prob, data, power, intervals)
    if input_data["constraints"]["ramp_up_down_constraints"]:
        with build_tracker.section("ramp_up_down"):
            prob, ramp_relax, objective_terms = create_ramp_up_down_constraints(input_data, prob, power, data, intervals, objective_terms)
    if input_data["constraints"]["allowed_thermal_states_transition_constraints"]:
        with build_tracker.section("allowed_operating_state_transitions"):
            prob, objective_terms = create_allowed_operating_states_transition_constraints(prob, objective_terms, data, intervals, u_2_dict, M) # u_2 --> u_2_dict done
    # Final operating-state timing set:
    # 1) transition minimum A: source-side minimum time before leaving A;
    # 2) transition minimum B: destination-side minimum stay in B;
    # 3) transition maximum B: destination-side maximum stay in B.
    # Older generic operating-state dwell-time helpers were intentionally
    # removed so the active model has one source of truth for each accepted
    # operating-state timing constraint.
    if (
        input_data["constraints"].get("operating_states_max_transition_time_between_states_constraint_b", False)
        or input_data["constraints"].get("operating_states_max_time_constraint_b", False)
    ):
        with build_tracker.section("max_transition_time_between_states_b"):
            prob, objective_terms = create_operating_state_max_transition_time_between_states_constraints_b(
                prob, objective_terms, input_data, data, u_2_dict, IntervalCount, intervals
            )  # u_2 --> u_2_dict
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        with build_tracker.section("min_transition_time_between_states_a"):
            prob, objective_terms = create_min_transition_time_between_states_constraints_a(prob, objective_terms, input_data, data, u_2_dict, intervals)
    # Transition-specific B-side minimum timing. This uses min-transition-time_b
    # fields on operating-state transition arcs and constrains the destination
    # state after a specific A -> B transition.
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        with build_tracker.section("min_transition_time_between_states_b"):
            prob,  objective_terms = create_min_transition_time_between_states_constraints_b(prob,  objective_terms, input_data, data, u_2_dict, intervals)
    # if input_data["constraints"]["rdas_deviations_calculation_constraints"] and power_baseline is not None and state_baseline is not None:
    #     prob, objective_terms, deviation_1, deviation_2, y_4, y_5 = create_power_state_baseline_deviations_calculation_constraints(input_data, prob, objective_terms, data, intervals, power,
    #         state, power_baseline, state_baseline, CONV, M)
    # if input_data["constraints"]["power_deviation_penalty"]:
    #     prob, objective_terms, deviation_3, y_6 = create_power_deviation_penalty(input_data, prob, objective_terms, power, intervals, CONV, M, data)
    if input_data["constraints"]["load_production_balance_constraint"]:
        with build_tracker.section("load_balance"):
            prob, objective_terms, s_load_minus, s_load_plus = create_production_load_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV, x_load)
    # if input_data["constraints"]["load_production_Energy_balance_constraint"]:
    #     prob, objective_terms, s_load_minus, s_load_plus = create_production_load_Energy_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV, x_load)
    if input_data["constraints"]["primary_active_power_reserves_constraint"] or input_data["constraints"]["secondary_active_power_reserves_constraint"] or input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        with build_tracker.section("largest_online_units"):
            largest_online_capacity, largest_two_online_capacity = create_largest_online_capacity_bounds(prob, CONV, state, data, intervals)
    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        with build_tracker.section("primary_active_power_reserves"):
            prob, objective_terms, primary_ActPR_plus, primary_ActPR_minus, primary_APRR, s_primary_APR_upwards, s_primary_APR_downwards = create_primary_active_power_reserves_constraint(
                prob, input_data, objective_terms, power, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, largest_online_capacity, largest_two_online_capacity)
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        with build_tracker.section("secondary_active_power_reserves"):
            prob, objective_terms, y_plus, y_minus, secondary_ActPR_plus, secondary_ActPR_minus, secondary_APRR, s_secondary_APR_upwards, s_secondary_APR_downwards = create_secondary_active_power_reserves_constraint(
                prob, input_data, objective_terms, power, primary_ActPR_plus, primary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, largest_online_capacity, largest_two_online_capacity)
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        with build_tracker.section("tertiary_active_power_reserves"):
            prob, objective_terms, tertiary_ActPR_plus, tertiary_ActPR_minus, tertiary_APRR, s_tertiary_APR_upwards, s_tertiary_APR_downwards = create_tertiary_active_power_reserves_constraint(
                prob, input_data, objective_terms, y_plus, y_minus, power, primary_ActPR_plus, primary_ActPR_minus, secondary_ActPR_plus, secondary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, largest_online_capacity, largest_two_online_capacity)
    if input_data["constraints"]["forbidden_zones_constraint"]:
        with build_tracker.section("forbidden_zones"):
            prob, objective_terms, y_zone, s_forbidden_zones_plus, s_forbidden_zones_minus = create_forbidden_zones_constraint(prob, objective_terms, input_data, power, data, intervals, CONV, M)
    if input_data["constraints"]["must_run_units_constraint"]:
        with build_tracker.section("must_run_units"):
            prob, objective_terms, s_must_run = create_mustRun_constraints(prob, objective_terms, input_data, data, intervals, state)
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        with build_tracker.section("res_pv_dispatch_variables"):
            prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_2 = create_res_pv_2_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast, RES_forecast, RES_sum, M, s_power_minus)
    else:
        with build_tracker.section("res_curtailment_objective"):
            for i in RES:
                for t in intervals[1:]:
                    objective_terms += (
                            (RES_forecast[t - 1][i] - power[i][t]) * 1000 * input_data["Time_granularity"]  #RES_forecast[t - 1][i]
                    )
                    # pass
    if input_data["constraints"]["testing_mode_constraints"]:
        with build_tracker.section("testing_mode"):
            prob, objective_terms = create_testing_mode_constraints(prob, objective_terms, input_data, data, power, intervals, CONV)
    if input_data["constraints"]["OOS_mode_constraints"]:
        with build_tracker.section("oos_mode"):
            prob, objective_terms = create_OOS_mode_constraints(prob, objective_terms, input_data, data, power, intervals, PV_no_SP)
    # State-level timing is intentionally limited to minimum on/off time. It
    # uses the unit-level state/startup/shutdown variables and the
    # state-transitions min-transition-time fields.
    if input_data["constraints"].get("state_min_time_constraint", input_data["constraints"].get("states_time_constraint", False)):
        with build_tracker.section("state_minimum_time"):
            prob, objective_terms = create_state_min_time_constraints(prob, objective_terms, input_data, data, state, intervals, startup, shutdown)

    # prob += u_2_dict[(2, 8, 4)] == 1
    # prob += u_2_dict[(2, 16, 6)] == 1
    # prob += u_2_dict[(0, 4, 6)] == 1
    # prob += u_2_dict[(0, 1, 4)] == 1
    # prob += u_2_dict[(0, 2, 4)] == 1
    # prob += u_2_dict[(0, 3, 4)] == 1
    # prob += u_2_dict[(0, 4, 4)] == 1
    # prob += u_2_dict[(0, 5, 4)] == 1
    # prob += u_2_dict[(0, 6, 4)] == 1
    #
    # for t in intervals[1:]:
    #     prob += s_Grid_Capacity_1[t] == s_Grid_Capacity_2[t] == s_Grid_Capacity_3[t] == 0


    # prob += power[0][2] == 11
    # prob += power[2][7] == 2
    # prob += u_2_dict[(1, 10, 2)] == 1
    # prob += u_2_dict[(1, 11, 3)] == 1
    # prob += u_2_dict[(1, 12, 4)] == 1
    # # prob += u_2_dict[(1, 13, 4)] == 1
    # prob += u_2_dict[(1, 14, 4)] == 1
    # prob += u_2_dict[(1, 15, 2)] == 1
    # prob += u_2_dict[(1, 16, 4)] == 1
    # prob += u_2_dict[(1, 17, 4)] == 1
    # prob += u_2_dict[(1, 10, 4)] == 0

    # prob += power[0][3] == 8.6
    # # prob += power[1][3] == 5.7
    # prob += power[0][1] == 15.6
    # # prob += power[1][1] == 17.3
    # prob += state[5][6] == 1
    # prob += state[5][5] == 1

    # prob += power[0][3] == 0
    # prob += power[1][3] == 0
    # prob += power[2][3] == 0
    # prob += state[0][10] == 1
    # prob += state[0][5] == 0
    # prob += state[0][6] == 0
    # prob += state[1][9] == 0
    # prob += power[0][3] == 0
    # prob += power[0][4] == 15.5
    # prob += power[0][5] == 8.5

    # prob += u_2_dict[(1, 10, 2)] == 1
    # prob += u_2_dict[(1, 11, 3)] == 1
    # prob += u_2_dict[(1, 12, 4)] == 1
    # prob += power[1][13] == 0

    # prob += u_1_dict[(0, 1, 0)] == 1
    # prob += u_2_dict[(0, 13, 6)] == 1

    # prob += u_2_dict[(gen_id, t, operating_state_id)] == 1

    with build_tracker.section("commitment_objective_terms"):
        for i, gen in enumerate(data):
            for t in intervals[1:]:
                if i in CONV:
                    objective_terms += (
                            gen.get('start_up_cost(euro)', 0) * startup[i][t] + gen.get('shut_down_cost(euro)', 0) *
                            shutdown[i][t] + state[i][t] * (+100) * input_data["Time_granularity"]
                    )
                #
                # the two following conditional terms, could be commented out as there is already the
                # term that pushes the solution to be as close to the rdas solution, as possible

                # if i in RES:
                #     objective_terms += power[i][t] * (-11320) * input_data["Time_granularity"]  #(-1000) -11320

    # objective_terms += 13123000000

    # Add the objective terms to the objective function
    with build_tracker.section("objective"):
        prob += pl.lpSum(objective_terms)

    # Στο στοχαστικό μοντέλο διατηρούμε όλη την άλγεβρα χωρίς ενδιάμεση επίλυση.
    # Η προεπιλεγμένη ντετερμινιστική διαδρομή παραμένει αμετάβλητη.
    if build_only:
        name_auto_constraints(prob)
        return prob, {
            "data": data, "intervals": intervals, "power": power,
            "state": state, "startup": startup, "shutdown": shutdown,
            "operating_states": u_2_dict, "CONV": CONV, "RES": RES, "PV": PV,
            "constraint_sections": build_tracker.summary(), "big_m": M,
        }

    # Check if the problem is an MIP problem
    if prob.isMIP():
        print("The problem is a Mixed-Integer Programming (MIP) problem.")
    # # Solve the problem
    # prob.solve()

    # Specify the path for the log file
    # log_file_path = "solver_log.txt"
    # path_to_glpk = r'C:\Users\NikosPapadopoulos\PycharmProjects\pythonProject\venv\Lib\site-packages\pulp\solverdir\glpk\glpk-4.65\w64\glpsol.exe'

    # solver = pl.GLPK_CMD(path=path_to_glpk, msg=True, timeLimit=620)
    # path_to_cplex = r'C:\Program Files\IBM\ILOG\CPLEX_Studio_Community2211\cplex\bin\x64_win64\cplex.exe'

    # solver = pl.GUROBI(msg=True, timeLimit=timeLimit, gapRel=0.1)  # gapRel=0.1,

    # solver = pl.CPLEX_PY(msg=True, timeLimit=timeLimit, gapRel=0.1)  # gapRel=0.1
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles, gapRel=0.1)




    # solver = pl.PULP_CBC_CMD(msg=True, timeLimit=timeLimit) #gapRel=0.1 # logPath=log_file_path  keepFiles=keepFiles, warmStart=warmStart
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles)

    # Set the number of threads
    # import os
    # os.environ['OMP_NUM_THREADS'] = '8'
    #
    # # Load the initial values from the JSON file
    # with open('solution_values.json', 'r') as f:
    #     initial_values = json.load(f)
    #
    # start_time_init = time.time()
    # print("initialization is starting")
    # #  Set initial values for warm start
    # for var_name, value in initial_values.items():
    #     if var_name in prob.variablesDict():
    #         var = prob.variablesDict()[var_name]
    #         var.setInitialValue(value)
    #
    # print("initialization is completed")
    # end_time_init = time.time()
    #
    # initialization_time = end_time_init - start_time_init
    # print("Initialization time:", round(initialization_time, 3), "seconds")
    # print('')

    # solver = HiGHS_CMD(path=r'C:\Users\NikosPapadopoulos\PycharmProjects\pythonProject4\venv\Lib\site-packages\HiGHS_build\RELEASE\bin\highs.exe', options=['--parallel choose'], msg=True, keepFiles=True)  # timeLimit=450
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles)
    # solver = pl.PULP_CBC_CMD(msg=True, keepFiles=True, warmStart=True)  #gapRel=0.1 # logPath=log_file_path  keepFiles=keepFiles, warmStart=warmStart
    # prob.solve(solver)
    # print(pl.listSolvers(onlyAvailable=True))
    # print(pl.listSolvers())
    # Define solver and set parameters
    # solver = pl.PULP_CBC_CMD(options=[
    #     'maxSolutions 1',  # Limit the number of solutions # 'sec 120',  # Set time limit to 120 seconds
    #
    #     'ratio 0.1',  # Set gap tolerance to 1%
    #     'threads 8'  # Use 4 threads
    #     # Additional parameters as needed
    # ])
    # prob.solve(highs_solver)
    constraint_sections = build_tracker.summary()
    print("Constraint build sections:")
    for section in constraint_sections:
        print(
            f"  {section['section']}: "
            f"+{section['constraints_added']} constraints, "
            f"+{section['variables_added']} variables"
        )

    renamed_constraints = name_auto_constraints(prob)
    print(f"Named anonymous constraints: {renamed_constraints}")

    # Write the model to an MPS file without solving

    mps_filename = "example_model.mps"
    mps_write_start = time.time()
    prob.writeMPS(mps_filename)
    mps_write_seconds = time.time() - mps_write_start

    print(f"Model successfully written to {mps_filename} without solving.")
    end_time = time.time()
    execution_time = end_time - start_time
    print(".mps file creation time:", round(execution_time, 3), "seconds")
    print('')

    solver_name = (solver_name or "highs").lower()
    solver_options = solver_options or {}
    if solver_name == "highs":
        solver = pl.HiGHS(
            msg=True, timeLimit=timeLimit, gapRel=gapRel, gapAbs=gapAbs, threads=threads,
            **solver_options)
    elif solver_name == "cbc":
        solver = pl.PULP_CBC_CMD(
            msg=True, timeLimit=timeLimit, keepFiles=keepFiles, warmStart=warmStart,
            logPath=logPath, gapRel=gapRel, gapAbs=gapAbs, threads=threads)
    else:
        raise ValueError(f"Unsupported solver '{solver_name}'. Use 'highs' or 'cbc'.")
    print(f"Using solver backend: {solver_name}")

    print("Number of constraints:", prob.numConstraints())
    print("Number of variables:", prob.numVariables())
    print("")
    solver_start_time = time.time()
    prob.solve(solver)
    solver_seconds = time.time() - solver_start_time

    Solution_Status = pl.LpStatus[prob.status]
    print("Objective function cost =", round(pl.value(prob.objective), 2))
    print('Status: ', pl.LpStatus[prob.status])
    print('')

    end_time_2 = time.time()
    execution_time_2 = end_time_2 - start_time
    print("DS execution time:", round(execution_time_2, 3), "seconds")
    print('')

    if require_optimal and Solution_Status != "Optimal":
        raise RuntimeError(
            f"Solver finished with status '{Solution_Status}', but an optimal solution is required. "
            "Increase/remove the time limit, relax require_optimal, or inspect the solver log."
        )

    # if pl.LpStatus[prob.status] == 'Optimal':
    #     print("Objective function cost =", round(pl.value(prob.objective), 5))
    # else:
    #     print("Problem not solved successfully. Status:", pl.LpStatus[prob.status])
    # if logPath == None:
    #     pass
    # else:
    #     try:
    #         with open(log_file_path, 'r') as file:
    #             solver_output = file.read()
    #         # print(solver_output)
    #         # Variable to store the matched line
    #         result_line = ""
    #         # Open the file in read mode
    #         with open(log_file_path, 'r') as file:
    #             # Iterate over each line
    #             for line in file:
    #                 # Check if the line starts with "Result -"
    #                 if line.startswith("Result -"):
    #                     result_line = line.strip()  # Using strip() to remove any leading/trailing whitespace
    #                     break  # Exit the loop once the line is found
    #         # result_line contains the desired line or is an empty string if no match was found
    #         print(result_line)
    #     except FileNotFoundError:
    #         print("Log file not found. Please check the solver and file path.")
    #     print('')
    #
    # # Extract values from the solved problem
    # solution_values = {v.name: v.varValue for v in prob.variables()}
    # # Serialize and save the dictionary to a file
    # with open('solution_values.json', 'w') as file:
    #     json.dump(solution_values, file)

    # Print the results
    # for v in prob.variables():
    #     print(v.name, "=", v.varValue)
    # Solution_Status = pl.LpStatus[prob.status]
    # print("Objective function cost =", round(pl.value(prob.objective), 2))
    # print('Status: ', Solution_Status)
    # print('')
    # print('# Must_run_units:', count_mru.value())

    # check the status
    # if pl.LpStatus[prob.status] == 'Optimal':
    #     print("The solution is optimal.")
    # else:
    #     print("The solution is not optimal.")


    # def categorize_variables(model):
    #     binary_vars = []
    #     integer_vars = []
    #     continuous_vars = []
    #
    #     for var in model.variables():
    #         if var.cat == 'Binary':
    #             binary_vars.append(var)
    #         elif var.cat == 'Integer':
    #             integer_vars.append(var)
    #         else:
    #             continuous_vars.append(var)
    #
    #     return binary_vars, integer_vars, continuous_vars
    #
    # # Get categorized variables
    # binary_vars, integer_vars, continuous_vars = categorize_variables(prob)
    #
    # # # Display the lists
    # # print("Binary Variables:", [var.name for var in binary_vars])
    # # print("Integer Variables:", [var.name for var in integer_vars])
    # # print("Continuous Variables:", [var.name for var in continuous_vars])
    #
    # # Total_cost = [0] * len(Load_forecast)
    # # for t in intervals[1:]:
    # #     for i, gen in enumerate(data):
    # #         if i in CONV:
    # #
    # #             if input_data["constraints"]["primary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += primary_ActPR_plus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][0] + \
    # #                                  primary_ActPR_minus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][1]
    # #             if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += secondary_ActPR_plus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][0] + \
    # #                                  secondary_ActPR_minus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][1]
    # #             if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += tertiary_ActPR_plus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][0] + \
    # #                                  tertiary_ActPR_minus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][1]
    # #
    # #             Total_cost[t] += gen.get('start_up_cost(euro)', 0) * startup[i][t].value() + gen.get(
    # #                 'shut_down_cost(euro)', 0) * shutdown[i][t].value()
    # #             # primary_ActPR_plus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][0] + \
    # #             # primary_ActPR_minus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][1] + \
    # #             # + tertiary_ActPR_plus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][0] + \
    # #             # tertiary_ActPR_minus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][1] +
    # #             # secondary_ActPR_plus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][0] + \
    # #             # secondary_ActPR_minus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][1] \
    # #
    # #             for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    # #                 Total_cost[t] += s * z_1[i][t][s_index].value()
    # #             for s_2_index, s_2 in enumerate(
    # #                     gen['Thermal_state_costs'][0]):  # for startup from a specific previous hour's thermal state
    # #                 # print(i,t,z_3[i][t][s_2_index].value())
    # #                 # print(u_2[i][t-1][s_2_index].value())
    # #                 Total_cost[t] += s_2 * z_3[i][t][s_2_index].value()
    # #             for s_3_index, s_3 in enumerate(
    # #                     gen['Thermal_state_costs'][1]):  # for remaining in a specific thermal state every hour t
    # #                 Total_cost[t] += s_3 * u_2[i][t][s_3_index].value()
    # #         # print(round(Total_cost[t],2))
    # # for t in intervals[1:]:
    # #     Total_cost[t] = round(Total_cost[t],
    # #                           2)  # we should divide by 4 some cost variables because the respective cost is calculated per hour
    # # Total_cost = [0, 0]
    solve_metadata = {
        "solver": solver_name,
        "solution_status": Solution_Status,
        "objective_value": round(pl.value(prob.objective), 8),
        "big_m": M,
        "num_constraints": prob.numConstraints(),
        "num_variables": prob.numVariables(),
        "anonymous_constraints_named": renamed_constraints,
        "constraint_sections": constraint_sections,
        "mps_file": mps_filename,
        "mps_write_seconds": round(mps_write_seconds, 3),
        "solver_seconds": round(solver_seconds, 3),
        "model_build_and_solve_seconds": round(execution_time_2, 3),
    }

    return prob.variables(), RES, Solution_Status, solve_metadata

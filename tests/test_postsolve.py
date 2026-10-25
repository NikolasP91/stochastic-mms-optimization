"""Tests for post-solve parsing and output helper behavior."""

import unittest

import pandas as pd

from mms.postsolve import create_output_json_template, setpoint_calculation


class PostsolveTests(unittest.TestCase):
    """Checks post-solve parsing and output helpers."""
    def test_setpoint_calculation_includes_pv_rows(self):
        input_data = {"constraints": {"res_pv_dispatch_variables_constraints": True}}
        setpoint_df = pd.DataFrame(
            [
                [0.0, 0.0],
                [0.5, 0.6],
                [0.2, 0.3],
            ]
        )

        result = setpoint_calculation(
            input_data,
            RES=[1],
            PV=[2],
            RES_forecast=[[0, 10, 5], [0, 12, 6]],
            Sum_RES_forecast=[0, 15, 18],
            data=[],
            power_df=pd.DataFrame(),
            setpoint_df=setpoint_df,
            state_df=pd.DataFrame(),
        )

        self.assertEqual([0.5, 0.6], list(result.iloc[1]))
        self.assertEqual([0.2, 0.3], list(result.iloc[2]))

    def test_pv_output_template_has_setpoints_field(self):
        template = create_output_json_template(
            data=[{}, {}],
            CONV=[],
            RES=[0],
            PV=[1],
            Partially_Controllable=[],
        )

        self.assertIn("Setpoints", template[1])


if __name__ == "__main__":
    unittest.main()

import unittest
import numpy as np
import pandas as pd

# Import the functions directly if the file is in the same directory
from et_model import (
    saturation_vapour_pressure,
    delta_vapour_pressure,
    calculate_et0,
    xl_col_letter
)

class TestETModelHelpers(unittest.TestCase):

    def test_saturation_vapour_pressure(self):
        # Known value: at 20°C, es ≈ 2.338 kPa
        T = 20
        expected = 0.6108 * np.exp((17.27 * T) / (T + 237.3))
        self.assertAlmostEqual(saturation_vapour_pressure(T), expected, places=3)

    def test_delta_vapour_pressure(self):
        # At 20°C, delta ≈ 0.1448 kPa/°C
        T = 20
        es = saturation_vapour_pressure(T)
        expected = 4098 * es / (T + 237.3) ** 2
        self.assertAlmostEqual(delta_vapour_pressure(T), expected, places=4)

    def test_calculate_et0_typical(self):
        # Use standard test values
        row = pd.Series({
            "T": 25,           # °C
            "u2": 2,           # m/s
            "RH": 60,          # %
            "GHI": 500         # W/m²
        })
        # Should return a non-negative float
        result = calculate_et0(row)
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0)

    def test_calculate_et0_zero_rh(self):
        row = pd.Series({
            "T": 25,
            "u2": 2,
            "RH": 0,
            "GHI": 500
        })
        result = calculate_et0(row)
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0)

    def test_xl_col_letter(self):
        # Mock weather_df in the function's scope
        import et_model
        et_model.weather_df = pd.DataFrame(columns=["T", "u2", "RH", "GHI", "Precip_mm"])
        self.assertEqual(xl_col_letter("T"), "A")
        self.assertEqual(xl_col_letter("GHI"), "D")
        with self.assertRaises(ValueError):
            xl_col_letter("NonExistent")

if __name__ == "__main__":
    unittest.main()

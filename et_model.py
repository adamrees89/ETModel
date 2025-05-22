import pandas as pd
import numpy as np
import yaml
from pvlib.iotools import read_epw
from pandas import ExcelWriter

# Constants
LAMBDA = 2.45  # MJ/kg, latent heat of vaporisation
MJ_TO_KWH = 1 / 3.6
GAMMA = 0.0665  # Psychrometric constant

# File paths
epw_file = 'weather.epw'
props_csv = 'plant_properties.csv'
config_file = 'plant_config.yaml'
output_excel = 'et_hourly_results.xlsx'

# Load weather data
epw_data, _ = read_epw(epw_file)
weather_df = epw_data[['temp_air', 'wind_speed', 'relative_humidity', 'ghi', 'precipitation']].copy()
weather_df.columns = ['T', 'u2', 'RH', 'GHI', 'Precip_mm']

# Load plant data
props_df = pd.read_csv(props_csv)
with open(config_file, 'r') as f:
    config = yaml.safe_load(f)

# Merge properties into config
plants_config = []
for plant in config['plants']:
    row = props_df.loc[props_df['Plant Type'] == plant['type']]
    if row.empty:
        raise ValueError(f"Plant type {plant['type']} not found in plant_properties.csv")
    props = row.iloc[0]
    plants_config.append({
        'type': plant['type'],
        'area_m2': plant['area_m2'],
        'kc': props['Kc'],
        'root_depth_m': props['Root Depth (m)'],
        'wilting_point': props['Wilting Point'],
        'field_capacity': props['Field Capacity']
    })

# Helper functions
def saturation_vapour_pressure(T):
    """
    Calculates the saturation vapor pressure at a given temperature.
    
    Args:
        T: Air temperature in degrees Celsius.
    
    Returns:
        Saturation vapor pressure in kilopascals (kPa).
    """
    return 0.6108 * np.exp((17.27 * T) / (T + 237.3))

def delta_vapour_pressure(T):
    """
    Calculates the slope of the saturation vapor pressure curve at a given temperature.
    
    Args:
        T: Air temperature in degrees Celsius.
    
    Returns:
        The slope of the saturation vapor pressure curve (kPa/°C) at temperature T.
    """
    es = saturation_vapour_pressure(T)
    return 4098 * es / (T + 237.3)**2

def calculate_et0(row):
    """
    Calculates hourly reference evapotranspiration (ET0) using the FAO Penman-Monteith equation.
    
    Args:
        row: A pandas Series containing temperature ('T', °C), wind speed ('u2', m/s),
            relative humidity ('RH', %), and global horizontal irradiance ('GHI', W/m²).
    
    Returns:
        The computed ET0 value in millimeters per hour (mm/hr), constrained to be non-negative.
    """
    T, u2, RH, GHI = row['T'], row['u2'], row['RH'], row['GHI']
    es = saturation_vapour_pressure(T)
    ea = es * RH / 100
    delta = delta_vapour_pressure(T)
    Rn = GHI * 0.8 / 3.6  # MJ/m²/hr
    et0 = ((0.408 * delta * Rn) + (GAMMA * (900 / (T + 273)) * u2 * (es - ea))) / (delta + GAMMA * (1 + 0.34 * u2))
    return max(et0, 0)

# Calculate ET0
weather_df['ET0_mm'] = weather_df.apply(calculate_et0, axis=1)

# Initialise total ET actual
total_et_actual = np.zeros(len(weather_df))
writer = ExcelWriter(output_excel, engine='xlsxwriter')

# Simulate each plant
for plant in plants_config:
    plant_type = plant['type']
    area = plant['area_m2']
    kc = plant['kc']
    root_depth = plant['root_depth_m']
    theta_wp = plant['wilting_point']
    theta_fc = plant['field_capacity']
    
    theta = theta_fc
    thetas, kss, et_actuals, cooling_kWh = [], [], [], []
    
    for i, row in weather_df.iterrows():
        P = row['Precip_mm'] / 1000  # mm to m
        ET0_mm = row['ET0_mm']
        
        if theta >= theta_fc:
            Ks = 1
        elif theta <= theta_wp:
            Ks = 0
        else:
            Ks = (theta - theta_wp) / (theta_fc - theta_wp)
        
        ET_actual_mm = Ks * kc * ET0_mm
        theta += (P - ET_actual_mm / 1000) / root_depth
        theta = min(max(theta, theta_wp), theta_fc)
        
        cooling = ET_actual_mm * area * LAMBDA * MJ_TO_KWH / 1000
        
        total_et_actual[i] += ET_actual_mm
        
        thetas.append(theta)
        kss.append(Ks)
        et_actuals.append(ET_actual_mm)
        cooling_kWh.append(cooling)
    
    # Store in DataFrame
    weather_df[f'SoilTheta_{plant_type}'] = thetas
    weather_df[f'Ks_{plant_type}'] = kss
    weather_df[f'ET_actual_{plant_type}'] = et_actuals
    weather_df[f'Cooling_{plant_type}_kWh'] = cooling_kWh

# Add total ET line
weather_df['ET_actual_total'] = total_et_actual

# Save and chart
weather_df.to_excel(writer, sheet_name='ET Results', index=False)
workbook = writer.book
worksheet = writer.sheets['ET Results']
chart = workbook.add_chart({'type': 'line'})

for plant in plants_config:
    plant_type = plant['type']
    col = weather_df.columns.get_loc(f'ET_actual_{plant_type}')
    chart.add_series({
        'name': f'ET_actual_{plant_type}',
        'categories': ['ET Results', 1, 0, len(weather_df), 0],
        'values':     ['ET Results', 1, col, len(weather_df), col],
    })

col_total = weather_df.columns.get_loc('ET_actual_total')
chart.add_series({
    'name': 'ET_actual_total',
    'categories': ['ET Results', 1, 0, len(weather_df), 0],
    'values':     ['ET Results', 1, col_total, len(weather_df), col_total],
    'line': {'width': 2.25, 'dash_type': 'solid', 'color': 'black'}
})

chart.set_title({'name': 'Hourly Actual ET by Plant Type'})
chart.set_x_axis({'name': 'Time'})
chart.set_y_axis({'name': 'ET (mm)'})
worksheet.insert_chart('J2', chart)

writer.close()
print("Done. Results written to", output_excel)
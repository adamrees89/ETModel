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
config_file = 'config.yaml'
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
        available_types = props_df['Plant Type'].unique()
        raise ValueError(f"Plant type '{plant['type']}' not found in plant_properties.csv. Available types: {', '.join(available_types)}")
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

def calculate_et0(row: pd.Series) -> float:
    """
    Calculate reference evapotranspiration (ET0) using the FAO Penman-Monteith equation.
    
    Reference: Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.
    Crop Evapotranspiration - Guidelines for Computing Crop Water Requirements.
    FAO Irrigation and Drainage Paper 56, Rome, Italy.
    
    Args:
        row: Pandas Series containing weather data (T, u2, RH, GHI)
        
    Returns:
        Hourly reference evapotranspiration in mm
    """
    T, u2, RH, GHI = row['T'], row['u2'], row['RH'], row['GHI']
    es = saturation_vapour_pressure(T)
    ea = es * RH / 100
    delta = delta_vapour_pressure(T)
    Rn = GHI * 0.8 / 3.6  # MJ/m²/hr
    et0 = ((0.408 * delta * Rn) + (GAMMA * (900 / (T + 273)) * u2 * (es - ea))) / (delta + GAMMA * (1 + 0.34 * u2))
    return max(et0, 0)

def xl_col_letter(col_name):
    """Convert column name to Excel column letter."""
    import string
    if col_name in weather_df.columns:
        col_num = weather_df.columns.get_loc(col_name) + 1
        col_letter = ''
        while col_num > 0:
            col_num, remainder = divmod(col_num - 1, 26)
            col_letter = string.ascii_uppercase[remainder] + col_letter
        return col_letter
    else:
        raise ValueError(f"Column {col_name} not found in DataFrame")

# Calculate ET0
weather_df['ET0_mm'] = weather_df.apply(calculate_et0, axis=1)

# Initialise total ET actual
total_et_actual = np.zeros(len(weather_df))
try:
    writer = ExcelWriter(output_excel, engine='xlsxwriter')
except Exception as e:
    print(f"Error creating Excel file: {e}")
    raise

# Simulate each plant
for plant in plants_config:
    plant_type = plant['type']
    area = plant['area_m2']
    kc = plant['kc']
    root_depth = plant['root_depth_m']
    theta_wp = plant['wilting_point']
    theta_fc = plant['field_capacity']
    
    # Validate parameters
    if area <= 0:
        raise ValueError(f"Plant area must be positive, got {area} for {plant_type}")
    if root_depth <= 0:
        raise ValueError(f"Root depth must be positive, got {root_depth} for {plant_type}")
    if not 0 <= theta_wp < theta_fc <= 1:
        raise ValueError(
            f"Invalid soil parameters: wilting point ({theta_wp}) must be "
            f"less than field capacity ({theta_fc}) and both must be between 0 and 1 for {plant_type}"
        )
    if kc <= 0:
        raise ValueError(f"Crop coefficient must be positive, got {kc} for {plant_type}")
    
    # ... rest of simulation logic ...
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
        # Calculate infiltration with simple rainfall intensity threshold
        P_infiltration = P
        if P * 1000 > 20:  # If precipitation > 20mm, assume partial runoff
            P_infiltration = min(P, 20/1000 + (P - 20/1000) * 0.7)  # 70% of rainfall above 20mm becomes runoff
            
        theta += (P_infiltration - ET_actual_mm / 1000) / root_depth
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
    chart.add_series({
        'name': f'ET_actual_{plant_type}',
        'categories': ['ET Results', 1, 0, len(weather_df), 0],
        'values':     f'=ET Results!${xl_col_letter(f"ET_actual_{plant_type}")}$2:${xl_col_letter(f"ET_actual_{plant_type}")}${len(weather_df)+1}',
    })

chart.add_series({
    'name': 'ET_actual_total',
    'categories': ['ET Results', 1, 0, len(weather_df), 0],
    'values':     f'=ET Results!${xl_col_letter("ET_actual_total")}$2:${xl_col_letter("ET_actual_total")}${len(weather_df)+1}',
    'line': {'width': 2.25, 'dash_type': 'solid', 'color': 'black'}
})

chart.set_title({'name': 'Hourly Actual ET by Plant Type'})
chart.set_x_axis({'name': 'Time'})
chart.set_y_axis({'name': 'ET (mm)'})
worksheet.insert_chart('J2', chart)

writer.close()
print("Done. Results written to", output_excel)
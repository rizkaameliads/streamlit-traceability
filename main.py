# -*- coding: utf-8 -*-
"""
streamlit_traceability.py

This script converts the Dash-based traceability dashboard into a Streamlit application.
It fetches data from KoboToolbox, performs spatial analysis, and displays interactive
visualizations and a map using Streamlit and Folium.
"""

# --- 1. LIBRARIES ---
import streamlit as st
import pandas as pd
import geopandas as gpd
import requests
import json
import plotly.express as px
import folium
from streamlit_folium import st_folium

# --- 2. INITIAL PAGE CONFIGURATION ---
# Set the layout to wide mode for a better dashboard experience
st.set_page_config(layout="wide")

# --- 3. DATA LOADING AND PROCESSING ---
# This part remains largely the same as your original script.
# We can use @st.cache_data to speed up the app by caching the data pull.

@st.cache_data(ttl=600) # Cache data for 10 minutes
def load_kobo_data():
    """Fetches data from the KoboToolbox API."""
    KOBO_TOKEN = "036d4c8aeb6a0c011630339e605e7e8bb5500c7b"
    ASSET_UID = "aNkj5BVuLuqGfqustJMNaM"
    KOBO_API_URL = f"https://kc.kobotoolbox.org/api/v2/assets/{ASSET_UID}/data.json/"
    HEADERS = {"Authorization": f"Token {KOBO_TOKEN}"}

    try:
        response = requests.get(KOBO_API_URL, headers=HEADERS)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()['results']
        df = pd.DataFrame(data)
        
        # --- Data Cleaning and Type Conversion ---
        # Convert numeric columns, coercing errors to NaN
        numeric_cols = ["plot_area", "C2_Total_synthetic_ast_year_on_farm_kg", 
                        "main_crop_productivity", "C1_Organic_fertiliz_ast_year_on_farm_kg"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Convert date column
        df['Data_collection_date'] = pd.to_datetime(df['Data_collection_date'])
        
        # Split location into latitude and longitude
        df[['lat', 'lon']] = df['B2_Plot_location'].str.split(' ', expand=True).iloc[:, :2].astype(float)
        
        return df
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data from KoboToolbox: {e}")
        return pd.DataFrame() # Return empty dataframe on error

@st.cache_resource # Cache the GeoDataFrames
def load_spatial_data():
    """Loads auxiliary spatial data (Peatland and Protected Areas)."""
    try:
        # NOTE: Update these paths to be accessible by your Streamlit app
        # It's best to place them in the same directory or a subdirectory.
        peatland_khGambut_gdf = gpd.read_file("INDONESIA PEATLAND 2017.zip")
        protected_areas_gdf = gpd.read_file("Protected_Areas_Generalized.zip")

        # Ensure CRS is consistent (WGS84)
        peatland_khGambut_gdf = peatland_khGambut_gdf.to_crs(epsg=4326)
        protected_areas_gdf = protected_areas_gdf.to_crs(epsg=4326)

        # Convert any datetime columns in protected_areas_gdf to string
        # to prevent JSON serialization errors with Folium.
        for col in protected_areas_gdf.columns:
            if pd.api.types.is_datetime64_any_dtype(protected_areas_gdf[col]):
                protected_areas_gdf[col] = protected_areas_gdf[col].astype(str)

        return peatland_khGambut_gdf, protected_areas_gdf
    except Exception as e:
        st.error(f"Error loading spatial data files. Make sure the files are in the correct path: {e}")
        return None, None

# Load all data
df = load_kobo_data()
peatland_gdf, protected_areas_gdf = load_spatial_data()

# Stop the app if data loading failed
if df.empty or protected_areas_gdf is None:
    st.warning("Data loading failed. Halting application.")
    st.stop()

# --- 4. SPATIAL ANALYSIS: INTERSECTION ---
# This logic is moved from the original script directly here.

# Convert survey data to a GeoDataFrame
survey_gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df['lon'], df['lat']),
    crs=protected_areas_gdf.crs
)

# Perform spatial join
points_in_protected_areas = gpd.sjoin(survey_gdf, protected_areas_gdf, how="inner", predicate="intersects")

# Create a boolean column to mark points inside protected areas
df['in_protected_area'] = df.index.isin(points_in_protected_areas.index)

# --- 5. UI: SIDEBAR ---
# In Streamlit, it's common to put filters in a sidebar.
st.sidebar.title("Welcome to The Traceability Dashboard!")
st.sidebar.markdown("How to use this dashboard:")

# --- 6. MAIN DASHBOARD LAYOUT ---
logo_col, title_col = st.columns([2, 12])

with logo_col:
    st.image("RCT_Logo.png")

with title_col:
    st.title("TRACEABILITY DASHBOARD")
    st.markdown("**© 2025 ReClimaTech**")

# --- TABS ---
tabs = st.tabs(["Dashboard", "About"])

with tabs[0]:
    # --- FILTER ---
    st.subheader("Filters")

    # Get unique farmer groups, handling potential None or NaN values
    farmer_group_options = [group for group in df['A13_Farmer_group_cooperative'].unique() if pd.notna(group)]
    selected_groups = st.multiselect(
            'Select Farmer Group(s):',
            options=farmer_group_options,
            default=farmer_group_options)

    # Filter the dataframe based on selection
    if selected_groups:
        filtered_df = df[df['A13_Farmer_group_cooperative'].isin(selected_groups)].copy()
    else:
        filtered_df = df.copy()

    # --- INDICATOR & FARM MANAGEMENT CHARTS ---
    st.subheader("Plot Information & Farm Management")

    # Calculate metrics from the filtered dataframe
    avg_plot_area = filtered_df["plot_area"].mean()
    avg_synth_fert = filtered_df["C2_Total_synthetic_ast_year_on_farm_kg"].mean()
    avg_prod = filtered_df["main_crop_productivity"].mean()
    avg_org_fert = filtered_df["C1_Organic_fertiliz_ast_year_on_farm_kg"].mean()

    # --- PIE CHARTS (CORRECTED & IMPROVED LAYOUT) ---
    def create_pie_chart(data, column_name, title, name_map=None):
        """Helper function to create styled Plotly pie charts."""
        pie_data = data[column_name].value_counts().reset_index()
        pie_data.columns = ['Answer', 'Count']

        # ✅ FIX: This section was missing. It applies the new names.
        if name_map:
            pie_data['Answer'] = pie_data['Answer'].map(name_map).fillna(pie_data['Answer'])
        
        fig = px.pie(pie_data, values='Count', names='Answer', title=title,
                    hole=0.4, width=300, height=200)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=45, b=5))
        return fig

    # --- DISPLAY INDICATOR & FARM MANAGEMENT PIE CHARTS ---
    pifm_1, pifm_2 = st.columns([3, 4])

    with pifm_1:
        col_m1, col_m2 = st.columns(2)

        with col_m1:
            st.metric("Average Plot Area (ha)", f"{avg_plot_area:.2f}", border=True)
            st.metric("Average Crop Productivity (kg/ha)", f"{avg_prod:.2f}", border=True)

        with col_m2:
            st.metric("Average Synthetic Fertilizer (kg/ha)", f"{avg_synth_fert:.2f}", border=True)
            st.metric("Average Organic Fertilizer (kg/ha)", f"{avg_org_fert:.2f}", border=True)

    with pifm_2:
        fm_1, fm_2, fm_3 = st.columns(3)

        with fm_1:
            st.plotly_chart(create_pie_chart(filtered_df, "Are_you_applying_chemical_pest", "Pesticide Application"), use_container_width=False)
        with fm_2:
            st.plotly_chart(create_pie_chart(filtered_df, "Are_you_applying_chemical_herb", "Herbicide Application"), use_container_width=False)

        with fm_3:
            agro_practice_names = {
                'fully_implement': 'Fully Implemented',
                'partially_implement': 'Partially Implemented',
                'no': 'No'
            }
            st.plotly_chart(create_pie_chart(
                filtered_df, 
                "C5_Type_of_agroforestry_practice", 
                "Agroforestry Practice", 
                name_map=agro_practice_names
            ), use_container_width=False)

    st.markdown("---") # Visual separator

    # --- 7. INTERACTIVE MAP & LISTS ---
    st.subheader("Survey Distribution Map and Farmer Data")

    map_col, list_col, alert_col = st.columns([3, 1, 1]) # Give the map more space

    with map_col:    
        # Create the Folium map centered on Indonesia
        center_lat, center_lon = -2.5489, 118.0149
        m = folium.Map(location=[center_lat, center_lon], zoom_start=4, tiles="CartoDB positron")

        # --- Add GeoJSON Layers ---
        # Layer 1: Peatland
        folium.GeoJson(
            peatland_gdf,
            name="Southeast Asia Peatland",
            style_function=lambda x: {'fillColor': '#4E7254', 'color': '#4E7254', 'weight': 2, 'fillOpacity': 0.5},
            tooltip=folium.GeoJsonTooltip(fields=['NAMA_KHG'], aliases=['Peatland:']),
            show=False # Initially turned off
        ).add_to(m)

        # Layer 2: Protected Areas
        # Define color mapping for protected areas
        pa_color_map = {
            "Hutan Lindung": "#9D9101", "Taman Wisata Alam": "#B32428",
            "Hutan Suaka Alam dan Wisata": "#E6D690", "Cagar Alam": "#4E3B31",
            "Taman Buru": "#4A192C", "Taman Nasional": "#4C514A",
            "Taman Hutan Raya": "#474B4E", "Suaka Margasatwa": "#6C3B2A",
            "Kawasan Suaka Alam/Kawasan Pelestarian Alam": "#1B5583"
        }
        
        folium.GeoJson(
            protected_areas_gdf,
            name="Protected Areas (2021)",
            style_function=lambda feature: {
                'fillColor': pa_color_map.get(feature['properties']['NAMOBJ'], 'gray'),
                'color': pa_color_map.get(feature['properties']['NAMOBJ'], 'gray'),
                'weight': 2,
                'fillOpacity': 0.5
            },
            tooltip=folium.GeoJsonTooltip(fields=['NAMOBJ'], aliases=['Protected Area:']),
            show=False # Initially turned off
        ).add_to(m)

        # --- Add Survey Points Markers ---
        marker_group = folium.FeatureGroup(name="Survey Data").add_to(m)
        for _, row in filtered_df.iterrows():
            # Determine color based on intersection status
            color = 'red' if row['in_protected_area'] else 'black'
            
            # Create the popup HTML content
            popup_html = f"""
            <b>Enumerator:</b> {row.get('Enumerator_name', 'N/A')}<br>
            <b>Farmer Name:</b> {row.get('A1_Producer_farmer_name_first_name', 'N/A')}<br>
            <b>Farmer ID:</b> {row.get('A3_Farmer_ID', 'N/A')}<br>
            <b>Group:</b> {row.get('A13_Farmer_group_cooperative', 'N/A')}<br>
            <b>Plot Area (ha):</b> {row.get('plot_area', 'N/A'):.2f}<br>
            <b>Productivity:</b> {row.get('main_crop_productivity', 'N/A'):.2f}
            """
            iframe = folium.IFrame(popup_html, width=250, height=150)
            popup = folium.Popup(iframe)
            
            folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=4,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                tooltip=f"Farmer ID: {row.get('A3_Farmer_ID', 'N/A')}",
                popup=popup
            ).add_to(marker_group)
            
        # Add layer control to toggle layers on and off
        folium.LayerControl().add_to(m)

        # Display the map in Streamlit
        st_folium(m, width='100%')

    with list_col:
        education_level_names = {
                'none': 'None',
                'primary_school': 'Primary',
                'secondary_school': 'Secondary',
                'tertiary_school': 'Tertiary'
            }
        st.plotly_chart(create_pie_chart(
                filtered_df, 
                "A6_Last_education_level", 
                "Education Level",
                name_map=education_level_names
            ), use_container_width=False)
        
        st.markdown("**Household List**")
        
        # Use an expander to make the list collapsible and save space
        with st.expander(f"Show {len(filtered_df)} households", expanded=True):
            for _, row in filtered_df.iterrows():
                dot_color = 'red' if row['in_protected_area'] else 'green'
                st.markdown(
                    f"<div style='display: flex; align-items: center; margin-bottom: 5px;'>"
                    f"<span style='height: 10px; width: 10px; background-color: {dot_color}; border-radius: 50%; display: inline-block; margin-right: 8px;'></span>"
                    f"<div><b>{row['A1_Producer_farmer_name_first_name']}</b> (ID: {row['A3_Farmer_ID']})<br>"
                    f"<small>Group: {row['A13_Farmer_group_cooperative']}</small>"
                    f"</div></div>",
                    unsafe_allow_html=True
                )

    with alert_col:
        gender_names = {
                'male': 'Male',
                'female': 'Female'
            }
        st.plotly_chart(create_pie_chart(
                filtered_df, "A4_Gender", "Farmer Gender",
                name_map=gender_names
            ), use_container_width=False)
        
        st.markdown("**⚠️ Alert 1: Protected Areas**")
        protected_alerts_df = filtered_df[filtered_df['in_protected_area']]
        
        if protected_alerts_df.empty:
            st.info("No survey points found in protected areas for the selected group(s).")
        else:
            for _, row in protected_alerts_df.iterrows():
                st.error(f"Farmer ID {row['A3_Farmer_ID']} is in a protected area.")

        st.markdown("**🚨 Alert 2: Protected Areas**")
        protected_alerts_df = filtered_df[filtered_df['in_protected_area']]
        
        if protected_alerts_df.empty:
            st.info("No survey points found in protected areas for the selected group(s).")
        else:
            for _, row in protected_alerts_df.iterrows():
                st.error(f"Farmer ID {row['A3_Farmer_ID']} is in a protected area.")

        st.markdown("---")

with tabs[1]:
    st.subheader("About ReClimaTech")
    st.text("At ReClimaTech we connect nature, communities, and businesses to foster sustainable growth through nature-based solutions with tailored and tech-driven consulting & advisory.")

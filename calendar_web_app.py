import streamlit as st
from datetime import time as dtime, timedelta
from CalendarScheduler import get_busy_times, find_free_windows
from dateutil import tz
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
import time
import os

st.set_page_config(page_title="Calendar Scheduler", layout="centered")
st.title("📅 Personal Calendar Availability Checker")

# Initialize session state for service
if 'service' not in st.session_state:
    st.session_state.service = None

# Cache the service object
@st.cache_resource
def get_calendar_service():
    try:
        # Get credentials from Streamlit secrets
        credentials_dict = {
            "type": st.secrets["google"]["type"],
            "project_id": st.secrets["google"]["project_id"],
            "private_key_id": st.secrets["google"]["private_key_id"],
            "private_key": st.secrets["google"]["private_key"],
            "client_email": st.secrets["google"]["client_email"],
            "client_id": st.secrets["google"]["client_id"],
            "auth_uri": st.secrets["google"]["auth_uri"],
            "token_uri": st.secrets["google"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["google"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["google"]["client_x509_cert_url"]
        }
        
        # Create credentials
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/calendar.readonly']
        )
        
        # Create service
        service = build('calendar', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"Error creating calendar service: {str(e)}")
        return None

# Cache timezone list
@st.cache_data
def get_timezone_list():
    return list(pytz.all_timezones)

# --- Timezone selector ---
timezones = get_timezone_list()
default_tz = "US/Eastern"
timezone_label = st.selectbox("Choose your time zone:", options=[default_tz] + [tz for tz in timezones if tz != default_tz])
local_tz = pytz.timezone(timezone_label)

# --- Work hours ---
col1, col2 = st.columns(2)
with col1:
    start_time = st.time_input("Workday starts at:", dtime(9, 0))
with col2:
    end_time = st.time_input("Workday ends at:", dtime(17, 0))

# --- Meeting and buffer preferences ---
min_minutes = st.slider("Minimum meeting length (minutes):", 15, 120, 30, step=5)
buffer_minutes = st.slider("Buffer before and after events (minutes):", 0, 60, 15, step=5)

# --- Initialize service ---
if st.session_state.service is None:
    st.session_state.service = get_calendar_service()

# --- Trigger scheduler ---
if st.session_state.service:
    if st.button("Find My Free Time"):
        with st.spinner("Checking your calendar..."):
            try:
                total_start = time.time()
                
                # Get busy times
                busy_start = time.time()
                busy_blocks = get_busy_times(st.session_state.service, local_tz, buffer_minutes)
                st.write(f"⏱️ Getting busy times took: {time.time() - busy_start:.2f} seconds")
                
                # Find free windows
                free_start = time.time()
                free_windows = find_free_windows(busy_blocks, local_tz, start_time, end_time, min_minutes)
                st.write(f"⏱️ Finding free windows took: {time.time() - free_start:.2f} seconds")
                
                st.write(f"⏱️ Total operation took: {time.time() - total_start:.2f} seconds")

                if not free_windows:
                    st.warning("No free time blocks found with the selected settings.")
                else:
                    st.success("✅ Here are your available meeting times:")
                    for day, blocks in free_windows:
                        st.subheader(day.strftime("%A, %B %d"))
                        for start, end in blocks:
                            st.write(f"{start.strftime('%-I:%M %p')} to {end.strftime('%-I:%M %p')}")
            except Exception as e:
                st.error(f"An error occurred: {e}")
else:
    st.error("Calendar service not initialized. Please check your credentials.")


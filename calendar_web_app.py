import streamlit as st
from datetime import time as dtime, timedelta
from CalendarScheduler import get_busy_times, find_free_windows
from dateutil import tz
import pytz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json
import time
import os

st.set_page_config(page_title="Calendar Scheduler", layout="centered")
st.title("📅 Personal Calendar Availability Checker")

# Initialize session state for credentials
if 'creds' not in st.session_state:
    st.session_state.creds = None

# Cache the service object
@st.cache_resource
def get_calendar_service():
    if st.session_state.creds and st.session_state.creds.valid:
        return build('calendar', 'v3', credentials=st.session_state.creds)
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

# --- Authentication ---
if not st.session_state.creds or not st.session_state.creds.valid:
    st.info("Please authenticate with Google Calendar to continue.")
    if st.button("Authenticate"):
        secrets = st.secrets["google"]
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": secrets.client_id,
                    "project_id": secrets.project_id,
                    "auth_uri": secrets.auth_uri,
                    "token_uri": secrets.token_uri,
                    "auth_provider_x509_cert_url": secrets.auth_provider_x509_cert_url,
                    "client_secret": secrets.client_secret,
                    "redirect_uris": secrets.redirect_uris
                }
            },
            ['https://www.googleapis.com/auth/calendar.readonly']
        )
        st.session_state.creds = flow.run_local_server(port=0)
        st.experimental_rerun()

# --- Trigger scheduler ---
if st.session_state.creds and st.session_state.creds.valid:
    if st.button("Find My Free Time"):
        with st.spinner("Checking your calendar..."):
            try:
                total_start = time.time()
                
                # Get calendar service
                service_start = time.time()
                service = get_calendar_service()
                st.write(f"⏱️ Getting calendar service took: {time.time() - service_start:.2f} seconds")
                
                # Get busy times
                busy_start = time.time()
                busy_blocks = get_busy_times(service, local_tz, buffer_minutes)
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



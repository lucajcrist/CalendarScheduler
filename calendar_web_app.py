import streamlit as st
from datetime import time as dtime, timedelta
from CalendarScheduler import get_user_preferences, authenticate, get_busy_times, find_free_windows, print_schedule
from dateutil import tz
import pytz

st.set_page_config(page_title="Calendar Scheduler", layout="centered")
st.title("📅 Personal Calendar Availability Checker")

# --- Timezone selector ---
timezones = list(pytz.all_timezones)
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

# --- Trigger scheduler ---
if st.button("Find My Free Time"):
    with st.spinner("Checking your calendar..."):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            import json
            import os

            secrets = st.secrets["google"]
            credentials_info = {
                "installed": {
                    "client_id": secrets.client_id,
                    "project_id": secrets.project_id,
                    "auth_uri": secrets.auth_uri,
                    "token_uri": secrets.token_uri,
                    "auth_provider_x509_cert_url": secrets.auth_provider_x509_cert_url,
                    "client_secret": secrets.client_secret,
                    "redirect_uris": secrets.redirect_uris
                }
            }
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
            flow = InstalledAppFlow.from_client_config(credentials_info, ['https://www.googleapis.com/auth/calendar.readonly'])
            creds = flow.run_local_server(open_browser=False, port=8501)

            service = build('calendar', 'v3', credentials=creds)
            busy_blocks = get_busy_times(service, local_tz, buffer_minutes)
            free_windows = find_free_windows(busy_blocks, local_tz, start_time, end_time, min_minutes)

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

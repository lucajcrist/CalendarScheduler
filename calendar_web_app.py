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

# --- Pre-load Google Credentials ---
    st.success("🔐 Successfully signed in to Google Calendar!")
else:
    creds = st.session_state.creds

service = build('calendar', 'v3', credentials=creds)
st.info("✅ Ready to fetch your calendar. Click the button below.")
    st.success("🔐 Successfully signed in to Google Calendar!")
else:
    creds = st.session_state.creds

service = build('calendar', 'v3', credentials=creds)

# --- Trigger scheduler ---
if st.button("Find My Free Time"):
    with st.spinner("Checking your calendar..."):
        try:
            if "creds" not in st.session_state:
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
                creds = flow.run_local_server(open_browser=False, port=0)
                st.session_state.creds = creds
            else:
                creds = st.session_state.creds

            service = build('calendar', 'v3', credentials=creds)
            if "busy_blocks" not in st.session_state:
                from datetime import datetime
                import time
                now = datetime.now(local_tz)
                start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_week = start_of_week + timedelta(days=5)
                fetch_start = time.time()
                busy_blocks = get_busy_times(service, local_tz, buffer_minutes, start=start_of_week, end=end_of_week)
                fetch_duration = time.time() - fetch_start
                st.session_state.fetch_duration = fetch_duration
                st.session_state.busy_blocks = busy_blocks
            else:
                busy_blocks = st.session_state.busy_blocks
            fetch_duration = st.session_state.fetch_duration
            st.write(f"⏱️ Calendar data fetched in {fetch_duration:.2f} seconds")
            find_start = time.time()
            free_windows = find_free_windows(busy_blocks, local_tz, start_time, end_time, min_minutes)
            find_duration = time.time() - find_start
            st.write(f"⏱️ Free time computation took {find_duration:.2f} seconds")

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


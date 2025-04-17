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
from google.auth.transport.requests import Request

st.set_page_config(page_title="Calendar Scheduler", layout="centered")
st.title("📅 Personal Calendar Availability Checker")

# Initialize session state for service and calendar ID
if 'service' not in st.session_state:
    st.session_state.service = None
if 'calendar_id' not in st.session_state:
    st.session_state.calendar_id = None

# Cache the service object
@st.cache_resource
def get_calendar_service():
    try:
        # Get credentials from Streamlit secrets
        try:
            # Debug: Print available secrets
            st.write("Available secrets:", list(st.secrets.keys()))
            if "google" not in st.secrets:
                st.error("❌ 'google' section not found in secrets.toml")
                return None
                
            # Debug: Print available google secrets
            st.write("Available google secrets:", list(st.secrets["google"].keys()))
            
            # Format private key with proper newlines
            private_key = st.secrets["google"]["private_key"]
            if "\\n" in private_key:
                private_key = private_key.replace("\\n", "\n")
            
            credentials_dict = {
                "type": st.secrets["google"]["type"],
                "project_id": st.secrets["google"]["project_id"],
                "private_key_id": st.secrets["google"]["private_key_id"],
                "private_key": private_key,
                "client_email": st.secrets["google"]["client_email"],
                "client_id": st.secrets["google"]["client_id"],
                "auth_uri": st.secrets["google"]["auth_uri"],
                "token_uri": st.secrets["google"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["google"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["google"]["client_x509_cert_url"]
            }
            
            # Debug: Print credential types
            st.write("Credential types:", {k: type(v) for k, v in credentials_dict.items()})
            
        except Exception as e:
            st.error(f"❌ Error reading credentials from secrets: {str(e)}")
            st.error("Please check that all required fields are present in your secrets.toml file")
            return None
        
        try:
            # Create credentials
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/calendar.readonly']
            )
            
            # Test the credentials
            try:
                credentials.refresh(Request())
                st.write("✅ Credentials are valid")
            except Exception as e:
                st.error(f"❌ Credentials validation failed: {str(e)}")
                return None
                
        except Exception as e:
            st.error(f"❌ Error creating credentials: {str(e)}")
            st.error("Please check that your private key and other credentials are correctly formatted")
            return None
        
        try:
            # Create service
            service = build('calendar', 'v3', credentials=credentials)
            
            # Test the service
            try:
                service.calendars().get(calendarId='primary').execute()
                st.write("✅ Calendar service is working")
            except Exception as e:
                st.error(f"❌ Calendar service test failed: {str(e)}")
                return None
                
            return service
        except Exception as e:
            st.error(f"❌ Error building calendar service: {str(e)}")
            st.error("Please check that the Calendar API is enabled in your Google Cloud project")
            return None
            
    except Exception as e:
        st.error(f"❌ Unexpected error initializing calendar service: {str(e)}")
        return None

# Initialize service
if st.session_state.service is None:
    st.write("Initializing calendar service...")
    st.session_state.service = get_calendar_service()
    if st.session_state.service is None:
        st.error("Failed to initialize calendar service. Please check the error messages above.")
        st.stop()

# Get calendar ID if not set
if st.session_state.service and not st.session_state.calendar_id:
    st.write("Please enter your calendar ID (usually your email address):")
    user_calendar_id = st.text_input("Calendar ID")
    
    if user_calendar_id:
        try:
            calendar = st.session_state.service.calendars().get(calendarId=user_calendar_id).execute()
            st.write(f"✅ Successfully connected to calendar: {calendar['summary']}")
            st.session_state.calendar_id = user_calendar_id
            st.rerun()
        except Exception as e:
            st.error(f"❌ Could not access your calendar: {str(e)}")
            st.info("Make sure you've shared your calendar with the service account.")

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

# --- Trigger scheduler ---
if st.session_state.service and st.session_state.calendar_id:
    if st.button("Find My Free Time"):
        with st.spinner("Checking your calendar..."):
            try:
                total_start = time.time()
                
                # Get busy times
                busy_start = time.time()
                busy_blocks = get_busy_times(st.session_state.service, st.session_state.calendar_id, local_tz, buffer_minutes)
                st.write(f"⏱️ Getting busy times took: {time.time() - busy_start:.2f} seconds")
                st.write(f"Found {len(busy_blocks)} busy blocks")
                
                if len(busy_blocks) == 0:
                    st.warning("No busy blocks found. Make sure:")
                    st.write("1. Your calendar is shared with the service account")
                    st.write("2. You have events in your calendar")
                    st.write("3. The service account has proper permissions")
                
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
                st.error("Make sure you've shared your calendar with the service account email: " + st.secrets["google"]["client_email"])
else:
    st.error("Calendar service not initialized. Please check your credentials.")


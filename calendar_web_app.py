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
from google.auth.transport.requests import Request

st.set_page_config(page_title="Calendar Scheduler", layout="centered")

# Initialize session state
if 'creds' not in st.session_state:
    st.session_state.creds = None
if 'calendar_id' not in st.session_state:
    st.session_state.calendar_id = None
if 'show_tutorial' not in st.session_state:
    st.session_state.show_tutorial = True

# OAuth scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_credentials():
    """Get valid user credentials from storage or prompt user to log in."""
    if st.session_state.creds and st.session_state.creds.valid:
        return st.session_state.creds
    
    # Load client secrets
    try:
        with open('credentials.json', 'r') as token:
            client_config = json.load(token)
    except Exception as e:
        st.error("❌ Error loading credentials file. Please check that credentials.json exists.")
        return None

    # Create flow
    flow = InstalledAppFlow.from_client_config(
        client_config,
        SCOPES,
        redirect_uri='http://localhost:8501'
    )
    
    # Get credentials
    try:
        st.session_state.creds = flow.run_local_server(port=8501)
        return st.session_state.creds
    except Exception as e:
        st.error(f"❌ Error during authentication: {str(e)}")
        return None

# Add subtle tutorial button (only show when tutorial is not visible)
if not st.session_state.show_tutorial:
    if st.button("Show Setup Instructions", type="secondary"):
        st.session_state.show_tutorial = True
        st.rerun()

# Show tutorial if it's the first time
if st.session_state.show_tutorial:
    st.markdown("""
    ## Welcome to Calendar Scheduler
    
    This app helps you share your available meeting times with others. To get started, you'll need to sign in with your Google account.
    
    ### How it Works
    
    1. Click the "Sign in with Google" button below
    2. Choose your Google account
    3. Grant calendar access when prompted
    4. Enter your work hours and preferences
    5. Click "Find My Free Time" to see your availability
    
    That's it! No complex setup required.
    """)
    
    if st.button("Sign in with Google"):
        st.session_state.show_tutorial = False
        st.rerun()
    st.stop()

# Main app interface
st.title("📅 Personal Calendar Availability Checker")

# Get credentials
creds = get_credentials()
if not creds:
    st.error("Please sign in with Google to continue.")
    if st.button("Show Setup Instructions Again"):
        st.session_state.show_tutorial = True
        st.rerun()
    st.stop()

# Build service
service = build('calendar', 'v3', credentials=creds)

# Get user's primary calendar
try:
    calendar = service.calendars().get(calendarId='primary').execute()
    st.session_state.calendar_id = 'primary'
    st.write(f"✅ Connected to your calendar: {calendar['summary']}")
except Exception as e:
    st.error(f"❌ Could not access your calendar: {str(e)}")
    st.stop()

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
if st.button("Find My Free Time"):
    with st.spinner("Checking your calendar..."):
        try:
            total_start = time.time()
            
            # Get busy times for both weeks
            busy_blocks = get_busy_times(service, st.session_state.calendar_id, local_tz, buffer_minutes, show_next_week=True)
            
            if len(busy_blocks) == 0:
                st.warning("No busy blocks found. Make sure you have events in your calendar.")
            
            # Find free windows
            free_windows = find_free_windows(busy_blocks, local_tz, start_time, end_time, min_minutes)

            if not free_windows:
                st.warning("No free time blocks found with the selected settings.")
            else:
                st.success("✅ Here are your available meeting times:")
                # Create a text area with formatted output
                formatted_output = []
                for day, blocks in free_windows:
                    # Format date with ordinal (e.g., 16th)
                    day_num = day.day
                    suffix = 'th' if 11 <= day_num <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day_num % 10, 'th')
                    date_str = f"{day.strftime('%B %d')}{suffix}"
                    
                    # Format time blocks
                    time_blocks = []
                    for start, end in blocks:
                        # Format times in lowercase with 'am/pm'
                        start_str = start.strftime('%-I:%M%p').lower()
                        end_str = end.strftime('%-I:%M%p').lower()
                        time_blocks.append(f"{start_str} to {end_str}")
                    
                    # Join date and times
                    formatted_output.append(f"• {date_str}: {', '.join(time_blocks)}")
                
                # Join with newlines and display in a text area
                email_text = "\n".join(formatted_output)
                st.text_area("Copy and paste these times into your email:", 
                           value=email_text,
                           height=300)
        except Exception as e:
            st.error(f"An error occurred: {e}")
            if st.button("Show Setup Instructions Again"):
                st.session_state.show_tutorial = True
                st.rerun()


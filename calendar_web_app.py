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

# OAuth scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_credentials():
    """Gets valid user credentials from storage or initiates OAuth flow."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Create credentials from Streamlit secrets
            client_config = {
                "installed": {
                    "client_id": st.secrets["google"]["client_id"],
                    "project_id": st.secrets["google"]["project_id"],
                    "auth_uri": st.secrets["google"]["auth_uri"],
                    "token_uri": st.secrets["google"]["token_uri"],
                    "auth_provider_x509_cert_url": st.secrets["google"]["auth_provider_x509_cert_url"],
                    "client_secret": st.secrets["google"]["client_secret"],
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            
            # Use device flow
            flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            
            st.markdown("""
            ### Authorization Steps:
            1. Click the link below to open the authorization page
            2. Sign in with your Google account
            3. Grant calendar access
            4. Copy the authorization code
            5. Paste it in the text box below
            """)
            
            st.markdown(f'[Click here to authorize]({auth_url})')
            code = st.text_input('Enter the authorization code:')
            
            if code:
                try:
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                    # Save the credentials for the next run
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    st.error(f"Error during authentication: {str(e)}")
                    st.stop()
            else:
                st.stop()
    return creds

st.set_page_config(page_title="Calendar Scheduler", layout="centered")

# Initialize session state
if 'creds' not in st.session_state:
    st.session_state.creds = None
if 'calendar_id' not in st.session_state:
    st.session_state.calendar_id = None
if 'show_tutorial' not in st.session_state:
    st.session_state.show_tutorial = True
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def logout():
    """Clear authentication state and credentials."""
    st.session_state.authenticated = False
    st.session_state.show_tutorial = True
    st.session_state.creds = None
    st.session_state.calendar_id = None
    st.session_state.service = None
    st.session_state.trigger_rerun = True  # Add flag to trigger rerun
    if os.path.exists('token.json'):
        os.remove('token.json')

# Add subtle logout button in top-right corner if authenticated
if st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col3:
        st.button("🔒 Logout", on_click=logout, type="secondary", use_container_width=True)

# Check if we need to rerun after logout
if st.session_state.get('trigger_rerun', False):
    st.session_state.trigger_rerun = False
    st.rerun()

# Add subtle tutorial button (only show when tutorial is not visible)
if not st.session_state.show_tutorial and not st.session_state.authenticated:
    if st.button("Show Setup Instructions", type="secondary"):
        st.session_state.show_tutorial = True
        st.rerun()

# Show tutorial if it's the first time and not authenticated
if st.session_state.show_tutorial and not st.session_state.authenticated:
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
        try:
            creds = get_credentials()
            if creds:
                service = build('calendar', 'v3', credentials=creds)
                st.session_state['service'] = service
                st.session_state['calendar_id'] = 'primary'  # Use primary calendar
                st.session_state.authenticated = True
                st.session_state.show_tutorial = False
                st.success("Successfully connected to your calendar!")
                st.rerun()
        except Exception as e:
            st.error(f"Error connecting to Google Calendar: {str(e)}")
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

import streamlit as st
from datetime import time as dtime, timedelta, datetime
import time as time_module
from CalendarScheduler import get_busy_times, find_free_windows
from dateutil import tz
import pytz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json
import os
from google.auth.transport.requests import Request
import pickle
import hashlib

# OAuth scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# User data directory
USER_DATA_DIR = 'user_data'
os.makedirs(USER_DATA_DIR, exist_ok=True)

def get_user_id(email):
    """Generate a unique user ID from email."""
    return hashlib.md5(email.encode()).hexdigest()

def get_user_credentials_path(user_id):
    """Get the path to store user credentials."""
    return os.path.join(USER_DATA_DIR, f'{user_id}_token.pickle')

def get_credentials(user_id):
    """Gets valid user credentials from storage or initiates OAuth flow."""
    creds = None
    token_path = get_user_credentials_path(user_id)
    
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None
    return creds

def save_credentials(user_id, creds):
    """Save user credentials to file."""
    token_path = get_user_credentials_path(user_id)
    with open(token_path, 'wb') as token:
        pickle.dump(creds, token)

def delete_credentials(user_id):
    """Delete user credentials."""
    token_path = get_user_credentials_path(user_id)
    if os.path.exists(token_path):
        os.remove(token_path)

st.set_page_config(page_title="Calendar Scheduler", layout="centered")

# Initialize session state
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'creds' not in st.session_state:
    st.session_state.creds = None
if 'calendar_id' not in st.session_state:
    st.session_state.calendar_id = None
if 'show_tutorial' not in st.session_state:
    st.session_state.show_tutorial = True
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'service' not in st.session_state:
    st.session_state.service = None
if 'trigger_rerun' not in st.session_state:
    st.session_state.trigger_rerun = False

def logout():
    """Clear authentication state and credentials."""
    st.session_state.authenticated = False
    st.session_state.show_tutorial = True
    st.session_state.creds = None
    st.session_state.calendar_id = None
    st.session_state.service = None
    st.session_state.user_id = None
    st.session_state.user_email = None
    st.session_state.trigger_rerun = True

# Check if we need to rerun after logout
if st.session_state.get('trigger_rerun', False):
    st.session_state.trigger_rerun = False
    st.rerun()

# Add subtle logout button in top-right corner if authenticated
if st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col3:
        st.button("🔒 Logout", on_click=logout, type="secondary", use_container_width=True)

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
    4. You will be redirected back to the app automatically
    5. Enter your work hours and preferences
    6. Click "Find My Free Time" to see your availability
    
    That's it! No complex setup required.
    """)
    
    if st.button("Sign in with Google"):
        try:
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
            3. You may see a warning about the app not being verified - this is normal for testing
            4. Click "Advanced" and then "Go to Calendar Scheduler (unsafe)"
            5. Grant calendar access when prompted
            6. Copy the authorization code
            7. Paste it in the text box below
            """)
            
            st.markdown(f'[Click here to authorize]({auth_url})')
            
            # Get the authorization code from user input
            code = st.text_input('Enter the authorization code:')
            if code:
                try:
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                    
                    # Get user's email from the credentials
                    service = build('oauth2', 'v2', credentials=creds)
                    user_info = service.userinfo().get().execute()
                    user_email = user_info['email']
                    user_id = get_user_id(user_email)
                    
                    # Save credentials for this user
                    save_credentials(user_id, creds)
                    
                    # Update session state
                    st.session_state.user_id = user_id
                    st.session_state.user_email = user_email
                    st.session_state.creds = creds
                    st.session_state.authenticated = True
                    st.session_state.show_tutorial = False
                    st.session_state.service = build('calendar', 'v3', credentials=creds)
                    st.session_state.calendar_id = 'primary'
                    st.success(f"Successfully connected to {user_email}'s calendar!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error during authentication: {str(e)}")
                    if "access_denied" in str(e):
                        st.error("""
                        The app is currently in testing mode. To use it:
                        1. Go to the Google Cloud Console
                        2. Navigate to OAuth consent screen
                        3. Add your email as a test user
                        4. Try signing in again
                        """)
                    st.stop()
            else:
                st.stop()
        except Exception as e:
            st.error(f"Error initializing authentication: {str(e)}")
            st.stop()
    st.stop()

# Main app interface
st.title("📅 Personal Calendar Availability Checker")

# Get credentials and initialize service
if not st.session_state.authenticated:
    # Try to load saved credentials
    if st.session_state.user_id:
        creds = get_credentials(st.session_state.user_id)
        if creds:
            st.session_state.creds = creds
            st.session_state.authenticated = True
            st.session_state.service = build('calendar', 'v3', credentials=creds)
            st.session_state.calendar_id = 'primary'
            st.rerun()
        else:
            st.error("Please sign in with Google to continue.")
            if st.button("Show Setup Instructions Again"):
                st.session_state.show_tutorial = True
                st.rerun()
            st.stop()
    else:
        st.error("Please sign in with Google to continue.")
        if st.button("Show Setup Instructions Again"):
            st.session_state.show_tutorial = True
            st.rerun()
        st.stop()

# Ensure service is available
if not st.session_state.service:
    st.error("Service not initialized. Please sign in again.")
    st.session_state.authenticated = False
    st.rerun()

# Get user's primary calendar
try:
    calendar = st.session_state.service.calendars().get(calendarId='primary').execute()
    st.write(f"✅ Connected to {st.session_state.user_email}'s calendar: {calendar['summary']}")
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

# --- Date range selection ---
st.subheader("Select Date Range")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("From:", 
                              value=datetime.now().date(),
                              min_value=datetime.now().date(),
                              max_value=datetime.now().date() + timedelta(days=90))
with col2:
    end_date = st.date_input("To:", 
                            value=datetime.now().date() + timedelta(days=14),
                            min_value=start_date,
                            max_value=datetime.now().date() + timedelta(days=90))

# Display selected date range
st.write(f"Showing availability from **{start_date.strftime('%A, %B %d, %Y')}** to **{end_date.strftime('%A, %B %d, %Y')}**")

# --- Work hours ---
st.subheader("Work Hours")
col1, col2 = st.columns(2)
with col1:
    start_time = st.time_input("Workday starts at:", dtime(9, 0))
with col2:
    end_time = st.time_input("Workday ends at:", dtime(17, 0))

# --- Meeting and buffer preferences ---
st.subheader("Meeting Preferences")
min_minutes = st.slider("Minimum meeting length (minutes):", 15, 120, 30, step=5)
buffer_minutes = st.slider("Buffer before and after events (minutes):", 0, 60, 15, step=5)

# --- Trigger scheduler ---
if st.button("Find My Free Time"):
    with st.spinner("Checking your calendar..."):
        try:
            total_start = time_module.time()
            
            # Get busy times for the selected date range
            busy_blocks = get_busy_times(st.session_state.service, st.session_state.calendar_id, local_tz, buffer_minutes, 
                                       start_date=start_date, end_date=end_date)
            
            if len(busy_blocks) == 0:
                st.warning("No busy blocks found. Make sure you have events in your calendar.")
            
            # Find free windows
            free_windows = find_free_windows(busy_blocks, local_tz, start_time, end_time, min_minutes)

            if not free_windows:
                st.warning("No free time blocks found with the selected settings.")
            else:
                st.success(f"✅ Available times from {start_date.strftime('%A, %B %d')} to {end_date.strftime('%A, %B %d')}:")
                # Create a text area with formatted output
                formatted_output = []
                for day, blocks in free_windows:
                    # Format date with weekday and ordinal (e.g., Friday, April 18th)
                    weekday = day.strftime('%A')
                    month = day.strftime('%B')
                    day_num = day.day
                    suffix = 'th' if 11 <= day_num <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day_num % 10, 'th')
                    date_str = f"{weekday}, {month} {day_num}{suffix}"
                    
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


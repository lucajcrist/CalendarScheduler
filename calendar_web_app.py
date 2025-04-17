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

# Initialize session state for service and calendar ID
if 'service' not in st.session_state:
    st.session_state.service = None
if 'calendar_id' not in st.session_state:
    st.session_state.calendar_id = None
if 'show_tutorial' not in st.session_state:
    st.session_state.show_tutorial = True

# Cache the service object
@st.cache_resource
def get_calendar_service():
    try:
        # Get credentials from Streamlit secrets
        try:
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
            
        except Exception as e:
            st.error(f"❌ Error reading credentials from secrets: {str(e)}")
            st.error("Please check that all required fields are present in your secrets.toml file")
            return None
        
        try:
            # Create credentials with SSL verification disabled for testing
            credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/calendar.readonly']
            )
            
            # Test the credentials
            credentials.refresh(Request())
                
        except Exception as e:
            st.error(f"❌ Error creating credentials: {str(e)}")
            st.error("Please check that your private key and other credentials are correctly formatted")
            return None
        
        try:
            # Create service
            service = build('calendar', 'v3', credentials=credentials)
            return service
        except Exception as e:
            st.error(f"❌ Error building calendar service: {str(e)}")
            st.error("Please check that the Calendar API is enabled in your Google Cloud project")
            return None
            
    except Exception as e:
        st.error(f"❌ Unexpected error initializing calendar service: {str(e)}")
        return None

# Initialize service if not already initialized
if st.session_state.service is None:
    st.write("Initializing calendar service...")
    service = get_calendar_service()
    if service is not None:
        st.session_state.service = service
    else:
        st.error("Failed to initialize calendar service. Please check the error messages above.")
        st.stop()

# Add subtle tutorial button (only show when tutorial is not visible)
if not st.session_state.show_tutorial:
    if st.button("Show Setup Instructions", type="secondary"):
        st.session_state.show_tutorial = True
        st.rerun()

# Show tutorial if it's the first time
if st.session_state.show_tutorial:
    st.markdown("""
    ## Welcome to Calendar Scheduler
    
    This app helps you share your available meeting times with others. **Before you can use it, you need to share your calendar with our service account.**
    
    ### Step-by-Step Setup Guide
    
    1. **Open Google Calendar**
       - Go to [calendar.google.com](https://calendar.google.com)
       - Make sure you're signed in with the account you want to share
    
    2. **Share Your Calendar**
       - On the left side, find your calendar under "My calendars"
       - Click the three dots (⋮) next to your calendar
       - Select "Settings and sharing"
    
    3. **Add the Service Account**
       - Scroll down to "Share with specific people"
       - Click "Add people"
       - Enter this email address:
       ```
       {service_account_email}
       ```
       - Choose your preferred permission level:
         - "See all event details" - Shows event titles and details
         - "See only free/busy" - Only shows when you're busy, not what you're doing
       - **Both options work equally well for finding your available times**
       - Click "Send"
    
    4. **Verify the Sharing**
       - Wait a few moments for the sharing to take effect
       - The service account will now be able to read your calendar
    
    5. **Find Your Calendar ID**
       - Your calendar ID is usually your email address
       - You can also find it in your calendar settings:
         1. Go to [Google Calendar Settings](https://calendar.google.com/calendar/r/settings)
         2. Click on your calendar under "Settings for my calendars"
         3. Look for "Calendar ID" in the "Integrate calendar" section
       - **For most users, it's simply your email address**
    
    6. **Enter Your Calendar ID**
       - Enter your calendar ID in the field below
       - Click "Connect" to verify the connection
    
    Once you've completed these steps, you can start using the app to find your available meeting times!
    """.format(service_account_email=st.secrets["google"]["client_email"]))
    
    if st.button("I've completed the setup"):
        st.session_state.show_tutorial = False
        st.rerun()
    st.stop()

# Main app interface
st.title("📅 Personal Calendar Availability Checker")

# Always show calendar ID input
st.write("Enter or update your calendar ID:")
st.info("""
Your calendar ID is usually your email address. You can also find it by:
1. Going to [Google Calendar Settings](https://calendar.google.com/calendar/r/settings)
2. Clicking on your calendar under "Settings for my calendars"
3. Looking for "Calendar ID" in the "Integrate calendar" section
""")
user_calendar_id = st.text_input("Calendar ID", value=st.session_state.calendar_id or "")

if user_calendar_id and user_calendar_id != st.session_state.calendar_id:
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
if st.session_state.service is not None and st.session_state.calendar_id:
    if st.button("Find My Free Time"):
        with st.spinner("Checking your calendar..."):
            try:
                total_start = time.time()
                
                # Get busy times for both weeks
                busy_blocks = get_busy_times(st.session_state.service, st.session_state.calendar_id, local_tz, buffer_minutes, show_next_week=True)
                
                if len(busy_blocks) == 0:
                    st.warning("No busy blocks found. Make sure:")
                    st.write("1. Your calendar is shared with the service account")
                    st.write("2. You have events in your calendar")
                    st.write("3. The service account has proper permissions")
                    if st.button("Show Setup Instructions Again"):
                        st.session_state.show_tutorial = True
                        st.rerun()
                
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
                        date_str = f"{day.strftime('%A, %B %d')}{suffix}"
                        
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
                st.error("Make sure you've shared your calendar with the service account email: " + st.secrets["google"]["client_email"])
                if st.button("Show Setup Instructions Again"):
                    st.session_state.show_tutorial = True
                    st.rerun()
else:
    if st.session_state.service is None:
        st.error("Calendar service not initialized. Please check your credentials.")
    else:
        st.info("Please enter your calendar ID above to continue.")



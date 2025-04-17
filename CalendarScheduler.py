from __future__ import print_function
import os.path
from datetime import datetime, timedelta, time
from dateutil import parser, tz
import pytz
import calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import time as time_module
import functools

# --- Google Calendar API scope ---
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# --- Timezone alias mapping ---
TIMEZONE_ALIASES = {
    "est": "US/Eastern",
    "eastern": "US/Eastern",
    "edt": "US/Eastern",
    "cst": "US/Central",
    "central": "US/Central",
    "mst": "US/Mountain",
    "mountain": "US/Mountain",
    "pst": "US/Pacific",
    "pacific": "US/Pacific",
    "pt": "US/Pacific",
    "gmt": "Etc/GMT",
    "utc": "UTC"
}

# --- Get timezone from user input ---
def get_timezone_from_input():
    user_input = input("What time zone are you in? (e.g., EST, PST, Eastern): ").strip().lower()
    if user_input in TIMEZONE_ALIASES:
        tz_name = TIMEZONE_ALIASES[user_input]
    else:
        print("Unknown or unsupported timezone. Defaulting to US/Eastern.")
        tz_name = "US/Eastern"
    return pytz.timezone(tz_name)

# --- User preferences setup ---
def get_user_preferences():
    print("📅 Let's set up your personal scheduling preferences.")

    local_tz = get_timezone_from_input()

    def parse_time_input(label):
        time_input = input(f"What time does your workday {label}? (e.g., 6, 7:00, 8:00AM, 7:00PM): ").strip().lower()
        try:
            aliases = {
                "noon": "12:00pm",
                "midnight": "12:00am",
                "half past ": lambda x: f"{x}:30"
            }
            if time_input in aliases:
                time_input = aliases[time_input]
            elif time_input.startswith("half past"):
                hour = time_input.replace("half past", "").strip()
                time_input = f"{hour}:30"
            elif time_input.isdigit() and len(time_input) <= 4:
                time_input = time_input.zfill(4)
                hour = int(time_input[:2])
                minute = int(time_input[2:]) if len(time_input) > 2 else 0
                return time(hour, minute)
            parsed_time = parser.parse(time_input)
            return time(parsed_time.hour, parsed_time.minute)
        except:
            print("Invalid time. Defaulting to 9:00 for start and 17:00 for end.")
            return time(9, 0) if label == "start" else time(17, 0)
        

    start_time = parse_time_input("start")
    end_time = parse_time_input("end")
    event_length = int(input("What's the minimum length (in minutes) for a meeting? "))
    buffer_minutes = int(input("How much buffer time (in minutes) do you want between meetings? "))

    return local_tz, start_time, end_time, event_length, buffer_minutes

# Cache the busy times results
@functools.lru_cache(maxsize=2)  # Increased cache size to handle both this week and next week
def get_busy_times(service, calendar_id, local_tz, buffer_minutes, start_date=None, end_date=None):
    start_time = time_module.time()
    now = datetime.now(local_tz)
    
    # Use provided date range or default to this week and next week
    if start_date is None:
        # Calculate start and end of this week
        this_week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        this_week_end = this_week_start + timedelta(days=7)
        
        # Calculate start and end of next week
        days_until_next_monday = (7 - now.weekday()) % 7
        if days_until_next_monday == 0:  # If today is Monday, add 7 days
            days_until_next_monday = 7
        next_week_start = (now + timedelta(days=days_until_next_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        next_week_end = next_week_start + timedelta(days=7)
        
        # Convert to UTC for API call
        start_utc = this_week_start.astimezone(tz.UTC)
        end_utc = next_week_end.astimezone(tz.UTC)
    else:
        # Use provided date range
        start_dt = datetime.combine(start_date, time(0, 0), tzinfo=local_tz)
        end_dt = datetime.combine(end_date, time(23, 59, 59), tzinfo=local_tz)
        
        # Convert to UTC for API call
        start_utc = start_dt.astimezone(tz.UTC)
        end_utc = end_dt.astimezone(tz.UTC)

    print(f"Local timezone: {local_tz}")
    print(f"Current time in local timezone: {now}")
    print(f"API call time range:")
    print(f"Start in UTC: {start_utc}")
    print(f"End in UTC: {end_utc}")

    # Get events for the time period
    try:
        # First, try to get calendar details to check access level
        try:
            calendar = service.calendars().get(calendarId=calendar_id).execute()
            access_level = calendar.get('accessRole', 'unknown')
            print(f"Calendar access level: {access_level}")
        except Exception as e:
            print(f"Could not get calendar details: {e}")
            access_level = 'unknown'

        # Try to get events with full details first
        try:
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=start_utc.isoformat(),
                timeMax=end_utc.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                maxResults=2500  # Increased from 1000 to 2500
            ).execute()
            events = events_result.get('items', [])
            print(f"Found {len(events)} events with full details")
            
            # Handle pagination if there are more events
            while 'nextPageToken' in events_result:
                events_result = service.events().list(
                    calendarId=calendar_id,
                    timeMin=start_utc.isoformat(),
                    timeMax=end_utc.isoformat(),
                    singleEvents=True,
                    orderBy='startTime',
                    maxResults=2500,
                    pageToken=events_result['nextPageToken']
                ).execute()
                events.extend(events_result.get('items', []))
                print(f"Found additional {len(events_result.get('items', []))} events")
        except Exception as e:
            print(f"Could not get full event details: {e}")
            events = []

        # If no events found with full details, try free/busy
        if not events:
            try:
                freebusy_request = {
                    "timeMin": start_utc.isoformat(),
                    "timeMax": end_utc.isoformat(),
                    "items": [{"id": calendar_id}]
                }
                freebusy_result = service.freebusy().query(body=freebusy_request).execute()
                busy_blocks = freebusy_result.get('calendars', {}).get(calendar_id, {}).get('busy', [])
                print(f"Found {len(busy_blocks)} busy blocks from free/busy")
                
                # Convert free/busy blocks to events format
                events = []
                for block in busy_blocks:
                    events.append({
                        'start': {'dateTime': block['start']},
                        'end': {'dateTime': block['end']},
                        'transparency': 'opaque'  # Mark as busy time
                    })
            except Exception as e:
                print(f"Could not get free/busy information: {e}")
                return tuple()
        
        busy_blocks = []
        buffer = timedelta(minutes=buffer_minutes)

        for event in events:
            # Skip events marked as 'transparent' (free/busy)
            if event.get('transparency') == 'transparent':
                continue
                
            # Skip declined events if we have full access
            if access_level in ['owner', 'writer'] and event.get('attendees'):
                my_response = next((a.get('responseStatus') for a in event['attendees'] 
                                 if a.get('self', False)), None)
                if my_response == 'declined':
                    continue

            # Handle both dateTime and date events
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            if start and end:
                # Convert to datetime if it's a date
                if 'T' not in start:
                    start = f"{start}T00:00:00"
                if 'T' not in end:
                    end = f"{end}T23:59:59"
                
                try:
                    # Parse the datetime string
                    start_dt = parser.isoparse(start)
                    end_dt = parser.isoparse(end)
                    
                    # If the datetime doesn't have timezone info, assume it's in UTC
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=tz.UTC)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=tz.UTC)
                    
                    # Convert to local timezone
                    start_dt = start_dt.astimezone(local_tz)
                    end_dt = end_dt.astimezone(local_tz)
                    
                    # Only print event details if we have full access
                    if access_level in ['owner', 'writer'] and event.get('summary'):
                        print(f"Event: {event.get('summary', 'No title')}")
                        print(f"Original start: {start} -> Local start: {start_dt}")
                        print(f"Original end: {end} -> Local end: {end_dt}")
                    
                    # Add buffer time
                    busy_blocks.append((start_dt - buffer, end_dt + buffer))
                except Exception as e:
                    print(f"Error processing event: {e}")
                    continue

        busy_blocks.sort()
        print(f"Total busy blocks: {len(busy_blocks)}")
        print(f"⏱️ get_busy_times took: {time_module.time() - start_time:.2f} seconds")
        return tuple(busy_blocks)
    except Exception as e:
        print(f"Error fetching events: {e}")
        return tuple()

# --- Merge overlapping busy blocks ---
def merge_blocks(blocks):
    if not blocks:
        return []
    merged = [blocks[0]]
    for start, end in blocks[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged

# Cache the free windows results
@functools.lru_cache(maxsize=2)
def find_free_windows(busy_blocks, local_tz, work_start, work_end, min_minutes):
    start_time = time_module.time()
    free_windows = []
    now = datetime.now(local_tz)
    busy_blocks = list(busy_blocks)  # Convert tuple back to list
    busy_blocks = merge_blocks(busy_blocks)
    min_duration = timedelta(minutes=min_minutes)

    # Get the date range from the busy blocks
    if busy_blocks:
        start_date = min(b.date() for b, _ in busy_blocks)
        end_date = max(_.date() for _, _ in busy_blocks)
    else:
        # If no busy blocks, use today as start date and go 90 days forward
        start_date = now.date()
        end_date = start_date + timedelta(days=90)

    print(f"Processing dates from {start_date} to {end_date}")

    # Process each day in the range
    current_date = start_date
    while current_date <= end_date:
        # Skip weekends
        if current_date.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
            current_date += timedelta(days=1)
            continue

        day = current_date
        start = datetime.combine(day, work_start, tzinfo=local_tz)
        end = datetime.combine(day, work_end, tzinfo=local_tz)
        
        print(f"Processing day: {day.strftime('%A, %Y-%m-%d')}")
        
        # Skip past days
        if day < now.date():
            current_date += timedelta(days=1)
            continue
            
        # For today, adjust start time to current time if it's later than work start
        if day == now.date():
            start = max(start, now)
            # If we're past work hours for today, skip to next day
            if start >= end:
                current_date += timedelta(days=1)
                continue
                
        current = start
        day_windows = []

        # Filter busy blocks for this day
        day_busy_blocks = [(s, e) for s, e in busy_blocks if s.date() == day or e.date() == day]
        
        # Sort busy blocks by start time
        day_busy_blocks.sort(key=lambda x: x[0])
        
        # If no busy blocks for the day, add the entire workday as a free window
        if not day_busy_blocks:
            if (end - start) >= min_duration:
                day_windows.append((start, end))
        else:
            # Process each busy block
            for b_start, b_end in day_busy_blocks:
                # Skip blocks that don't overlap with work hours
                if b_end <= start or b_start >= end:
                    continue
                    
                # Adjust block times to work hours
                b_start = max(b_start, start)
                b_end = min(b_end, end)
                
                # If there's a gap before this block
                if b_start > current:
                    free_start = current
                    free_end = b_start
                    # Only add if it's long enough and within work hours
                    if (free_end - free_start) >= min_duration:
                        day_windows.append((free_start, free_end))
                
                current = max(current, b_end)

            # Check for free time after the last busy block
            if current < end:
                free_start = current
                free_end = end
                if (free_end - free_start) >= min_duration:
                    day_windows.append((free_start, free_end))

        # Filter out any invalid windows
        valid_windows = []
        for window_start, window_end in day_windows:
            # Skip zero-duration windows
            if window_start >= window_end:
                continue
                
            # Skip windows that are too short
            if (window_end - window_start) < min_duration:
                continue
                
            # Ensure windows are within work hours
            window_start = max(window_start, start)
            window_end = min(window_end, end)
            
            # Skip if window is now too short after adjustment
            if (window_end - window_start) < min_duration:
                continue
                
            # Skip past time slots
            if window_start < now:
                continue
                
            # Round times to nearest 5 minutes
            window_start = window_start.replace(minute=(window_start.minute // 5) * 5)
            window_end = window_end.replace(minute=(window_end.minute // 5) * 5)
            
            valid_windows.append((window_start, window_end))

        if valid_windows:
            free_windows.append((day, tuple(valid_windows)))
        
        current_date += timedelta(days=1)

    print(f"⏱️ find_free_windows took: {time_module.time() - start_time:.2f} seconds")
    return tuple(free_windows)

# --- Format date and time strings ---
def format_date(date_obj):
    weekday = calendar.day_name[date_obj.weekday()]
    month = calendar.month_name[date_obj.month]
    day = date_obj.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{weekday}, {month} {day}{suffix}"

def format_time(dt):
    return dt.strftime("%-I:%M%p").lower().replace(":00", "")

# --- Print final schedule ---
def print_schedule(free_windows, min_minutes):
    print(f"\n✅ Free time blocks (≥{min_minutes} min, with custom buffer):\n")
    for day, windows in free_windows:
        date_str = format_date(day)
        for start, end in windows:
            print(f"{date_str}: {format_time(start)} to {format_time(end)}")

# --- Main execution ---
def main():
    local_tz, work_start, work_end, min_minutes, buffer_minutes = get_user_preferences()
    # Remove the creds reference since we're using service account
    print("This script is meant to be imported, not run directly.")
    print("Please use the Streamlit web app instead.")

if __name__ == '__main__':
    main()

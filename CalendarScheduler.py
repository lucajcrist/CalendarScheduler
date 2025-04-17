from __future__ import print_function
import os.path
from datetime import datetime, timedelta, time
from dateutil import parser, tz
import pytz
import calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import time
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
@functools.lru_cache(maxsize=1)
def get_busy_times(service, local_tz, buffer_minutes):
    start_time = time.time()
    now = datetime.now(local_tz)
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)

    print(f"Local timezone: {local_tz}")
    print(f"Current time in local timezone: {now}")
    print(f"Start of week in local timezone: {start_of_week}")
    print(f"End of week in local timezone: {end_of_week}")

    # Convert to UTC for API call
    start_utc = start_of_week.astimezone(tz.UTC)
    end_utc = end_of_week.astimezone(tz.UTC)

    print(f"Start of week in UTC: {start_utc}")
    print(f"End of week in UTC: {end_utc}")

    # Get events for the week
    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_utc.isoformat(),
            timeMax=end_utc.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=1000
        ).execute()

        events = events_result.get('items', [])
        print(f"Found {len(events)} events in the calendar")
        
        busy_blocks = []
        buffer = timedelta(minutes=buffer_minutes)

        for event in events:
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
                    
                    print(f"Event: {event.get('summary', 'No title')}")
                    print(f"Original start: {start} -> Local start: {start_dt}")
                    print(f"Original end: {end} -> Local end: {end_dt}")
                    
                    busy_blocks.append((start_dt - buffer, end_dt + buffer))
                except Exception as e:
                    print(f"Error processing event: {e}")
                    continue

        busy_blocks.sort()
        print(f"Total busy blocks: {len(busy_blocks)}")
        print(f"⏱️ get_busy_times took: {time.time() - start_time:.2f} seconds")
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
@functools.lru_cache(maxsize=1)
def find_free_windows(busy_blocks, local_tz, work_start, work_end, min_minutes):
    start_time = time.time()
    free_windows = []
    now = datetime.now(local_tz)
    busy_blocks = list(busy_blocks)  # Convert tuple back to list
    busy_blocks = merge_blocks(busy_blocks)
    min_duration = timedelta(minutes=min_minutes)

    # Process one day at a time
    for day_offset in range(5):  # Mon to Fri
        day = (now + timedelta(days=day_offset - now.weekday())).date()
        start = datetime.combine(day, work_start, tzinfo=local_tz)
        end = datetime.combine(day, work_end, tzinfo=local_tz)
        current = start
        day_windows = []

        # Filter busy blocks for this day
        day_busy_blocks = [(s, e) for s, e in busy_blocks if s.date() == day or e.date() == day]
        
        for b_start, b_end in day_busy_blocks:
            if b_end <= start or b_start >= end:
                continue
            b_start = max(b_start, start)
            b_end = min(b_end, end)
            if b_start > current:
                free_start = current
                free_end = b_start
                if (free_end - free_start) >= min_duration:
                    day_windows.append((free_start, free_end))
            current = max(current, b_end)

        if current < end:
            free_start = current
            free_end = end
            if (free_end - free_start) >= min_duration:
                day_windows.append((free_start, free_end))

        if day_windows:
            free_windows.append((day, tuple(day_windows)))  # Convert day_windows to tuple

    print(f"⏱️ find_free_windows took: {time.time() - start_time:.2f} seconds")
    return tuple(free_windows)  # Convert list to tuple for caching

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
    service = build('calendar', 'v3', credentials=creds)
    busy_blocks = get_busy_times(service, local_tz, buffer_minutes=buffer_minutes)
    free_windows = find_free_windows(busy_blocks, local_tz, work_start, work_end, min_minutes)
    print_schedule(free_windows, min_minutes)

if __name__ == '__main__':
    main()

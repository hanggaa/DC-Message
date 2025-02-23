import json
import sys
import random
import time
import threading
import re
from datetime import datetime
from http.client import HTTPSConnection
from typing import Dict, List
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CREDENTIALS_FILE = "credentials.json"  # Google Sheets API credentials

def extract_sheet_id_from_url(url: str) -> str:
    """Extract the Google Sheets ID from a URL"""
    # Pattern for different Google Sheets URL formats
    patterns = [
        r"/spreadsheets/d/([a-zA-Z0-9-_]+)",  # Standard URL
        r"spreadsheets/d/([a-zA-Z0-9-_]+)",   # Modified URL
        r"^([a-zA-Z0-9-_]+)$"                 # Direct ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError("Invalid Google Sheets URL format")

def get_sheet_url_from_user() -> str:
    """Get and validate the Google Sheets URL from user input"""
    while True:
        print("\nPlease enter your Google Sheets URL or ID")
        print("Make sure the sheet is publicly accessible or shared with the service account email")
        url = input("URL: ").strip()
        
        try:
            sheet_id = extract_sheet_id_from_url(url)
            return sheet_id
        except ValueError:
            print("Invalid URL format. Please try again.")
            continue

class ChannelConfig:
    def __init__(self, url: str, id: str, alias: str, messages: List[str], delay: float):
        self.url = url
        self.id = id
        self.alias = alias
        self.messages = messages
        self.delay = delay

    @classmethod
    def from_sheet_row(cls, row_data: List[str]):
        messages = [msg.strip() for msg in row_data[6].split(',') if msg.strip()]
        return cls(
            url=row_data[3],
            id=row_data[4],
            alias=row_data[5] if row_data[5] else row_data[4],
            messages=messages,
            delay=float(row_data[7])
        )

class UserConfig:
    def __init__(self, user_id: str, token: str, channels: List[ChannelConfig], alias: str):
        self.user_id = user_id
        self.token = token
        self.channels = channels
        self.alias = alias

    def get_display_name(self) -> str:
        return self.alias if self.alias else self.user_id

def get_timestamp() -> str:
    return "[" + str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")) + "]"

def precise_sleep(duration: float, randomize: bool = False, min_random: float = 0, max_random: float = 0):
    if randomize:
        sleep_duration = duration + random.uniform(min_random, max_random)
    else:
        sleep_duration = duration
        
    start_time = time.perf_counter()
    while (time.perf_counter() - start_time) < sleep_duration:
        remaining = sleep_duration - (time.perf_counter() - start_time)
        if remaining > 0.1:
            time.sleep(0.1)

def validate_sheet_structure(values: List[List[str]]) -> bool:
    """Validate that the sheet has the correct structure"""
    expected_headers = [
        "User ID", "User Alias", "Token", "Channel URL", 
        "Channel ID", "Channel Alias", "Messages", "Delay"
    ]
    
    if not values or len(values) < 2:  # At least headers and one data row
        print("Error: Sheet is empty")
        return False
        
    headers = values[0]
    if len(headers) < len(expected_headers):
        print("Error: Missing columns in sheet")
        print("Expected columns:", expected_headers)
        print("Found columns:", headers)
        return False
        
    for expected, found in zip(expected_headers, headers):
        if expected.lower() != found.lower():
            print(f"Error: Expected column '{expected}', found '{found}'")
            return False
            
    return True

def load_from_sheets(sheet_id: str) -> List[UserConfig]:
    try:
        # Set up Google Sheets API
        creds = Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        service = build('sheets', 'v4', credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=sheet_id,
            range='Sheet1!A1:H1000'  # Include headers for validation
        ).execute()
        
        values = result.get('values', [])
        if not values:
            print('No data found in Google Sheets.')
            return []

        # Validate sheet structure
        if not validate_sheet_structure(values):
            return []

        # Process the data (skip header row)
        users = {}
        for row in values[1:]:  # Skip header row
            # Ensure row has all required fields
            if len(row) < 8:
                print(f"Skipping incomplete row: {row}")
                continue

            user_id = row[0]
            
            # Create new user if not exists
            if user_id not in users:
                users[user_id] = UserConfig(
                    user_id=user_id,
                    token=row[2],
                    channels=[],
                    alias=row[1] if row[1] else user_id
                )
            
            # Add channel to user
            channel = ChannelConfig.from_sheet_row(row)
            users[user_id].channels.append(channel)

        return list(users.values())

    except HttpError as e:
        print(f"Error accessing Google Sheets: {e}")
        if e.resp.status == 403:
            print("Access denied. Make sure the sheet is publicly accessible or shared with the service account.")
        return []
    except Exception as e:
        print(f"Error loading Google Sheets: {e}")
        return []

def send_message(user: UserConfig, channel: ChannelConfig, message: str):
    try:
        header_data = {
            "content-type": "application/json",
            "user-id": user.user_id,
            "authorization": user.token,
            "host": "discordapp.com",
            "referrer": channel.url
        }
        
        message_data = json.dumps({"content": message})
        conn = HTTPSConnection("discordapp.com", 443)
        
        conn.request("POST", f"/api/v6/channels/{channel.id}/messages", message_data, header_data)
        resp = conn.getresponse()
        
        if 199 < resp.status < 300:
            print(f"{get_timestamp()} User {user.get_display_name()} sent message to channel {channel.alias}")
        else:
            print(f"{get_timestamp()} Failed to send message for user {user.get_display_name()} in channel {channel.alias}: Status {resp.status}")
            
        conn.close()
    except Exception as e:
        print(f"{get_timestamp()} Error sending message for user {user.get_display_name()} in channel {channel.alias}: {e}")

def channel_message_loop(user: UserConfig, channel: ChannelConfig):
    """Function to handle message sending for a single channel"""
    while True:
        print(f"{get_timestamp()} User {user.get_display_name()} starting messages for channel {channel.alias}")
        for message in channel.messages:
            send_message(user, channel, message)
            precise_sleep(channel.delay)
        print(f"{get_timestamp()} User {user.get_display_name()} completed message cycle for channel {channel.alias}")
        precise_sleep(1.0)  # Short sleep between cycles

def user_message_loop(user: UserConfig):
    """Function to handle message sending for a single user across all channels in parallel"""
    channel_threads = []
    
    # Create a thread for each channel
    for channel in user.channels:
        thread = threading.Thread(
            target=channel_message_loop,
            args=(user, channel),
            daemon=True
        )
        channel_threads.append(thread)
    
    # Start all channel threads
    for thread in channel_threads:
        thread.start()

def show_configuration_summary(users: List[UserConfig]):
    print("\nCurrent Configuration Summary:")
    for user in users:
        print(f"\nUser: {user.get_display_name()} (ID: {user.user_id})")
        for channel in user.channels:
            print(f"  Channel: {channel.alias} (ID: {channel.id})")
            print(f"    Delay: {channel.delay} seconds")
            print(f"    Messages ({len(channel.messages)}):")
            for i, msg in enumerate(channel.messages, 1):
                print(f"      {i}. {msg}")

def show_help():
    print("Discord Multi-User Auto Messenger Help")
    print("Usage:")
    print("  'python3 auto.py'      : Run the auto messenger")
    print("  'python3 auto.py --help': Show this help message")
    print("\nGoogle Sheets Template Format:")
    print("The following columns are required:")
    print("  - User ID")
    print("  - User Alias")
    print("  - Token")
    print("  - Channel URL")
    print("  - Channel ID")
    print("  - Channel Alias")
    print("  - Messages (comma-separated)")
    print("  - Delay")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        show_help()
        return

    sheet_id = get_sheet_url_from_user()
    users = load_from_sheets(sheet_id)
    
    if not users:
        print(f"{get_timestamp()} No users configured. Please check your Google Sheets configuration.")
        return

    show_configuration_summary(users)
    
    user_threads = []
    for user in users:
        thread = threading.Thread(
            target=user_message_loop,
            args=(user,),
            daemon=True
        )
        user_threads.append(thread)

    print(f"{get_timestamp()} Starting message sending for all users simultaneously...")
    for thread in user_threads:
        thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{get_timestamp()} Received shutdown signal. Waiting for threads to complete...")
        sys.exit(0)

if __name__ == "__main__":
    main()
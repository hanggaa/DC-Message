import json
import sys
import random
import time
import threading
from datetime import datetime
from http.client import HTTPSConnection
from typing import Dict, List

CONFIG_FILE = "config.json"

class ChannelConfig:
    def __init__(self, url: str, id: str, alias: str, messages: List[str], delay: float):
        self.url = url
        self.id = id
        self.alias = alias
        self.messages = messages
        self.delay = delay

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "id": self.id,
            "alias": self.alias,
            "messages": self.messages,
            "delay": self.delay
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            data["url"],
            data["id"],
            data.get("alias", data["id"]),
            data.get("messages", []),
            data.get("delay", 1.0)
        )

class UserConfig:
    def __init__(self, user_id: str, token: str, channels: List[ChannelConfig], alias: str):
        self.user_id = user_id
        self.token = token
        self.channels = channels
        self.alias = alias

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "token": self.token,
            "channels": [channel.to_dict() for channel in self.channels],
            "alias": self.alias
        }

    @classmethod
    def from_dict(cls, data: dict):
        channels = [ChannelConfig.from_dict(channel_data) for channel_data in data["channels"]]
        return cls(
            data["user_id"],
            data["token"],
            channels,
            data.get("alias", data["user_id"])
        )

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

def save_config(users: List[UserConfig]):
    try:
        with open(CONFIG_FILE, "w") as file:
            json.dump({"users": [user.to_dict() for user in users]}, file, indent=4)
        print(f"{get_timestamp()} Configuration saved successfully!")
    except Exception as e:
        print(f"{get_timestamp()} Error saving configuration: {e}")
        sys.exit(1)

def load_config() -> List[UserConfig]:
    try:
        with open(CONFIG_FILE, "r") as file:
            data = json.load(file)
            return [UserConfig.from_dict(user_data) for user_data in data["users"]]
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"{get_timestamp()} Error loading configuration: {e}")
        return []

def configure_single_channel(channel_number: int) -> ChannelConfig:
    print(f"\n--- Channel #{channel_number} Configuration ---")
    channel_url = input("Enter Discord channel URL: ").strip()
    channel_id = input("Enter Discord channel ID: ").strip()
    channel_alias = input("Enter alias for this channel (press Enter to use channel ID): ").strip()
    
    while True:
        try:
            channel_delay = float(input("Enter delay between messages for this channel (in seconds): "))
            if channel_delay > 0:
                break
            print("Please enter a number greater than 0")
        except ValueError:
            print("Please enter a valid number")

    print(f"\nHow many messages should be sent in this channel?")
    while True:
        try:
            num_messages = int(input("Number of messages: "))
            if num_messages > 0:
                break
            print("Please enter a number greater than 0")
        except ValueError:
            print("Please enter a valid number")

    messages = []
    for i in range(num_messages):
        message = input(f"Enter message #{i+1} for this channel: ").strip()
        messages.append(message)

    return ChannelConfig(
        channel_url,
        channel_id,
        channel_alias if channel_alias else channel_id,
        messages,
        channel_delay
    )

def configure_single_user(user_number: int) -> UserConfig:
    print(f"\n=== Configuring User #{user_number} ===")
    user_id = input("Enter User ID: ").strip()
    alias = input("Enter alias name for this user (press Enter to skip): ").strip()
    token = input("Enter Discord token: ").strip()
    
    print(f"\nHow many channels should User #{user_number} send messages to?")
    while True:
        try:
            num_channels = int(input("Number of channels: "))
            if num_channels > 0:
                break
            print("Please enter a number greater than 0")
        except ValueError:
            print("Please enter a valid number")
    
    channels = []
    for i in range(num_channels):
        channel = configure_single_channel(i + 1)
        channels.append(channel)
    
    return UserConfig(user_id, token, channels, alias if alias else user_id)

def configure_users():
    print("\n=== Multi-User Configuration ===")
    while True:
        try:
            num_users = int(input("How many Discord accounts do you want to configure? "))
            if num_users > 0:
                break
            print("Please enter a number greater than 0")
        except ValueError:
            print("Please enter a valid number")

    users = []
    for i in range(num_users):
        user = configure_single_user(i + 1)
        users.append(user)

    save_config(users)
    print(f"\n{get_timestamp()} Configuration completed! {len(users)} users configured.")
    return users

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

def user_message_loop(user: UserConfig):
    """Function to handle message sending for a single user"""
    while True:
        for channel in user.channels:
            print(f"{get_timestamp()} User {user.get_display_name()} starting messages for channel {channel.alias}")
            for message in channel.messages:
                send_message(user, channel, message)
                precise_sleep(channel.delay)
                    
        print(f"{get_timestamp()} User {user.get_display_name()} completed message cycle")
        precise_sleep(1.0)  # Short sleep between cycles

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
    print("  'python3 auto.py'          : Run the auto messenger")
    print("  'python3 auto.py --config' : Configure users and channels")
    print("  'python3 auto.py --help'   : Show this help message")

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--config":
            users = configure_users()
            show_configuration_summary(users)
            return
        elif sys.argv[1] == "--help":
            show_help()
            return

    users = load_config()
    if not users:
        print(f"{get_timestamp()} No users configured. Please run with --config first.")
        return

    show_configuration_summary(users)
    
    threads = []
    for user in users:
        thread = threading.Thread(
            target=user_message_loop,
            args=(user,),
            daemon=True
        )
        threads.append(thread)

    print(f"{get_timestamp()} Starting message sending for all users simultaneously...")
    for thread in threads:
        thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{get_timestamp()} Received shutdown signal. Waiting for threads to complete...")
        sys.exit(0)

if __name__ == "__main__":
    main()
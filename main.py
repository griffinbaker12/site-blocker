import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

HOSTS_PATH = "/etc/hosts"
HEADER_BLOCK = "# Added by work script\n"
FOOTER_BLOCK = "End of section\n"
EM_DASH = "\u2014"
SITE_PATTERN = r"(?:www\.)?([a-zA-Z0-9-]+)\.com"
SESSION_INFO_FILE = "/tmp/site_blocker_session_info"
TEST_FILE = "/tmp/exit_ran"
TIME_FORMAT = "%m/%d/%y, %H:%M:%S"
POST_SESSION_RECAP_QS = [
    "1) What did you learn?",
    "2) What went well?",
    "3) What did not go well?",
]
NOTES_DIR = "session_notes"
SESSION_TRACKER_FILE = "session_tracker.json"

end_session_requested = False


def reset_dns(success_str):
    subprocess.run(["sudo", "killall", "-HUP", "mDNSResponder"])
    return success_str


def print_underline(s, with_str=True):
    if with_str:
        print(s)
    print("-" * len(s))


def remove_spaces(arr):
    return list(filter(bool, arr))


def get_site_name(line):
    return remove_spaces(line.split("\n"))[0].split(" ")[1]


def already_a_session():
    return os.path.exists(SESSION_INFO_FILE)


def block_sites(sites):
    if not already_a_session():
        entries = []
        with open(HOSTS_PATH, "a") as hosts_file:
            for site in sites:
                entries.extend(
                    [
                        f"0.0.0.0 {site}.com",
                        f"0.0.0.0 www.{site}.com",
                    ]
                )
            hosts_file.write(HEADER_BLOCK)
            hosts_file.write("\n".join(entries))
            hosts_file.write("\n")
            hosts_file.write(FOOTER_BLOCK)
        return reset_dns(f"Blocked the following sites: {", ".join(sites)}.")
    else:
        print("Error: Already a current study session in progress.")
        return False


def remove_sites():
    blocked_sites = set()

    with open(HOSTS_PATH, "r") as hosts_file:
        lines = hosts_file.readlines()

    with open(HOSTS_PATH, "w") as hosts_file:
        seen_header_block = False
        for line in lines:
            if line == HEADER_BLOCK:
                seen_header_block = True
            elif not seen_header_block:
                hosts_file.write(line)
            elif line == FOOTER_BLOCK:
                break
            else:
                parsed_line = get_site_name(line)
                if m := re.match(SITE_PATTERN, parsed_line):
                    if m not in blocked_sites:
                        site_name = m.group(1)
                        blocked_sites.add(site_name)

    reset_dns(f"\nRemoved blocked sites: {", ".join(blocked_sites)}.")


def prompt_user(start_time):
    if not os.path.exists(NOTES_DIR):
        os.makedirs(NOTES_DIR)

    if not os.path.exists(SESSION_TRACKER_FILE):
        with open(SESSION_TRACKER_FILE, "w") as tracker_file:
            json.dump({"session_number": 1}, tracker_file)

    with open(SESSION_TRACKER_FILE, "r") as tracker_file:
        data = json.load(tracker_file)
        session_number = data["session_number"]

    session_end_str = "Work session ended, answer these questions to recap how it went!"
    # print("\n")
    print_underline(f"{session_end_str}", with_str=False)
    print_underline(session_end_str)

    answers = {}
    for q in POST_SESSION_RECAP_QS:
        answer = input(f"{q}\n")
        answers[q] = answer
        print("\n")

    note_file_path = os.path.join(NOTES_DIR, f"session_{session_number:02}.md")
    with open(note_file_path, "w") as note_file:
        session_start_time = start_time
        session_end_time = datetime.now()
        session_duration_str = format_timedelta(session_end_time - session_start_time)
        note_file.write(f"**Session {session_number} - {session_duration_str}**\n\n")

        for q, a in answers.items():
            note_file.write(f"**{q}**\n{a}\n\n")

    data["session_number"] += 1
    with open(SESSION_TRACKER_FILE, "w") as tracker_file:
        json.dump(data, tracker_file)

    subprocess.run(f"echo '{note_file_path}' | pbcopy", shell=True)
    print(f"⭐️ Congrats on working for {session_duration_str} ⭐️")
    print(
        f"Your answers have been saved to {note_file_path}. The file path has also been copied to your clipboard!"
    )


def start_session(sites, duration):
    if block_str := block_sites(sites):
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration)

        with open(SESSION_TRACKER_FILE, "r") as tracker_file:
            data = json.load(tracker_file)
            session_number = data["session_number"]

        with open(SESSION_INFO_FILE, "w") as session_file:
            session_file.write(
                f"Session number {session_number}\nStart time:{start_time.strftime(TIME_FORMAT)}\nEnd time:{end_time.strftime(TIME_FORMAT)}\n"
            )
            session_file.write("\n".join(sites))

        session_started_str = f"Study session started for {duration} minutes."
        underline_str = (
            session_started_str
            if len(session_started_str) > len(block_str)
            else block_str
        )

        print_underline(underline_str, with_str=False)
        print(session_started_str)
        print(block_str)
        print_underline(underline_str, with_str=False)

        try:
            time.sleep(duration * 60)
        except KeyboardInterrupt:
            confirm_end_session()
        finally:
            if not end_session_requested:
                end_session()


def remove_old_info_file_and_get_start_time():
    start_time = None
    if os.path.exists(SESSION_INFO_FILE):
        with open(SESSION_INFO_FILE, "r") as f:
            for line in f:
                if line.startswith("Start time:"):
                    start_time_str = line.split("Start time:")[1].strip()
                    start_time = datetime.strptime(start_time_str, TIME_FORMAT)
                    break
        os.remove(SESSION_INFO_FILE)
    return start_time


def end_session():
    remove_sites()

    start_time = None
    if os.path.exists(SESSION_INFO_FILE):
        # save the old start time to get full duration
        start_time = remove_old_info_file_and_get_start_time()

    if start_time:
        prompt_user(start_time)
    else:
        print("Error parsing the session info file.")
        sys.exit(1)

    sys.exit(0)


def confirm_end_session():
    global end_session_requested
    end_session_requested = True
    valid_input = False

    while not valid_input:
        confirm = (
            input("\nAre you sure you want to end the study session? (y/n): ")
            .strip()
            .lower()
        )
        if confirm == "y":
            end_session()
            valid_input = True
        elif confirm == "n":
            end_session_requested = False
            valid_input = True
        else:
            print("Please type either 'y' or 'n'.")


def signal_handler(sig, frame):
    confirm_end_session()


def format_timedelta(td):
    hours, remainder = divmod(td.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    if int(hours) > 0:
        return f"{int(hours)} hours, {int(minutes)} minutes"
    else:
        return f"{int(minutes)} minutes"


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(
        description="Block websites during this study session of a specified time period."
    )
    parser.add_argument(
        "action",
        choices=["start", "end"],
        help="Action to perform: 'start' a new session, get 'info' about the current session, or 'end' the current session.",
    )
    # Q: assume that the --sites makes it optional?
    parser.add_argument(
        "--sites",
        help="Comma-separated list of site names (eg, x, instagram, etc.) to block.",
    )
    # Q: assume that the --sites makes it optional?
    parser.add_argument(
        "--duration",
        type=int,
        help="Time to block sites (in minutes).",
    )
    args = parser.parse_args()

    if args.action == "start":
        if not args.sites or not args.duration:
            print("Error: Both --sites and --duration are required for 'start' action.")
            sys.exit(1)
        sites = args.sites.split(",")
        start_session(sites, args.duration)
    elif args.action == "end":
        end_session()
    else:
        print("Please enter a valid action: start, end.")


if __name__ == "__main__":
    main()

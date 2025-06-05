import argparse
import json
import re
import os
from bs4 import BeautifulSoup
from datetime import datetime
from bs4 import MarkupResemblesLocatorWarning
import warnings

# Ignore the MarkupResemblesLocatorWarning as we are parsing HTML snippets
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

def clean_display_name(display_name_text):
    """
    Cleans and normalizes a display name by removing common chat client suffixes,
    special characters, and extra spaces.
    """
    # Remove HTML entities like &lt; and &gt;
    cleaned = display_name_text.replace('&lt;', '<').replace('&gt;', '>').strip()
    # Remove common suffixes (e.g., ' - ...', ' [...]', ' (...)', ' :')
    cleaned = re.sub(r'\s*[-—].*|\s*\[.*?\]|\s*\([^)]+\)|\s*:\s*$', '', cleaned).strip()
    # Remove any lingering special characters or non-alphanumeric that aren't part of core names
    cleaned = re.sub(r'[^\w\s]', '', cleaned).strip()
    # Replace sequences of whitespace with a single space
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    return cleaned

def html_to_json(html_file_path, json_file_path, user_identifier):
    """
    Converts an HTML chat log file into a JSON format suitable for AI training.
    Messages from the 'user_identifier' are marked as 'gpt', others as 'human'.
    """
    print(f"DEBUG: Processing file: {html_file_path}")
    conversations = []

    try:
        # Open file with specific UTF-16LE encoding for MSN logs
        with open(html_file_path, 'r', encoding='utf-16-le') as file:
            soup = BeautifulSoup(file, 'html.parser')
    except Exception as e:
        print(f"ERROR: Could not open or parse {html_file_path}: {e}")
        return

    sessions = soup.find_all('div', class_='mplsession')
    print(f"DEBUG: Found {len(sessions)} sessions in {html_file_path}")

    for session_idx, session in enumerate(sessions):
        # Extract session date
        session_date_tag = session.find('h2')
        session_date = "UNKNOWN_DATE"
        if session_date_tag:
            date_str_match = re.search(r'\d{1,2} \w+ \d{4}', session_date_tag.get_text())
            if date_str_match:
                date_part = date_str_match.group(0)
                # Map French month names to English for datetime parsing
                french_months = {
                    'janvier': 'January', 'février': 'February', 'mars': 'March',
                    'avril': 'April', 'mai': 'May', 'juin': 'June',
                    'juillet': 'July', 'août': 'August', 'septembre': 'September',
                    'octobre': 'October', 'novembre': 'November', 'décembre': 'December'
                }
                for fr, en in french_months.items():
                    date_part = date_part.replace(fr, en)
                try:
                    session_date = datetime.strptime(date_part, '%d %B %Y').strftime('%y.%m.%d')
                except ValueError:
                    print(f"Warning: Could not parse session date '{date_part}' in file {html_file_path}. Using UNKNOWN_DATE.")

        # Build a canonical map of known display names to primary identifiers (e.g., email IDs)
        # This map will store {normalized_display_name_from_header: primary_identifier, ...}
        canonical_participant_map = {} 
        
        participants_list = session.find('ul')
        if participants_list:
            for li in participants_list.find_all('li'):
                full_li_text = li.get_text(strip=True)
                # Try to extract the primary identifier (e.g., email address) from parentheses
                identifier_match = re.search(r'\(([^)]+@[^)]+\.[^)]+)\)', full_li_text)
                
                primary_identifier = None
                if identifier_match:
                    primary_identifier = identifier_match.group(1).lower()
                    
                    # Extract the display name part before the identifier
                    display_name_part = full_li_text.replace(f'({identifier_match.group(1)})', '').strip()
                    
                    # Store multiple, increasingly cleaned versions of the display name
                    # These will be the keys for our canonical_participant_map
                    
                    # 1. Very light cleaning: just remove surrounding whitespace
                    name_v1 = display_name_part.lower()
                    if name_v1 and name_v1 not in canonical_participant_map:
                        canonical_participant_map[name_v1] = primary_identifier

                    # 2. More aggressive cleaning: remove suffixes and special characters
                    name_v2 = clean_display_name(display_name_part)
                    if name_v2 and name_v2 not in canonical_participant_map:
                        canonical_participant_map[name_v2] = primary_identifier
                    
                    # 3. First word only (e.g., "User", "Friend")
                    name_v3 = name_v2.split(' ')[0] if name_v2 else ''
                    if name_v3 and name_v3 not in canonical_participant_map:
                        canonical_participant_map[name_v3] = primary_identifier
                else:
                    # Fallback for participants without explicit identifier in header (less common but for robustness)
                    cleaned_name = clean_display_name(full_li_text)
                    if cleaned_name and cleaned_name not in canonical_participant_map:
                        canonical_participant_map[cleaned_name] = cleaned_name # Use name as pseudo-identifier

        print(f"DEBUG: Session {session_idx+1} Canonical Participant Map: {canonical_participant_map}")

        message_rows = session.find_all('tr')
        session_conversations = []

        for row_idx, row in enumerate(message_rows):
            # Skip rows that represent status changes or other non-message events
            if 'msgplus' in row.get('class', []):
                continue

            time_tag = row.find('span', class_='time')
            sender_th = row.find('th')
            content_td = row.find('td')

            if time_tag and sender_th and content_td:
                # Extract and format timestamp
                time_str = time_tag.get_text(strip=True).replace('(', '').replace(')', '')
                if len(time_str.split(':')) == 2: # Add dummy seconds if missing
                    time_str += ':00'
                full_timestamp = f"{session_date}, {time_str}"

                # Extract sender's display name from the <th> tag, accounting for inner HTML spans
                sender_th_clone = sender_th.decode_contents() # Get inner HTML
                # Remove the time span HTML from the string before parsing with BS again
                time_span_html = str(time_tag)
                sender_display_name_raw = sender_th_clone.replace(time_span_html, '', 1).strip()
                
                # Use BeautifulSoup to get pure text from the potentially HTML-rich sender name
                sender_display_name_from_msg = BeautifulSoup(sender_display_name_raw, 'html.parser').get_text(strip=True).rstrip(':').strip()

                # Prepare multiple cleaned versions of the sender name from the message for matching
                sender_name_v1 = sender_display_name_from_msg.lower()
                sender_name_v2 = clean_display_name(sender_display_name_from_msg)
                sender_name_v3 = sender_name_v2.split(' ')[0] if sender_name_v2 else ''

                # Extract and clean message content
                content_html = ''.join(str(c) for c in content_td.contents)
                content_text = BeautifulSoup(content_html, 'html.parser').get_text(separator=' ', strip=True)

                # Filter out messages containing only links or specific system prompts
                if content_text.strip().lower().startswith("http://") or \
                   content_text.strip().lower().startswith("https://") or \
                   content_text.strip().lower().startswith("ping? [request]"):
                    continue

                # --- Determine 'from' field based on identifier lookup ---
                identified_sender_identifier = None

                # Prioritize matching cleaned versions of the sender's name from the message
                if sender_name_v2 in canonical_participant_map:
                    identified_sender_identifier = canonical_participant_map[sender_name_v2]
                elif sender_name_v3 in canonical_participant_map:
                    identified_sender_identifier = canonical_participant_map[sender_name_v3]
                elif sender_name_v1 in canonical_participant_map: # Check raw lowecased version
                    identified_sender_identifier = canonical_participant_map[sender_name_v1]
                else:
                    # Fallback to broader substring matching if direct clean matches fail
                    for canonical_name, identifier_in_map in canonical_participant_map.items():
                        if canonical_name in sender_name_v2 or sender_name_v2 in canonical_name:
                            identified_sender_identifier = identifier_in_map
                            break 

                from_field = "human" # Default label for other participants
                if identified_sender_identifier and user_identifier.lower() == identified_sender_identifier.lower():
                    from_field = "gpt" # Label for the specified user

                print(f"DEBUG: Message sender: '{sender_display_name_from_msg}' (cleaned:'{sender_name_v2}') -> Identified ID: {identified_sender_identifier}, Label: {from_field}") 

                session_conversations.append({
                    "from": from_field,
                    "value": content_text
                })

        if session_conversations:
            conversations.extend(session_conversations)
            print(f"DEBUG: Session {session_idx+1} added {len(session_conversations)} messages. Total so far: {len(conversations)}")

    print(f"DEBUG: Finished processing {html_file_path}. Total conversations: {len(conversations)}")

    # Save the conversations list to JSON file(s)
    if len(conversations) > 40: # Split into multiple files if too long for training
        for i in range(0, len(conversations), 40):
            partial_conversations = conversations[i:i+40]
            if len(partial_conversations) < 3: # Skip very short segments
                print(f"DEBUG: Skipping partial conversation (length {len(partial_conversations)}) as it's too short.")
                continue
            json.dump({"conversations": partial_conversations}, open(json_file_path + str(i) + ".json", 'w', encoding='utf-8'), ensure_ascii=False, indent=4)
            print(f"DEBUG: Saved {json_file_path}{i}.json with {len(partial_conversations)} messages.")
    else:
        if len(conversations) < 3: # Skip very short complete conversations
            print(f"DEBUG: Skipping conversation (length {len(conversations)}) as it's too short for a single file.")
            return
        json.dump({"conversations": conversations}, open(json_file_path + ".json", 'w', encoding='utf-8'), ensure_ascii=False, indent=4)
        print(f"DEBUG: Saved {json_file_path}.json with {len(conversations)} messages.")


def process_folder(data_folder, output_folder, user_identifier):
    """
    Processes all HTML files in a given data folder and converts them to JSON.
    """
    # Create the output folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"DEBUG: Created output folder: {output_folder}")

    # Process each .html file in the data folder
    found_html_files = False
    for filename in os.listdir(data_folder):
        if filename.endswith('.html'):
            found_html_files = True
            file_path = os.path.join(data_folder, filename)
            json_file_name = os.path.splitext(filename)[0]
            json_file_path = os.path.join(output_folder, json_file_name)
            print(f"Processing '{filename}'...")
            html_to_json(file_path, json_file_path, user_identifier)

    if not found_html_files:
        print(f"WARNING: No .html files found in '{data_folder}'. Please ensure your files are in this directory and have the '.html' extension.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert chat HTML logs to JSON format for AI training.")
    parser.add_argument("user_identifier", type=str, 
                        help="Your primary identifier (e.g., email address) to label your messages as 'gpt'.")
    args = parser.parse_args()

    if not args.user_identifier:
        print("Please provide a user identifier to label your messages.")
        exit()

    print(f"Using '{args.user_identifier}' as the user identifier.")

    data_folder = "data/raw_data"
    output_folder = "data/preprocessed"
    process_folder(data_folder, output_folder, args.user_identifier)

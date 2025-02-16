import os
import subprocess
import logging
import time
import json

logging.basicConfig(filename='update_messages.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
def export_chat(their_id, messages_file, messages_file_temp):
    logging.info("Starting chat export...")
    
    # Load the last export time if it exists
    last_export_time_file = 'last_export_time'
    if os.path.exists(last_export_time_file):
        with open(last_export_time_file, 'r') as file:
            last_export_time = file.read().strip()
    else:
        last_export_time = '0'  # Unix epoch start time
    
    current_time = str(int(time.time()))
    
    command = [
        'tdl', 'chat', 'export',
        '-c', str(their_id),
        '--raw',
        '--all',
        '--with-content',
        '-o', messages_file_temp,
        '-i', f'{last_export_time},{current_time}'
    ]

    logging.info(f"Running command: {' '.join(command)}")
    
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode == 0:
        logging.info("Chat export successful.")
        
        # New: Download chat files using tdl dl command
        download_command = ['tdl', 'dl', '-f', messages_file_temp]
        download_result = subprocess.run(download_command, capture_output=True, text=True, encoding='utf-8')
        if download_result.returncode != 0:
            logging.error(f"Error downloading files: {download_result.stderr}")
        else:
            logging.info("Download successful.")
        
        # Load existing messages if the file exists
        if os.path.exists(messages_file):
            with open(messages_file, 'r', encoding='utf-8') as file:
                existing_data = json.load(file)
        else:
            existing_data = {"id": their_id, "messages": []}
        
        # Load new messages from the temporary exported file
        with open(messages_file_temp, 'r', encoding='utf-8') as file:
            new_data = json.load(file)
        
        # Append new messages to the existing messages
        existing_data['messages'].extend(new_data['messages'])
        
        # Save the combined messages back to the file
        with open(messages_file, 'w', encoding='utf-8') as file:
            json.dump(existing_data, file, ensure_ascii=False, indent=4)
        
        # Save the current time as the last export time
        with open(last_export_time_file, 'w') as file:
            file.write(current_time)
    else:
        logging.error(f"Error exporting chat: {result.stderr}")
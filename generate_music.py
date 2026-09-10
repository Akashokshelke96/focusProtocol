import warnings
# Suppress the urllib3 version mismatch warning
warnings.filterwarnings("ignore", category=UserWarning, module='requests')

import requests
import sys

API_KEY = "271fd1cf7aa14bda9b2227ec4c797cda"
BASE_URL = "https://api.acemusic.ai"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def generate_music():
    print("1. Submitting generation request to Cloud API...")
    
    # Standard OpenAI-compatible audio generation payload
    payload = {
        "model": "acestep-v15-turbo", # Standard ACE-Step 1.5 fast model
        "prompt": "upbeat pop, energetic synth, dance",
        "response_format": "mp3"
    }

    try:
        response = requests.post(BASE_URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        # Check if the API returned the audio file directly as bytes
        content_type = response.headers.get("Content-Type", "")
        
        if "audio" in content_type:
            print("2. Generation complete! Downloading file directly...")
            with open("generated_track.mp3", "wb") as f:
                f.write(response.content)
            print("Success! Saved as generated_track.mp3")
            
        # Otherwise, check if it returned a JSON containing a download URL
        else:
            data = response.json()
            print("2. Response received. Extracting audio...")
            
            # Navigate standard JSON data structures for audio URLs
            if "data" in data and len(data["data"]) > 0:
                audio_url = data["data"][0].get("url")
                if audio_url:
                    print(f"Downloading from: {audio_url}")
                    audio_resp = requests.get(audio_url)
                    audio_resp.raise_for_status()
                    with open("generated_track.mp3", "wb") as f:
                        f.write(audio_resp.content)
                    print("Success! Saved as generated_track.mp3")
                else:
                    print("Error: 'url' missing in the response data.")
            else:
                 print("Unexpected JSON format received:", data)
                 
    except requests.exceptions.HTTPError as e:
        print(f"\nAPI Error {e.response.status_code}: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"\nFailed to submit task: {e}")
        sys.exit(1)

if __name__ == "__main__":
    generate_music()
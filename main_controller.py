"""
WILDLIFE MONITOR - RASPBERRY PI CONTROLLER (FINAL)
-------------------------------------------------
Connects to MQTT, waits for a trigger, records video,
runs AI detection, saves to DB, and sends notifications.
"""
import paho.mqtt.client as mqtt
import json
import subprocess
import os
import sqlite3
import requests
import time
from datetime import datetime
from ultralytics import YOLO


# --- Configuration ---
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TRIGGER_TOPIC = "WILDLIFE/TRIGGER"
NTFY_TOPIC = "wildcam_project_aus" 
MODEL_FILE = "/home/param/yolov8n.pt"
CAPTURE_DIR = "/home/param/captures"
DB_FILE = "/home/param/wildlife_log.db"
VIDEO_DURATION_MS = 10000  # 10 seconds

# List of classes to consider "animals"
ANIMAL_CLASSES = ["bird", "cat", "dog", "horse", "sheep", "cow", 
                  "elephant", "bear", "zebra", "giraffe"]

# --- Global YOLO Model ---
model = None
# --- NEW: Global processing lock ---
is_processing = False

# --- 1. Database Functions ---
def init_db():
    """Initializes the database and creates the 'captures' table if it doesn't exist."""
    print("Initializing database...")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                classification TEXT NOT NULL,
                confidence REAL,
                video_path TEXT,
                temp REAL,
                humidity REAL,
                battery INTEGER,
                light_state INTEGER
            );
            """)
            conn.commit()
            print("Database initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")
def save_to_db(data):
    """Saves a single detection event to the database."""
    print("Saving to database...")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO captures (timestamp, classification, confidence, video_path, 
                                  temp, humidity, battery, light_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get('timestamp'),
                data.get('classification'),
                data.get('confidence'),
                data.get('video_path'),
                data.get('temp'),
                data.get('humidity'),
                data.get('battery'),
                data.get('light_state')
            ))
            conn.commit()
            print("Data saved successfully.")
    except Exception as e:
        print(f"Error saving to database: {e}")

# --- 2. Core Logic ---
def record_video(filename_base):
    """Records a 10-second video and saves it as a web-safe MP4."""
    print(f"Recording {VIDEO_DURATION_MS}ms video...")
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    
    # Define paths
    raw_video_path = os.path.join(CAPTURE_DIR, f"{filename_base}.h264")
    final_video_path = os.path.join(CAPTURE_DIR, f"{filename_base}.mp4")
    
    # 1. Record the raw H.264 stream
    record_command = [
        "rpicam-vid",
        "-t", str(VIDEO_DURATION_MS),
        "--width", "1280",
        "--height", "720",
        "-o", raw_video_path
    ]
    
    try:
        subprocess.run(record_command, check=True)
        print(f"Raw video saved: {raw_video_path}")
    except Exception as e:
        print(f"Error recording video: {e}")
        return None

    # 2. Re-wrap the raw stream into an MP4 container using ffmpeg
    print(f"Converting {raw_video_path} to {final_video_path}...")
    convert_command = [
        "ffmpeg",
        "-i", raw_video_path,
        "-c:v", "copy",
        "-y",
        final_video_path
    ]
    
    try:
        # Hide the ffmpeg output to keep the log clean
        subprocess.run(convert_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"MP4 conversion successful: {final_video_path}")
    except Exception as e:
        print(f"Error converting video to MP4: {e}")
        return None
        
    # 3. Clean up the raw .h264 file
    try:
        os.remove(raw_video_path)
        print(f"Cleaned up {raw_video_path}")
    except Exception as e:
        print(f"Warning: could not delete raw video file: {e}")

    # 4. Return the path to the final MP4
    return final_video_path

def extract_frame(video_path, frame_path):
    """Extracts the first frame from the video for analysis."""
    print(f"Extracting frame from {video_path}...")
    try:
        command = [
            "ffmpeg",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2", # High quality
            frame_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Frame saved: {frame_path}")
        return frame_path
    except Exception as e:
        print(f"Error extracting frame: {e}")
        return None
def run_animal_detection(frame_path):
    """Runs YOLOv8 model on the frame and classifies."""
    global model
    print(f"Analyzing frame with YOLOv8: {frame_path}...")
    
    results = model(frame_path, verbose=False) 
    
    best_detection = {"is_animal": False, "class": "False Positive", "confidence": 0.0}
    
    for r in results:
        for box in r.boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            confidence = float(box.conf[0])
            
            if class_name in ANIMAL_CLASSES and confidence > best_detection["confidence"]:
                best_detection["is_animal"] = True
                best_detection["class"] = class_name.capitalize()
                best_detection["confidence"] = confidence
    
    print(f"AI Result: {best_detection}")
    return best_detection

def send_notification(result, frame_path):
    """Sends a push notification via ntfy.sh."""
    print("Sending notification...")
    try:
        title = f"Animal Detected: {result['class']}"
        message = f"Confidence: {result['confidence'] * 100:.1f}%"
        
        with open(frame_path, 'rb') as f:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=f.read(),
                headers={
                    "Title": title,
                    "Message": message,
                    "filename": "detection.jpg"
                }
            )
        print("Notification sent.")
    except Exception as e:
        print(f"Error sending notification: {e}")
# --- 3. MQTT Handlers ---
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected to MQTT Broker.")
        client.subscribe(TRIGGER_TOPIC)
        print(f"Waiting for trigger on {TRIGGER_TOPIC}...")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    """Main callback triggered by Arduino."""

    # --- NEW: Check the lock ---
    global is_processing
    if is_processing:
        print("\n--- BUSY: Ignoring trigger, processing in progress. ---")
        return # Exit immediately

    # --- NEW: Set the lock ---
    is_processing = True

    print("\n--- TRIGGER RECEIVED ---")
    try:
        # 1. Get sensor data from payload
        payload = msg.payload.decode('utf-8')
        print(f"Payload: {payload}")
        sensor_data = json.loads(payload)

        # 2. Define filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename_base = f"vid_{timestamp}" # No .mp4 extension
        frame_filename = f"frame_{timestamp}.jpg"

        # 3. Record video
        video_path = record_video(video_filename_base) # Pass the base name
        if not video_path:
            return # Error is printed inside function

        # 4. Extract frame
        frame_path = os.path.join(CAPTURE_DIR, frame_filename)
        if not extract_frame(video_path, frame_path):
            return # Error is printed inside function

        # 5. Run AI
        ai_result = run_animal_detection(frame_path)

        # 6. Prepare data for database
        db_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "classification": ai_result["class"],
            "confidence": ai_result["confidence"],
            "video_path": video_path,
            "temp": sensor_data.get("temp"),
            "humidity": sensor_data.get("humidity"),
            "battery": sensor_data.get("battery"),
            "light_state": sensor_data.get("light_state")
        }

        # 7. Save to DB
        save_to_db(db_data)

        # 8. Send notification (only if animal)
        if ai_result["is_animal"]:
            send_notification(ai_result, frame_path)

        print("--- TASK COMPLETE ---")

    except Exception as e:
        print(f"Error in on_message: {e}")

    # --- NEW: Release the lock in a 'finally' block ---
    finally:
        print(f"Cooldown started... waiting 10 seconds.")
        time.sleep(10) # <-- YOUR 10 SECOND GAP
        is_processing = False # Unlock for the next trigger
        print("System is ready for new trigger.")
# --- 4. Main Execution ---
if __name__ == "__main__":
    try:
        # Load AI model
        print("Loading YOLOv8n model...")
        model = YOLO(MODEL_FILE)
        print("YOLOv8n model loaded.")
        
        # Initialize database
        init_db()

        # Start MQTT client
        print("Processor script running...")
        client = mqtt.Client(client_id="rpi_processor", callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
        
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Main loop error: {e}")


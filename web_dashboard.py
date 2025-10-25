"""
WILDLIFE MONITOR - WEB DASHBOARD 
"""
from flask import Flask, render_template, send_from_directory, g
import sqlite3
import os

# --- Configuration ---
DATABASE_FILE = "/home/param/wildlife_log.db"
CAPTURE_DIR = "/home/param/captures"
HOST_IP = "0.0.0.0" # Listen on all network interfaces
HOST_PORT = 5000

app = Flask(__name__)

# --- Database Connection ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE_FILE)
        db.row_factory = sqlite3.Row  # This lets us access columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Main Dashboard Route ---
@app.route('/')
def index():
    try:
        cur = get_db().cursor()
        
        # --- THIS IS THE ORIGINAL QUERY ---
        # It selects *all* entries, including False Positives.
        cur.execute(
            "SELECT * FROM captures ORDER BY id DESC"
        )
        
        captures = cur.fetchall()
        
        # We need to process the paths to be web-friendly
        processed_captures = []
        for cap in captures:
            row = dict(cap) # Convert sqlite3.Row to a mutable dict
            
            # Create a relative path for the web server
            if row['video_path']:
                row['web_video_path'] = os.path.basename(row['video_path'])
            processed_captures.append(row)
            
        return render_template('index.html', captures=processed_captures)
        
    except Exception as e:
        return f"An error occurred reading the database: {e}"

# --- Route to serve the video files ---
@app.route('/captures/<filename>')
def serve_capture(filename):
    try:
        # --- THIS IS THE CORRECTED LINE ---
        return send_from_directory(CAPTURE_DIR, filename)
    except Exception as e:
        return f"Error serving file: {e}"

# --- Run the App ---
if __name__ == '__main__':
    print(f"Starting Wildlife Dashboard Server...")
    print(f"Access it at http://{HOST_IP}:{HOST_PORT}")
    app.run(host=HOST_IP, port=HOST_PORT, debug=False)


from flask import Flask, jsonify, request, send_file, abort
import subprocess
import os
import tempfile
import shutil
from datetime import datetime, timedelta
import threading
import time
from pathlib import Path
import uuid

app = Flask(__name__)

TEMP_DIR = "/app/temp_conversions"
CLEANUP_INTERVAL = 3600  # Clean up every hour
MAX_FILE_AGE = 3600  # Delete files older than 1 hour

os.makedirs(TEMP_DIR, exist_ok=True)

def cleanup_old_files():
    """Remove temporary files older than MAX_FILE_AGE"""
    while True:
        try:
            now = time.time()
            for item in Path(TEMP_DIR).iterdir():
                if item.is_dir():
                    # Check directory modification time
                    if now - item.stat().st_mtime > MAX_FILE_AGE:
                        shutil.rmtree(item)
                        print(f"Cleaned up old directory: {item}")
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(CLEANUP_INTERVAL)

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.route('/')
def home():
    return jsonify({
        "message": "Flask + MuseScore Docker Environment",
        "status": "running",
        "endpoints": {
            "/": "This message",
            "/health": "Health check",
            "/musescore/version": "Get MuseScore version",
            "/convert": "Convert MIDI to MusicXML (POST)"
        }
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/musescore/version')
def musescore_version():
    try:
        result = subprocess.run(['musescore3', '--version'], 
                              capture_output=True, 
                              text=True)
        return jsonify({
            "musescore_version": result.stdout.strip(),
            "error": result.stderr if result.stderr else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/convert', methods=['POST'])
def convert_midi_to_musicxml():
    """
    Convert MIDI file to MusicXML using MuseScore.
    Expects a MIDI file in the request body.
    Returns the converted MusicXML file.
    """
    # Check if file is present in request
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    # Check if file is selected
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    # Validate file extension
    if not file.filename.lower().endswith(('.mid', '.midi')):
        return jsonify({"error": "File must be a MIDI file (.mid or .midi)"}), 400
    
    # Create a unique temporary directory for this conversion
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(TEMP_DIR, temp_id)
    os.makedirs(temp_path, exist_ok=True)
    
    try:
        # Save uploaded MIDI file
        midi_filename = f"input_{temp_id}.mid"
        midi_path = os.path.join(temp_path, midi_filename)
        file.save(midi_path)
        
        # Define output MusicXML path
        xml_filename = f"output_{temp_id}.xml"
        xml_path = os.path.join(temp_path, xml_filename)
        
        # Convert MIDI to MusicXML using MuseScore
        cmd = ['musescore3', '-o', xml_path, midi_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # Check if conversion was successful
        if result.returncode != 0:
            error_msg = result.stderr if result.stderr else "Unknown error during conversion"
            return jsonify({
                "error": "Conversion failed",
                "details": error_msg
            }), 500
        
        # Check if output file was created
        if not os.path.exists(xml_path):
            return jsonify({"error": "Conversion failed - output file not created"}), 500
        
        # Send the converted file
        return send_file(
            xml_path,
            mimetype='application/xml',
            as_attachment=True,
            download_name=f"{os.path.splitext(file.filename)[0]}.xml"
        )
        
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timeout - file may be too large or complex"}), 500
    except Exception as e:
        return jsonify({"error": f"Conversion error: {str(e)}"}), 500
    finally:
        def delayed_cleanup():
            time.sleep(5)  # Wait 5 seconds to ensure file is sent
            try:
                if os.path.exists(temp_path):
                    shutil.rmtree(temp_path)
            except:
                pass
        
        cleanup = threading.Thread(target=delayed_cleanup, daemon=True)
        cleanup.start()

@app.route('/convert/info', methods=['GET'])
def convert_info():
    """Get information about the conversion endpoint"""
    return jsonify({
        "endpoint": "/convert",
        "method": "POST",
        "accepts": "MIDI files (.mid, .midi)",
        "returns": "MusicXML file (.xml)",
        "usage": {
            "curl": "curl -X POST -F 'file=@your_file.mid' http://localhost:8129/convert -o output.xml",
            "description": "Send a MIDI file as multipart/form-data with field name 'file'"
        },
        "limitations": {
            "timeout": "30 seconds",
            "file_types": "MIDI files only (.mid or .midi extension)"
        }
    })

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({"error": "File too large"}), 413

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8129, debug=True)

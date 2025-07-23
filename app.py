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
import signal
import psutil

app = Flask(__name__)

# Temporary files directory
TEMP_DIR = "/app/temp_conversions"
CLEANUP_INTERVAL = 3600  # Clean up every hour
MAX_FILE_AGE = 3600  # Delete files older than 1 hour
PROCESS_CHECK_INTERVAL = 300  # Check for zombie processes every 5 minutes

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)


def kill_process_tree(pid):
    """Kill a process and all its children"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)

        # Kill children first
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass

        # Give them time to terminate
        gone, alive = psutil.wait_procs(children, timeout=3)

        # Force kill any remaining
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass

        # Kill parent
        try:
            parent.terminate()
            parent.wait(timeout=3)
        except psutil.TimeoutExpired:
            parent.kill()
        except psutil.NoSuchProcess:
            pass

    except psutil.NoSuchProcess:
        pass


def cleanup_zombie_musescore():
    """Find and kill any hanging MuseScore processes"""
    while True:
        try:
            killed_count = 0
            for proc in psutil.process_iter(['pid', 'name', 'create_time']):
                try:
                    # Check if it's a musescore process
                    if 'musescore' in proc.info['name'].lower():
                        # If process is older than 5 minutes, it's probably hanging
                        age = time.time() - proc.info['create_time']
                        if age > 300:  # 5 minutes
                            print(f"Killing hanging MuseScore process {proc.info['pid']} (age: {age:.0f}s)")
                            kill_process_tree(proc.info['pid'])
                            killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if killed_count > 0:
                print(f"Cleaned up {killed_count} hanging MuseScore processes")

        except Exception as e:
            print(f"Process cleanup error: {e}")

        time.sleep(PROCESS_CHECK_INTERVAL)


def cleanup_old_files():
    """Remove temporary files older than MAX_FILE_AGE"""
    while True:
        try:
            now = time.time()
            for item in Path(TEMP_DIR).iterdir():
                if item.is_dir():
                    if now - item.stat().st_mtime > MAX_FILE_AGE:
                        shutil.rmtree(item)
                        print(f"Cleaned up old directory: {item}")
        except Exception as e:
            print(f"File cleanup error: {e}")

        time.sleep(CLEANUP_INTERVAL)


# Start cleanup threads
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

zombie_cleanup_thread = threading.Thread(target=cleanup_zombie_musescore, daemon=True)
zombie_cleanup_thread.start()


@app.route('/')
def home():
    # Get process count for monitoring
    musescore_count = sum(1 for p in psutil.process_iter(['name'])
                          if 'musescore' in p.info['name'].lower())

    return jsonify({
        "message": "Flask + MuseScore Docker Environment",
        "status": "running",
        "musescore_processes": musescore_count,
        "endpoints": {
            "/": "This message",
            "/health": "Health check",
            "/musescore/version": "Get MuseScore version",
            "/convert": "Convert MIDI to MusicXML (POST)",
            "/system/processes": "Check running processes"
        }
    })


@app.route('/health')
def health():
    return jsonify({"status": "healthy"})


@app.route('/system/processes')
def system_processes():
    """Monitor running MuseScore processes"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'create_time', 'memory_info']):
        try:
            if 'musescore' in proc.info['name'].lower():
                age = time.time() - proc.info['create_time']
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'age_seconds': round(age, 2),
                    'memory_mb': round(proc.info['memory_info'].rss / 1024 / 1024, 2)
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return jsonify({
        'musescore_processes': len(processes),
        'processes': processes
    })


@app.route('/musescore/version')
def musescore_version():
    try:
        result = subprocess.run(['musescore3', '--version'],
                                capture_output=True,
                                text=True,
                                timeout=10)
        return jsonify({
            "musescore_version": result.stdout.strip(),
            "error": result.stderr if result.stderr else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/convert', methods=['POST'])
def convert_midi_to_musicxml():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not file.filename.lower().endswith(('.mid', '.midi')):
        return jsonify({"error": "File must be a MIDI file (.mid or .midi)"}), 400

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

        # Use Popen for better process control
        cmd = ['musescore3', '-o', xml_path, midi_path]

        # Start process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Create new process group
        )

        try:
            # Wait for completion with timeout
            stdout, stderr = process.communicate(timeout=30)

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error during conversion"
                return jsonify({
                    "error": "Conversion failed",
                    "details": error_msg
                }), 500

        except subprocess.TimeoutExpired:
            # Kill the entire process group
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            time.sleep(1)
            # Force kill if still alive
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except:
                pass
            return jsonify({"error": "Conversion timeout - file may be too large or complex"}), 500
        finally:
            # Ensure process is dead
            try:
                process.kill()
            except:
                pass

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

    except Exception as e:
        return jsonify({"error": f"Conversion error: {str(e)}"}), 500
    finally:
        # Cleanup
        def delayed_cleanup():
            time.sleep(5)
            try:
                if os.path.exists(temp_path):
                    shutil.rmtree(temp_path)
            except:
                pass

        cleanup = threading.Thread(target=delayed_cleanup, daemon=True)
        cleanup.start()


@app.route('/convert/info', methods=['GET'])
def convert_info():
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

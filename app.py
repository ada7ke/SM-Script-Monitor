import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

"""
 TODO:
 - cant find place warning
"""


from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from difflib import SequenceMatcher
from scipy.signal import butter, lfilter
import sounddevice as sd
import numpy as np
import whisper, queue, threading, time, re, string

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

SCRIPT_FILE = "testscript.txt" # CHANGE THIS TO YOUR SCRIPT FILE
CUELIST_FILE = "cuelist.txt" # CHANGE THIS TO YOUR CUELIST FILE

MODEL_SIZE = "tiny"
SAMPLE_RATE = 16000
CHUNK_DURATION = 1
OVERLAP_DURATION = 0.25
AUDIO_GAIN = 0

HEADS_UP_WORDS = 50
CONFIDENCE_THRESHOLD = 0.55
TRANSCRIBE_LANGUAGE = "en"

state_lock = threading.Lock()
state_version = 0
current_script_name = os.path.basename(SCRIPT_FILE)
current_cuelist_name = os.path.basename(CUELIST_FILE)

# audio processing
def apply_gain(audio, db=AUDIO_GAIN):
    factor = 10 ** (db / 20)
    audio = audio * factor
    return np.clip(audio, -1.0, 1.0).astype(np.float32)

def highpass_filter(audio, cutoff=100, fs=16000):
    b, a = butter(1, cutoff / (fs / 2), btype='high')
    return lfilter(b, a, audio).astype(np.float32)

def pre_emphasis(audio, coeff=0.97):
    emphasized = np.append(audio[0], audio[1:] - coeff * audio[:-1])
    return emphasized.astype(np.float32)

def noise_gate(audio, threshold=0.01):
    return np.where(np.abs(audio) < threshold, 0, audio).astype(np.float32)

def process_audio(audio):
    audio = audio.astype(np.float32)

    audio = apply_gain(audio, AUDIO_GAIN)
    audio = highpass_filter(audio)
    audio = pre_emphasis(audio)
    audio = noise_gate(audio)

    return audio.astype(np.float32)

# load files
def parse_script_text(text):
    words = text.replace("\n", " ").split()
    standby_markers = []

    for i, w in enumerate(words):
        match = re.match(r"\[SB(\d+)\]", w)
        if match:
            standby_markers.append((i, int(match.group(1))))

    return words, standby_markers, text

def load_script(file):
    with open(file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return parse_script_text(text)

def parse_cuelist_text(text):
    cue_map = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(r"^([A-Za-z]*)(\d+)\s*:\s*(.+)$", line)
        if not match:
            continue

        prefix, number, info = match.groups()
        number = int(number)
        label = f"{prefix}{number}" if prefix else str(number)
        cue_map[number] = (label, info.strip())

    return cue_map

def load_cuelist(file):
    with open(file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return parse_cuelist_text(text)

def build_cue_payload(cues):
    cue_entries = [cues[key] for key in sorted(cues.keys())]
    cue_lookup = {
        str(key): {"label": cues[key][0], "info": cues[key][1]}
        for key in cues
    }
    return cue_entries, cue_lookup

script_words, standby_markers, full_script = load_script(SCRIPT_FILE)
cue_map = load_cuelist(CUELIST_FILE)

# audio stream
audio_queue = queue.Queue()
monitoring_enabled = threading.Event()
monitoring_enabled.set()


def clear_audio_queue():
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata.copy())

def record_audio():
    while True:
        if not monitoring_enabled.is_set():
            time.sleep(0.1)
            continue

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32',
            callback=audio_callback
        ):
            while monitoring_enabled.is_set():
                time.sleep(0.05)

# match script
def normalize(text):
    translator = str.maketrans('', '', string.punctuation)
    return text.translate(translator).lower()

def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def find_best_match(transcribed_words, script_words, last_pos):
    window_size = len(transcribed_words)
    best_score = 0
    best_index = last_pos

    search_range = range(max(0, last_pos - 120), min(len(script_words), last_pos + 250))

    for i in search_range:
        script_slice = script_words[i:i+window_size]
        if len(script_slice) < window_size:
            continue

        score = similarity(" ".join(transcribed_words), " ".join(script_slice))

        if score > best_score:
            best_score = score
            best_index = i

    return best_index, best_score

# background worker
def background_worker():
    print("Loading Whisper model...")
    model = whisper.load_model(MODEL_SIZE)

    current_position = 0
    last_reminder = -1
    seen_version = -1

    threading.Thread(target=record_audio, daemon=True).start()

    rolling_audio = np.array([], dtype=np.float32)

    chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)
    overlap_samples = int(OVERLAP_DURATION * SAMPLE_RATE)

    while True:
        if not monitoring_enabled.is_set():
            rolling_audio = np.array([], dtype=np.float32)
            time.sleep(0.1)
            continue

        with state_lock:
            if seen_version != state_version:
                current_position = 0
                last_reminder = -1
                seen_version = state_version
            worker_script_words = script_words[:]
            worker_standby_markers = standby_markers[:]
            worker_cue_map = cue_map.copy()

        # accumulate audio
        while monitoring_enabled.is_set() and len(rolling_audio) < chunk_samples:
            if not audio_queue.empty():
                new_audio = audio_queue.get().flatten().astype(np.float32)
                rolling_audio = np.concatenate((rolling_audio, new_audio)).astype(np.float32)

        if not monitoring_enabled.is_set():
            rolling_audio = np.array([], dtype=np.float32)
            continue

        audio_np = rolling_audio[:chunk_samples].astype(np.float32)
        rolling_audio = rolling_audio[chunk_samples - overlap_samples:].astype(np.float32)

        audio_np = process_audio(audio_np)
        audio_np = audio_np.astype(np.float32)

        result = model.transcribe(
            audio_np,
            fp16=False,
            language=TRANSCRIBE_LANGUAGE,
            task="transcribe",
            condition_on_previous_text=False,
            verbose=False
        )

        text = result["text"].strip()
        if not text:
            continue

        print(f"Heard: {text}")
        socketio.emit("transcription", text)

        transcribed_words = text.split()

        # Keep live monitor responsive by showing short chunks,
        # but only run positional matching on longer phrases.
        if len(transcribed_words) < 3:
            socketio.emit("cue_update", "No upcoming cues...")
            time.sleep(0.05)
            continue

        # match
        new_pos, confidence = find_best_match(transcribed_words, worker_script_words, current_position)

        if confidence > CONFIDENCE_THRESHOLD:
            if abs(new_pos - current_position) < 80:
                current_position = new_pos

            print(f"Matched at {current_position} (conf={confidence:.2f})")
            socketio.emit("script_position", current_position)

        # cues
        message = "No upcoming cues..."

        for sb_index, sb_number in worker_standby_markers:
            if current_position < sb_index:
                distance = sb_index - current_position

                if distance <= HEADS_UP_WORDS:
                    if sb_number in worker_cue_map:
                        cue_label, cue_info = worker_cue_map[sb_number]
                        message = f"Reminder: SB{sb_number} in {distance} words\n{cue_label}: {cue_info}"
                    else:
                        message = f"Reminder: SB{sb_number} in {distance} words\n(No cue info found)"
                break

        socketio.emit("cue_update", message)

        time.sleep(0.05)


@socketio.on("connect")
def handle_connect():
    socketio.emit("monitoring_state", {"isMonitoring": monitoring_enabled.is_set()})


@socketio.on("toggle_monitoring")
def handle_toggle_monitoring():
    if monitoring_enabled.is_set():
        monitoring_enabled.clear()
        clear_audio_queue()
        socketio.emit("cue_update", "Monitoring paused")
    else:
        monitoring_enabled.set()
        socketio.emit("cue_update", "Monitoring active")

    socketio.emit("monitoring_state", {"isMonitoring": monitoring_enabled.is_set()})

# routes
@app.route("/")
def index():
    with state_lock:
        current_script = full_script
        cues_snapshot = cue_map.copy()
        script_name = current_script_name
        cuelist_name = current_cuelist_name

    cue_entries, cue_lookup = build_cue_payload(cues_snapshot)
    return render_template(
        "index.html",
        script=current_script,
        cue_entries=cue_entries,
        cue_lookup=cue_lookup,
        current_script_name=script_name,
        current_cuelist_name=cuelist_name
    )

@app.route("/import_txt", methods=["POST"])
def import_txt():
    global script_words, standby_markers, full_script, cue_map
    global current_script_name, current_cuelist_name, state_version

    import_type = request.form.get("import_type", "").strip().lower()
    uploaded = request.files.get("file")

    if import_type not in {"script", "cue"}:
        return jsonify({"ok": False, "error": "Invalid import type."}), 400

    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "No file selected."}), 400

    if not uploaded.filename.lower().endswith(".txt"):
        return jsonify({"ok": False, "error": "Only .txt files are supported."}), 400

    text = uploaded.stream.read().decode("utf-8", errors="ignore")
    if not text.strip():
        return jsonify({"ok": False, "error": "The selected file is empty."}), 400

    try:
        with state_lock:
            if import_type == "script":
                new_words, new_standby_markers, new_full_script = parse_script_text(text)
                script_words = new_words
                standby_markers = new_standby_markers
                full_script = new_full_script
                current_script_name = os.path.basename(uploaded.filename)
            else:
                cue_map = parse_cuelist_text(text)
                current_cuelist_name = os.path.basename(uploaded.filename)

            state_version += 1

            current_script = full_script
            cues_snapshot = cue_map.copy()
            script_name = current_script_name
            cuelist_name = current_cuelist_name
    except Exception as error:
        return jsonify({"ok": False, "error": f"Import failed: {error}"}), 400

    cue_entries, cue_lookup = build_cue_payload(cues_snapshot)

    return jsonify({
        "ok": True,
        "import_type": import_type,
        "script": current_script,
        "cue_entries": cue_entries,
        "cue_lookup": cue_lookup,
        "current_script_name": script_name,
        "current_cuelist_name": cuelist_name
    })

# run
if __name__ == "__main__":
    threading.Thread(target=background_worker, daemon=True).start()
    print("SERVER STARTING ON http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

# wrap text: alt + z
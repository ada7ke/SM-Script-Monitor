import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

"""
 TODO:
 - add ui
 - cant find place warning
 - convert image to text file
"""


from flask import Flask, render_template
from flask_socketio import SocketIO
from difflib import SequenceMatcher
from scipy.signal import butter, lfilter
import sounddevice as sd
import numpy as np
import whisper, queue, threading, time, re, string

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

SCRIPT_FILE = "testscript.txt"
CUELIST_FILE = "cuelist.txt"
MODEL_SIZE = "tiny"
SAMPLE_RATE = 16000

CHUNK_DURATION = 1
OVERLAP_DURATION = 0.25
AUDIO_GAIN = 0

HEADS_UP_WORDS = 50
CONFIDENCE_THRESHOLD = 0.55
TRANSCRIBE_LANGUAGE = "en"

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
def load_script(file):
    with open(file, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    words = text.replace("\n", " ").split()
    standby_markers = []

    for i, w in enumerate(words):
        match = re.match(r"\[SB(\d+)\]", w)
        if match:
            standby_markers.append((i, int(match.group(1))))

    return words, standby_markers, text

def load_cuelist(file):
    cue_map = {}

    with open(file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
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

script_words, standby_markers, full_script = load_script(SCRIPT_FILE)
cue_map = load_cuelist(CUELIST_FILE)

# audio stream
audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata.copy())

def record_audio():
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        callback=audio_callback
    ):
        while True:
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

    threading.Thread(target=record_audio, daemon=True).start()

    rolling_audio = np.array([], dtype=np.float32)

    chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)
    overlap_samples = int(OVERLAP_DURATION * SAMPLE_RATE)

    while True:
        # accumulate audio
        while len(rolling_audio) < chunk_samples:
            if not audio_queue.empty():
                new_audio = audio_queue.get().flatten().astype(np.float32)
                rolling_audio = np.concatenate((rolling_audio, new_audio)).astype(np.float32)

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

        if len(text.split()) < 3:
            continue

        print(f"Heard: {text}")
        socketio.emit("transcription", text)

        transcribed_words = text.split()

        # match
        new_pos, confidence = find_best_match(transcribed_words, script_words, current_position)

        if confidence > CONFIDENCE_THRESHOLD:
            if abs(new_pos - current_position) < 80:
                current_position = new_pos

            print(f"Matched at {current_position} (conf={confidence:.2f})")
            socketio.emit("script_position", current_position)

        # cues
        message = "No upcoming cues..."

        for sb_index, sb_number in standby_markers:
            if current_position < sb_index:
                distance = sb_index - current_position

                if distance <= HEADS_UP_WORDS:
                    if sb_number in cue_map:
                        cue_label, cue_info = cue_map[sb_number]
                        message = f"Reminder: SB{sb_number} in {distance} words\n{cue_label}: {cue_info}"
                    else:
                        message = f"Reminder: SB{sb_number} in {distance} words\n(No cue info found)"
                break

        socketio.emit("cue_update", message)

        time.sleep(0.05)

# routes
@app.route("/")
def index():
    cue_entries = [cue_map[key] for key in sorted(cue_map.keys())]
    return render_template("index.html", script=full_script, cue_entries=cue_entries)

# run
if __name__ == "__main__":
    threading.Thread(target=background_worker, daemon=True).start()
    print("SERVER STARTING ON http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

# wrap text: alt + z
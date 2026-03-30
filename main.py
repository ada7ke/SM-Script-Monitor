import whisper
import sounddevice as sd
import numpy as np
import queue
import threading
import time
from difflib import SequenceMatcher

# =========================
# CONFIG
# =========================
SCRIPT_FILE = "script.txt"
MODEL_SIZE = "base"   # tiny, base, small, medium
SAMPLE_RATE = 16000
CHUNK_DURATION = 3  # seconds of audio per inference
HEADS_UP_WORDS = 50
CONFIDENCE_THRESHOLD = 0.5

# =========================
# LOAD SCRIPT
# =========================
def load_script(file):
    with open(file, "r") as f:
        text = f.read()

    words = text.replace("\n", " ").split()
    cue_indices = []

    for i, w in enumerate(words):
        if "[CALL" in w:
            cue_indices.append(i)

    return words, cue_indices


script_words, cue_indices = load_script(SCRIPT_FILE)

# =========================
# AUDIO STREAM SETUP
# =========================
audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata.copy())

def record_audio():
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback):
        while True:
            time.sleep(0.1)

# =========================
# FUZZY MATCHING
# =========================
def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_match(transcribed_words, script_words, last_pos):
    window_size = len(transcribed_words)
    best_score = 0
    best_index = last_pos

    # Only search near last known position for stability
    search_range = range(max(0, last_pos - 100), min(len(script_words), last_pos + 200))

    for i in search_range:
        script_slice = script_words[i:i+window_size]
        if len(script_slice) < window_size:
            continue

        score = similarity(" ".join(transcribed_words), " ".join(script_slice))

        if score > best_score:
            best_score = score
            best_index = i

    return best_index, best_score

# =========================
# MAIN LOGIC
# =========================
def main():
    print("Loading Whisper model...")
    model = whisper.load_model(MODEL_SIZE)

    current_position = 0
    last_warning_triggered = -1

    print("Starting audio thread...")
    threading.Thread(target=record_audio, daemon=True).start()

    buffer = []

    while True:
        audio_chunk = []

        # Collect audio for CHUNK_DURATION seconds
        start_time = time.time()
        while time.time() - start_time < CHUNK_DURATION:
            if not audio_queue.empty():
                audio_chunk.append(audio_queue.get())

        if not audio_chunk:
            continue

        audio_np = np.concatenate(audio_chunk, axis=0).flatten()

        # Transcribe
        result = model.transcribe(audio_np, fp16=False)
        text = result["text"].strip()

        if not text:
            continue

        print(f"\nHeard: {text}")

        transcribed_words = text.split()

        # Find best match in script
        new_pos, confidence = find_best_match(transcribed_words, script_words, current_position)

        if confidence > CONFIDENCE_THRESHOLD:
            current_position = new_pos
            print(f"Matched at word index {current_position} (confidence={confidence:.2f})")

        # Check for upcoming cues
        for cue_index in cue_indices:
            if current_position < cue_index and (cue_index - current_position) <= HEADS_UP_WORDS:
                if cue_index != last_warning_triggered:
                    print("\n==============================")
                    print("⚠️ HEADS UP: Cue coming soon!")
                    snippet_start = max(0, cue_index - HEADS_UP_WORDS)
                    snippet = " ".join(script_words[snippet_start:cue_index])
                    print(snippet)
                    print("==============================\n")
                    last_warning_triggered = cue_index

# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()
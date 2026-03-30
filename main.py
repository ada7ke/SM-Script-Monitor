import whisper
import sounddevice as sd
import numpy as np
import queue
import threading
import time
import re
from difflib import SequenceMatcher


SCRIPT_FILE = "script.txt"
CUELIST_FILE = "cuelist.txt"
MODEL_SIZE = "base"   # tiny, base, small, medium
SAMPLE_RATE = 16000
CHUNK_DURATION = 3  # seconds of audio per inference
HEADS_UP_WORDS = 50
CONFIDENCE_THRESHOLD = 0.5

def load_script(file):
    with open(file, "r") as f:
        text = f.read()

    words = text.replace("\n", " ").split()
    standby_markers = []

    for i, w in enumerate(words):
        match = re.match(r"\[SB(\d+)\]", w)
        if match:
            standby_markers.append((i, int(match.group(1))))

    return words, standby_markers

def load_cuelist(file):
    cue_map = {}

    with open(file, "r") as f:
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


script_words, standby_markers = load_script(SCRIPT_FILE)
cue_map = load_cuelist(CUELIST_FILE)

# setup audio stream
audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata.copy())

def record_audio():
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback):
        while True:
            time.sleep(0.1)

# match words
def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_match(transcribed_words, script_words, last_pos):
    window_size = len(transcribed_words)
    best_score = 0
    best_index = last_pos

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


def main():
    print("Loading Whisper model...")
    model = whisper.load_model(MODEL_SIZE)

    current_position = 0
    last_warning_triggered = -1

    print("Starting audio thread...")
    threading.Thread(target=record_audio, daemon=True).start()

    buffer = []

    while True:
        # get audio chunk
        audio_chunk = []
        start_time = time.time()
        while time.time() - start_time < CHUNK_DURATION:
            if not audio_queue.empty():
                audio_chunk.append(audio_queue.get())
        if not audio_chunk:
            continue
        audio_np = np.concatenate(audio_chunk, axis=0).flatten()

        # transcribe
        result = model.transcribe(audio_np, fp16=False)
        text = result["text"].strip()
        if not text:
            continue
        print(f"Heard: {text}")
        transcribed_words = text.split()

        # find best match in script
        new_pos, confidence = find_best_match(transcribed_words, script_words, current_position)

        if confidence > CONFIDENCE_THRESHOLD:
            current_position = new_pos
            print(f"Matched at word index {current_position} (confidence={confidence:.2f})")

        # check for upcoming SB markers
        for sb_index, sb_number in standby_markers:
            if current_position < sb_index and (sb_index - current_position) <= HEADS_UP_WORDS:
                if sb_index != last_warning_triggered:
                    print("\n==============================")
                    print(f"WARNING: SB{sb_number} in {sb_index - current_position} words")

                    if sb_number in cue_map:
                        cue_label, cue_info = cue_map[sb_number]
                        print(f"{cue_label}: {cue_info}")
                    else:
                        print(f"{sb_number}: not found in {CUELIST_FILE}")

                    print("==============================\n")
                    last_warning_triggered = sb_index

main()
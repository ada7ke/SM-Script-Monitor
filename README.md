# Stage Manager Script Monitor
A real-time monitor that listens to live audio, transcribes dialogue, and tracks the current position within a script. It highlights the active section, and provides early warnings for upcoming cues based on script markers.

## Installation
#### 1. Clone or download project

    git clone <your-repo-url>
    
    cd <project-folder>
    
#### 2. Install Python Dependencies
    pip install flask flask-socketio eventlet openai-whisper sounddevice numpy scipy

#### 3. Install FFmpeg
- macOS: ```brew install ffmpeg```
- Ubuntu: ```sudo apt install ffmpeg```
- Windows: download from https://www.gyan.dev/ffmpeg/builds/
 and add to PATH

 #### 4. Prepare Files
* Place your script in a .txt file
* Add stand by and cue markers with the formal [SB#] or [Q#]
* Create a cuelist.txt with call descriptions

## Usage
* Run the server ```python app.py```
* Open the UI
   * Go to: ```http://localhost:5000```
* The app will begin listening through your microphone
* Live transcription appears on the right
* Script position updates automatically on the left
* Cue warnings show at the bottom
* Mute button on top right toggles live listening
* Import button on top left allows you to import new scripts or cue lists

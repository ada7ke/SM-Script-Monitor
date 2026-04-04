const socket = io();

const scriptDiv = document.getElementById("script");
const transcriptDiv = document.getElementById("transcript");
const terminalDiv = document.getElementById("terminal");
const cueListDiv = document.getElementById("cue-list");

let scriptWords = scriptDiv.innerText.split(" ");

// Initialize terminal status message
terminalDiv.innerText = "No upcoming cues...";

socket.on("transcription", (text) => {
    console.log("TRANSCRIPTION:", text);
    transcriptDiv.innerText += (transcriptDiv.innerText ? "\n" : "") + text;
    transcriptDiv.scrollTop = transcriptDiv.scrollHeight;
});

socket.on("script_position", (pos) => {
    let words = scriptWords;

    // rebuild with highlight
    let html = words.map((w, i) => {
        if (i < pos) {
            return `<span class="past">${w}</span>`;
        }
        if (i >= pos && i < pos + 5) {
            return `<span class="highlight">${w}</span>`;
        }
        return w;
    }).join(" ");

    scriptDiv.innerHTML = html;

    // auto scroll
    let percent = pos / words.length;
    let target = scriptDiv.scrollHeight * percent;
    let offset = scriptDiv.clientHeight * 0.33;

    scriptDiv.scrollTop = Math.max(0, target - offset);
});

socket.on("cue_update", (msg) => {
    terminalDiv.innerText = msg;
});
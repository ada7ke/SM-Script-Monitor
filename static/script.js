const socket = io();

const scriptDiv = document.getElementById("script");
const transcriptDiv = document.getElementById("transcript");
const bottomDiv = document.getElementById("bottom");

let scriptWords = scriptDiv.innerText.split(" ");

socket.on("transcription", (text) => {
    console.log("TRANSCRIPTION:", text);
    transcriptDiv.innerText += (transcriptDiv.innerText ? "\n" : "") + text;
    transcriptDiv.scrollTop = transcriptDiv.scrollHeight;
});

socket.on("script_position", (pos) => {
    let words = scriptWords;

    // rebuild with highlight
    let html = words.map((w, i) => {
        if (i >= pos && i < pos + 5) {
            return `<span class="highlight">${w}</span>`;
        }
        return w;
    }).join(" ");

    scriptDiv.innerHTML = html;

    // auto scroll
    let percent = pos / words.length;
    scriptDiv.scrollTop = scriptDiv.scrollHeight * percent;
});

socket.on("cue_update", (msg) => {
    bottomDiv.innerText = msg;
});
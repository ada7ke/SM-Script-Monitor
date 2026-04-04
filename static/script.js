const socket = io();

const scriptDiv = document.getElementById("script");
const transcriptDiv = document.getElementById("transcript");
const terminalDiv = document.getElementById("terminal");
const cueListDiv = document.getElementById("cue-list");
const monitorToggleBtn = document.getElementById("monitor-toggle");
const cueLookupDataEl = document.getElementById("cue-lookup-data");
let cueLookup = {};

if (cueLookupDataEl) {
    try {
        cueLookup = JSON.parse(cueLookupDataEl.textContent || "{}");
    } catch (error) {
        cueLookup = {};
    }
}

const markerRegex = /^\[(SB|Q)\d+\]$/i;
let scriptWords = scriptDiv.innerText.split(/\s+/).filter(Boolean);
let activeMarker = null;

const cueTooltip = document.createElement("div");
cueTooltip.id = "cue-tooltip";
cueTooltip.className = "hidden";
document.body.appendChild(cueTooltip);

function updateTooltipPosition(markerEl) {
    const rect = markerEl.getBoundingClientRect();
    const tooltipWidth = cueTooltip.offsetWidth || 240;
    const left = Math.min(
        Math.max(8, rect.left),
        window.innerWidth - tooltipWidth - 8
    );

    cueTooltip.style.left = `${left}px`;
    cueTooltip.style.top = `${rect.bottom + 8}px`;
}

function showCueTooltip(markerEl) {
    const markerNumber = markerEl.getAttribute("data-cue-number");
    const markerLabel = markerEl.getAttribute("data-cue-label") || "Cue";
    const numericKey = String(Number(markerNumber));
    const cue = cueLookup[numericKey];

    if (cue) {
        cueTooltip.innerHTML = `<strong>${markerLabel}</strong><br><strong>${cue.label}:</strong> ${cue.info}`;
    } else {
        cueTooltip.innerHTML = `<strong>${markerLabel}</strong><br><em>No cue found</em>`;
    }

    cueTooltip.classList.remove("hidden");
    updateTooltipPosition(markerEl);
}

function hideCueTooltip() {
    cueTooltip.classList.add("hidden");
}

function formatScriptWord(word) {
    const match = word.match(/^\[([A-Z]+)(\d+)\]$/i);
    if (match) {
        const markerPrefix = match[1].toUpperCase();
        const markerNumber = match[2];
        const markerLabel = `${markerPrefix}${markerNumber}`;

        return `<span class="cue-marker" data-cue-number="${markerNumber}" data-cue-label="${markerLabel}"><strong>${word}</strong></span>`;
    }
    return word;
}

function renderScript(pos = null) {
    const html = scriptWords.map((w, i) => {
        const displayWord = formatScriptWord(w);

        if (pos !== null && i < pos) {
            return `<span class="past">${displayWord}</span>`;
        }
        if (pos !== null && i >= pos && i < pos + 5) {
            return `<span class="highlight">${displayWord}</span>`;
        }
        return displayWord;
    }).join(" ");

    scriptDiv.innerHTML = html;

    if (pos !== null) {
        // auto scroll
        let percent = pos / scriptWords.length;
        let target = scriptDiv.scrollHeight * percent;
        let offset = scriptDiv.clientHeight * 0.33;

        scriptDiv.scrollTop = Math.max(0, target - offset);
    }
}

// Initial render so markers are bold before first position update.
renderScript();

// Initialize terminal status message
terminalDiv.innerText = "No upcoming cues...";

function updateMonitoringButton(isMonitoring) {
    monitorToggleBtn.classList.toggle("is-on", isMonitoring);
    monitorToggleBtn.classList.toggle("is-off", !isMonitoring);
    monitorToggleBtn.setAttribute("aria-pressed", String(isMonitoring));
    monitorToggleBtn.title = isMonitoring ? "Stop monitoring" : "Start monitoring";
}

monitorToggleBtn.addEventListener("click", () => {
    socket.emit("toggle_monitoring");
});

scriptDiv.addEventListener("mouseover", (event) => {
    const markerEl = event.target.closest(".cue-marker");
    if (!markerEl || !scriptDiv.contains(markerEl)) {
        return;
    }

    activeMarker = markerEl;
    showCueTooltip(markerEl);
});

scriptDiv.addEventListener("mouseout", (event) => {
    const markerEl = event.target.closest(".cue-marker");
    if (!markerEl) {
        return;
    }

    const related = event.relatedTarget;
    if (related && markerEl.contains(related)) {
        return;
    }

    activeMarker = null;
    hideCueTooltip();
});

scriptDiv.addEventListener("mousemove", () => {
    if (activeMarker) {
        updateTooltipPosition(activeMarker);
    }
});

window.addEventListener("scroll", () => {
    if (activeMarker) {
        updateTooltipPosition(activeMarker);
    }
}, true);

window.addEventListener("resize", () => {
    if (activeMarker) {
        updateTooltipPosition(activeMarker);
    }
});

socket.on("transcription", (text) => {
    transcriptDiv.innerText += (transcriptDiv.innerText ? "\n" : "") + text;
    transcriptDiv.scrollTop = transcriptDiv.scrollHeight;
});

socket.on("script_position", (pos) => {
    renderScript(pos);
});

socket.on("cue_update", (msg) => {
    terminalDiv.innerText = msg;
});

socket.on("monitoring_state", (payload) => {
    updateMonitoringButton(Boolean(payload && payload.isMonitoring));
});
// accessibility_and_audio_bridge.js - WhatsApp Web Access & Audio Quality Bridge

(function() {
    console.log("WhatsApp Audio Quality Bridge: Initializing...");

    // Override WebRTC constraints to disable compression/filters and request raw high-quality audio
    function overrideConstraints(constraints) {
        if (constraints && constraints.audio) {
            if (typeof constraints.audio === 'boolean') {
                constraints.audio = {};
            }
            
            constraints.audio.echoCancellation = false;
            constraints.audio.noiseSuppression = false;
            constraints.audio.autoGainControl = false;
            constraints.audio.googEchoCancellation = false;
            constraints.audio.googAutoGainControl = false;
            constraints.audio.googNoiseSuppression = false;
            constraints.audio.googTypingNoiseDetection = false;
            constraints.audio.googAudioMirroring = false;
            constraints.audio.channelCount = { ideal: 1 }; // Force mono to prevent WhatsApp encoder crashes
            constraints.audio.sampleRate = { ideal: 48000 };
            constraints.audio.sampleSize = { ideal: 24 };
            constraints.audio.latency = 0;
            
            console.log("WhatsApp Audio Quality Bridge: Applied overrides.", constraints.audio);
        }
        return constraints;
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = async function(constraints) {
            return originalGetUserMedia(overrideConstraints(constraints));
        };
    }

    if (navigator.getUserMedia) {
        const originalLegacy = navigator.getUserMedia.bind(navigator);
        navigator.getUserMedia = function(constraints, success, error) {
            return originalLegacy(overrideConstraints(constraints), success, error);
        };
    }
    
    if (window.navigator && window.navigator.getUserMedia) {
        const originalWinLegacy = window.navigator.getUserMedia.bind(window.navigator);
        window.navigator.getUserMedia = function(constraints, success, error) {
            return originalWinLegacy(overrideConstraints(constraints), success, error);
        };
    }

    if (typeof MediaStreamTrack !== 'undefined' && MediaStreamTrack.prototype.applyConstraints) {
        const originalApplyConstraints = MediaStreamTrack.prototype.applyConstraints;
        MediaStreamTrack.prototype.applyConstraints = async function(constraints) {
            return originalApplyConstraints.call(this, overrideConstraints(constraints));
        };
    }

    // Intercept Opus Web Worker initialization to force studio quality parameters
    const originalWorkerPostMessage = window.Worker.prototype.postMessage;
    window.Worker.prototype.postMessage = function(payload, transfer) {
        let innerMessage = payload;
        if (payload && payload.type === 'message' && payload.message) {
            innerMessage = payload.message;
        }

        if (innerMessage && typeof innerMessage === 'object' && innerMessage.command === 'encode-init') {
            if (innerMessage.config) {
                innerMessage.config.encoderSampleRate = 48000;
                innerMessage.config.bitRate = 128000;
                console.log("WhatsApp Audio Quality Bridge: Opus encoder forced to 48kHz, 128kbps.");
            }
        }
        return originalWorkerPostMessage.call(this, payload, transfer);
    };

})();

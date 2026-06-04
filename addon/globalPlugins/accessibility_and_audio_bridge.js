// accessibility_and_audio_bridge.js - El script de inyección principal

(function() {
    console.log("WhatsApp Web Access & Audio Control: Inicializando Bridge en MUNDO MAIN...");

    // ==========================================
    // 1. SECCIÓN AUDIO: Secuestro de getUserMedia
    // ==========================================
    
    // Sobrescribimos el objeto mediaDevices nativo del navegador antes de que Meta pueda usarlo.
    function overrideConstraints(constraints) {
        if (constraints && constraints.audio) {
            if (typeof constraints.audio === 'boolean') {
                constraints.audio = {};
            }
            
            // ==========================================
            // EXTREME AUDIO QUALITY OVERRIDES
            // ==========================================
            constraints.audio.echoCancellation = false;
            constraints.audio.noiseSuppression = false;
            constraints.audio.autoGainControl = false;
            constraints.audio.googEchoCancellation = false;
            constraints.audio.googAutoGainControl = false;
            constraints.audio.googNoiseSuppression = false;
            constraints.audio.googTypingNoiseDetection = false;
            constraints.audio.googAudioMirroring = false;
            constraints.audio.channelCount = { ideal: 1 }; // Forzar mono para no crashear el renderizador de WhatsApp
            constraints.audio.sampleRate = { ideal: 48000 };
            constraints.audio.sampleSize = { ideal: 24 };
            constraints.audio.latency = 0;
            
            console.log("WhatsApp Web Access & Audio Control: Restricciones anuladas. Se entregará Audio Crudo.", constraints.audio);
        }
        return constraints;
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = async function(constraints) {
            console.log("WhatsApp Web Access & Audio Control: Interceptando mediaDevices.getUserMedia...");
            
            // Buscar la URL completa en los scripts cargados en la página
            const scripts = Array.from(document.querySelectorAll('script'));
            let targetScriptUrl = scripts.find(s => s.src && s.src.includes('qc5NimR'))?.src;
            
            if (!targetScriptUrl) {
                // Si no está en el DOM, buscar en los recursos cargados por la red
                const resources = performance.getEntriesByType("resource");
                const targetResource = resources.find(r => r.name.includes('qc5NimR'));
                if (targetResource) targetScriptUrl = targetResource.name;
            }

            if (targetScriptUrl) {
                console.log("¡ENCONTRADO! URL COMPLETA DEL SCRIPT:", targetScriptUrl.replace("https://", "hxxps_"));
            } else {
                console.log("Script no encontrado en la página ni en la red.");
            }
            
            return originalGetUserMedia(overrideConstraints(constraints));
        };
    }

    // WhatsApp también usa APIs legacy para compatibilidad
    if (navigator.getUserMedia) {
        const originalLegacy = navigator.getUserMedia.bind(navigator);
        navigator.getUserMedia = function(constraints, success, error) {
            console.log("WhatsApp Web Access & Audio Control: Interceptando navigator.getUserMedia (legacy)...");
            console.log("Origen de la llamada (Stack Trace):", new Error().stack);
            return originalLegacy(overrideConstraints(constraints), success, error);
        };
    }
    
    // Y el alias en window
    if (window.navigator && window.navigator.getUserMedia) {
        const originalWinLegacy = window.navigator.getUserMedia.bind(window.navigator);
        window.navigator.getUserMedia = function(constraints, success, error) {
            console.log("WhatsApp Web Access & Audio Control: Interceptando window.navigator.getUserMedia (legacy)...");
            console.log("Origen de la llamada (Stack Trace):", new Error().stack);
            return originalWinLegacy(overrideConstraints(constraints), success, error);
        };
    }

    // 1.1 Interceptar applyConstraints (por si intentan degradar la calidad después de obtener el micrófono)
    if (typeof MediaStreamTrack !== 'undefined' && MediaStreamTrack.prototype.applyConstraints) {
        const originalApplyConstraints = MediaStreamTrack.prototype.applyConstraints;
        MediaStreamTrack.prototype.applyConstraints = async function(constraints) {
            console.log("WhatsApp Web Access & Audio Control: Interceptando applyConstraints...");
            return originalApplyConstraints.call(this, overrideConstraints(constraints));
        };
    }



    // ==========================================
    // 3. SECCIÓN ALTA FIDELIDAD: Intercepción del Codificador Opus
    // ==========================================
    // Interceptar los mensajes enviados al Web Worker de Opus
    const originalWorkerPostMessage = window.Worker.prototype.postMessage;
    window.Worker.prototype.postMessage = function(payload, transfer) {
        // WhatsApp envuelve los mensajes en { type: "message", message: { command: ... } }
        let innerMessage = payload;
        if (payload && payload.type === 'message' && payload.message) {
            innerMessage = payload.message;
        }

        if (innerMessage && typeof innerMessage === 'object' && innerMessage.command === 'encode-init') {
            console.log("WhatsApp Web Access & Audio Control: ¡Interceptada la inicialización del codificador Opus!");
            console.log("Configuración original de Meta:", JSON.stringify(innerMessage.config));
            
            // Forzar Alta Fidelidad
            if (innerMessage.config) {
                innerMessage.config.encoderSampleRate = 48000; // Calidad de estudio (48kHz)
                innerMessage.config.bitRate = 128000;          // Bitrate alto (128kbps)
                console.log("WhatsApp Web Access & Audio Control: Configuración modificada a Alta Fidelidad (48kHz, 128kbps).");
            }
        }
        return originalWorkerPostMessage.call(this, payload, transfer);
    };

})();

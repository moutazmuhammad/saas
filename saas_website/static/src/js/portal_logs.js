/**
 * Portal Live Logs Viewer
 * Connects to the SSE log streaming endpoint and displays real-time container output.
 */
(function() {
    'use strict';

    function initLogViewer() {
        var logContainer = document.getElementById('log-output');
        if (!logContainer) return;

        var streamUrl = logContainer.dataset.streamUrl;
        if (!streamUrl) return;

        var paused = false;
        var source = null;
        var maxLines = 2000;

        var pauseBtn = document.getElementById('logs-pause-btn');
        var clearBtn = document.getElementById('logs-clear-btn');

        function isScrolledToBottom() {
            return logContainer.scrollHeight - logContainer.scrollTop - logContainer.clientHeight < 30;
        }

        function appendLine(text) {
            if (paused) return;
            var wasAtBottom = isScrolledToBottom();
            var div = document.createElement('div');
            div.className = 'log-line';
            div.textContent = text;
            logContainer.appendChild(div);

            while (logContainer.children.length > maxLines) {
                logContainer.removeChild(logContainer.firstChild);
            }

            // Only auto-scroll if user was already at the bottom
            if (wasAtBottom) {
                logContainer.scrollTop = logContainer.scrollHeight;
            }
        }

        function connect() {
            logContainer.innerHTML = '';
            appendLine('--- Connecting to log stream... ---');

            try {
                source = new EventSource(streamUrl + '?tail=200');
            } catch (e) {
                appendLine('--- Failed to connect: ' + e.message + ' ---');
                return;
            }

            source.onopen = function() {
                // Clear the connecting message once connected
                logContainer.innerHTML = '';
                appendLine('--- Connected ---');
            };

            source.onmessage = function(e) {
                try {
                    var data = JSON.parse(e.data);
                    if (typeof data === 'string') {
                        appendLine(data);
                    } else if (data.line) {
                        appendLine(data.line);
                    } else if (data.text) {
                        appendLine(data.text);
                    } else {
                        appendLine(e.data);
                    }
                } catch (err) {
                    appendLine(e.data);
                }
            };

            source.addEventListener('done', function() {
                appendLine('--- Stream ended ---');
                source.close();
            });

            source.addEventListener('error', function() {
                appendLine('--- Stream error ---');
                source.close();
            });

            source.onerror = function() {
                if (source.readyState === EventSource.CLOSED) {
                    appendLine('--- Connection closed ---');
                } else if (source.readyState === EventSource.CONNECTING) {
                    // EventSource auto-reconnects, let it try
                } else {
                    appendLine('--- Connection lost ---');
                    source.close();
                }
            };
        }

        if (pauseBtn) {
            pauseBtn.addEventListener('click', function() {
                paused = !paused;
                if (paused) {
                    pauseBtn.innerHTML = '<i class="fas fa-play me-1"></i>Resume';
                } else {
                    pauseBtn.innerHTML = '<i class="fas fa-pause me-1"></i>Pause';
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', function() {
                logContainer.innerHTML = '';
            });
        }

        connect();
    }

    // Run immediately if DOM is ready, otherwise wait
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initLogViewer);
    } else {
        initLogViewer();
    }
})();

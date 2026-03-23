/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

/**
 * Dynamically load xterm.js + fit addon from CDN.
 * Returns { Terminal, FitAddon } once loaded.
 */
let _xtermPromise = null;
function loadXterm() {
    if (_xtermPromise) return _xtermPromise;
    _xtermPromise = new Promise((resolve, reject) => {
        // Load CSS
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css";
        document.head.appendChild(link);

        // Load xterm.js
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js";
        script.onload = () => {
            // Load fit addon
            const fitScript = document.createElement("script");
            fitScript.src = "https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js";
            fitScript.onload = () => {
                resolve({
                    Terminal: window.Terminal,
                    FitAddon: window.FitAddon,
                });
            };
            fitScript.onerror = reject;
            document.head.appendChild(fitScript);
        };
        script.onerror = reject;
        document.head.appendChild(script);
    });
    return _xtermPromise;
}

class SshTerminal extends Component {
    static template = "saas_core.SshTerminal";
    static props = ["*"];

    setup() {
        this.actionService = useService("action");
        this.state = useState({
            connected: false,
            connecting: true,
            error: null,
            serverName: "",
        });
        this.termRef = useRef("terminalContainer");
        this.terminal = null;
        this.fitAddon = null;
        this.eventSource = null;
        this.sessionId = null;
        this._resizeObserver = null;

        const ctx = this.props.action.context || {};
        this.serverModel = ctx.server_model;
        this.serverId = ctx.server_id;
        this.state.serverName = ctx.server_name || "Server";

        onMounted(() => this._init());
        onWillUnmount(() => this._destroy());
    }

    async _init() {
        try {
            // Load xterm.js
            const { Terminal, FitAddon } = await loadXterm();

            // Create terminal instance
            this.terminal = new Terminal({
                cursorBlink: true,
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
                theme: {
                    background: "#1e1e2e",
                    foreground: "#cdd6f4",
                    cursor: "#f5e0dc",
                    selectionBackground: "#585b70",
                    black: "#45475a",
                    red: "#f38ba8",
                    green: "#a6e3a1",
                    yellow: "#f9e2af",
                    blue: "#89b4fa",
                    magenta: "#f5c2e7",
                    cyan: "#94e2d5",
                    white: "#bac2de",
                    brightBlack: "#585b70",
                    brightRed: "#f38ba8",
                    brightGreen: "#a6e3a1",
                    brightYellow: "#f9e2af",
                    brightBlue: "#89b4fa",
                    brightMagenta: "#f5c2e7",
                    brightCyan: "#94e2d5",
                    brightWhite: "#a6adc8",
                },
            });

            this.fitAddon = new FitAddon.FitAddon();
            this.terminal.loadAddon(this.fitAddon);

            // Attach to DOM
            this.terminal.open(this.termRef.el);
            this.fitAddon.fit();

            // Handle user input -> send to server
            this.terminal.onData((data) => {
                if (this.sessionId && this.state.connected) {
                    this._sendInput(data);
                }
            });

            // Handle resize
            this.terminal.onResize(({ cols, rows }) => {
                if (this.sessionId && this.state.connected) {
                    this._sendResize(cols, rows);
                }
            });

            // Watch container size changes
            this._resizeObserver = new ResizeObserver(() => {
                if (this.fitAddon) {
                    try { this.fitAddon.fit(); } catch {}
                }
            });
            this._resizeObserver.observe(this.termRef.el);

            this.terminal.write("Connecting to " + this.state.serverName + "...\r\n");

            // Create SSH session
            await this._createSession();

        } catch (e) {
            this.state.connecting = false;
            this.state.error = e.message || String(e);
        }
    }

    async _createSession() {
        try {
            const result = await rpc("/saas/terminal/create", {
                server_model: this.serverModel,
                server_id: this.serverId,
            });

            this.sessionId = result.session_id;
            this.state.connected = true;
            this.state.connecting = false;

            // Start output stream
            this._startOutputStream();

            // Focus terminal
            this.terminal.focus();

            // Send initial resize
            const { cols, rows } = this.terminal;
            this._sendResize(cols, rows);

        } catch (e) {
            this.state.connecting = false;
            const msg = (e.data && e.data.message) || e.message || String(e);
            this.state.error = msg;
            if (this.terminal) {
                this.terminal.write("\r\n\x1b[31mConnection failed: " + msg + "\x1b[0m\r\n");
            }
        }
    }

    _startOutputStream() {
        if (this.eventSource) {
            this.eventSource.close();
        }

        const url = `/saas/terminal/output/${this.sessionId}`;
        this.eventSource = new EventSource(url);

        this.eventSource.onmessage = (event) => {
            // Data is base64-encoded
            const encoded = JSON.parse(event.data);
            const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
            const text = new TextDecoder().decode(bytes);
            this.terminal.write(text);
        };

        this.eventSource.addEventListener("closed", () => {
            this.state.connected = false;
            if (this.terminal) {
                this.terminal.write("\r\n\x1b[33mSession ended.\x1b[0m\r\n");
            }
            this._stopOutputStream();
        });

        this.eventSource.addEventListener("timeout", () => {
            // Reconnect on stream timeout (the session is still alive)
            this._stopOutputStream();
            if (this.sessionId && this.state.connected) {
                this._startOutputStream();
            }
        });

        this.eventSource.addEventListener("error", (event) => {
            if (event.data) {
                this.state.error = JSON.parse(event.data);
            }
            this.state.connected = false;
            this._stopOutputStream();
        });

        this.eventSource.onerror = () => {
            // EventSource built-in reconnection will handle transient errors.
            // If it fails permanently, mark disconnected.
            if (this.eventSource && this.eventSource.readyState === EventSource.CLOSED) {
                this.state.connected = false;
            }
        };
    }

    _stopOutputStream() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }

    async _sendInput(data) {
        try {
            const result = await rpc("/saas/terminal/input", {
                session_id: this.sessionId,
                data: data,
            });
            if (result.status === "closed") {
                this.state.connected = false;
                this.terminal.write("\r\n\x1b[33mSession closed.\x1b[0m\r\n");
            }
        } catch {
            // Silently ignore transient input errors to avoid flooding
        }
    }

    async _sendResize(cols, rows) {
        try {
            await rpc("/saas/terminal/resize", {
                session_id: this.sessionId,
                cols: cols,
                rows: rows,
            });
        } catch {
            // Ignore resize errors
        }
    }

    async _destroy() {
        this._stopOutputStream();

        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }

        if (this.terminal) {
            this.terminal.dispose();
            this.terminal = null;
        }

        // Close server-side session
        if (this.sessionId) {
            try {
                await rpc("/saas/terminal/close", {
                    session_id: this.sessionId,
                });
            } catch {
                // Best effort cleanup
            }
            this.sessionId = null;
        }
    }

    async onReconnect() {
        this.state.error = null;
        this.state.connecting = true;

        // Close old session
        if (this.sessionId) {
            try {
                await rpc("/saas/terminal/close", {
                    session_id: this.sessionId,
                });
            } catch {}
            this.sessionId = null;
        }
        this._stopOutputStream();

        if (this.terminal) {
            this.terminal.clear();
            this.terminal.write("Reconnecting to " + this.state.serverName + "...\r\n");
        }

        await this._createSession();
    }

    onDisconnect() {
        this._destroy();
        this.state.connected = false;
        if (this.terminal) {
            this.terminal.write("\r\n\x1b[33mDisconnected.\x1b[0m\r\n");
        }
    }
}

registry.category("actions").add("ssh_terminal", SshTerminal);

/**
 * CloudOdoo - Frontend Interaction JavaScript
 * Handles client-side interactions for the SaaS website.
 * All data comes from server-rendered QWeb templates.
 */

// ============================================
// Utility Functions
// ============================================

const CloudOdoo = {
    // Debounce function
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Show toast notification
    showToast(message, type = 'info') {
        let container = document.getElementById('co-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'co-toast-container';
            container.style.cssText = 'position:fixed;top:100px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;';
            document.body.appendChild(container);
        }
        const iconMap = { success: 'check-circle', error: 'exclamation-circle', info: 'info-circle' };
        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type} fade-in`;
        toast.innerHTML = `<i class="fas fa-${iconMap[type] || 'info-circle'}"></i><span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    },

    // Format currency
    formatCurrency(amount, currency) {
        currency = currency || 'USD';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currency,
            minimumFractionDigits: 0,
            maximumFractionDigits: 2
        }).format(amount);
    },

    // Format storage (MB to human readable)
    formatStorage(mb) {
        if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB';
        return mb + ' MB';
    },

    // Show styled confirmation modal (programmatic use)
    showConfirm(message, variant, yesText, onConfirm) {
        initConfirmModals();
        _coSetupModal(message, variant, yesText, 'No, keep it', onConfirm);
    },

    // Get CSRF token from the page
    getCsrfToken() {
        const el = document.querySelector('input[name="csrf_token"]');
        return el ? el.value : '';
    },

    // Odoo JSON-RPC call
    jsonRpc(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jsonrpc: '2.0',
                id: Math.floor(Math.random() * 1000000),
                method: 'call',
                params: params || {},
            }),
        })
        .then(r => r.json())
        .then(data => {
            if (data.error) throw new Error(data.error.data?.message || data.error.message || 'Server error');
            return data.result;
        });
    },
};

// ============================================
// Theme Toggle (Dark/Light)
// ============================================

function initThemeToggle() {
    var saved = localStorage.getItem('co-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);

    var toggle = document.getElementById('themeToggle');
    var icon = document.getElementById('themeIcon');
    if (!toggle || !icon) return;

    function updateIcon(theme) {
        // Show sun icon in dark mode (click to go light), moon in light mode (click to go dark)
        icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }

    updateIcon(saved);

    toggle.addEventListener('click', function() {
        var current = document.documentElement.getAttribute('data-theme') || 'dark';
        var next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('co-theme', next);
        updateIcon(next);
    });
}

// ============================================
// Billing Toggle (Plans Page)
// ============================================

function initBillingToggle() {
    const toggle = document.getElementById('billing-toggle');
    if (!toggle) return;

    toggle.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            toggle.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const billing = btn.dataset.billing;

            // Toggle visibility of monthly/yearly prices
            document.querySelectorAll('[data-monthly-price]').forEach(el => {
                const monthly = parseFloat(el.dataset.monthlyPrice) || 0;
                const yearly = parseFloat(el.dataset.yearlyPrice) || 0;
                const currency = el.dataset.currency || 'USD';
                const amountEl = el.querySelector('.plan-amount');
                const periodEl = el.querySelector('.plan-period');
                if (!amountEl || !periodEl) return;

                if (billing === 'yearly' && yearly > 0) {
                    const perMonth = yearly / 12;
                    amountEl.textContent = CloudOdoo.formatCurrency(perMonth, currency);
                    periodEl.textContent = '/mo (billed yearly)';
                    const origEl = el.querySelector('.plan-original');
                    if (origEl) {
                        origEl.style.display = perMonth < monthly ? '' : 'none';
                        origEl.textContent = CloudOdoo.formatCurrency(monthly, currency);
                    }
                } else {
                    amountEl.textContent = CloudOdoo.formatCurrency(monthly, currency);
                    periodEl.textContent = '/mo';
                    const origEl = el.querySelector('.plan-original');
                    if (origEl) origEl.style.display = 'none';
                }
            });

            // Update plan links with billing period
            document.querySelectorAll('a[data-plan-link]').forEach(link => {
                const base = link.dataset.planLink;
                const sep = base.includes('?') ? '&' : '?';
                link.href = base + sep + 'billing=' + billing;
            });
        });
    });
}

// ============================================
// Subdomain Validation (Configure Page)
// ============================================

function initSubdomainCheck() {
    const input = document.getElementById('subdomain-input');
    if (!input) return;

    const feedback = document.getElementById('subdomain-feedback');
    const preview = document.getElementById('url-preview');
    const domainSelect = document.getElementById('domain-select');
    const submitBtn = document.getElementById('submit-btn');
    const subdomainRe = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

    function updatePreview() {
        const sub = input.value.toLowerCase() || 'your-subdomain';
        const domain = domainSelect ? domainSelect.options[domainSelect.selectedIndex].text : '';
        if (preview) {
            preview.innerHTML = '<span class="subdomain">' + sub + '</span>.' + domain;
        }
    }

    const checkAvailability = CloudOdoo.debounce(() => {
        const value = input.value.toLowerCase().trim();

        if (!value) {
            feedback.innerHTML = '';
            input.classList.remove('is-valid', 'is-invalid');
            if (submitBtn) submitBtn.disabled = true;
            return;
        }

        if (!subdomainRe.test(value)) {
            input.classList.remove('is-valid');
            input.classList.add('is-invalid');
            feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>Invalid format. Use lowercase letters, numbers, and hyphens only.</span>';
            if (submitBtn) submitBtn.disabled = true;
            return;
        }

        // Show loading
        feedback.innerHTML = '<span class="text-muted"><span class="spinner-sm me-2"></span>Checking availability...</span>';

        const domainId = domainSelect ? parseInt(domainSelect.value) : 0;
        CloudOdoo.jsonRpc('/saas/check-subdomain', {
            subdomain: value,
            domain_id: domainId,
        }).then(result => {
            if (result.available) {
                input.classList.remove('is-invalid');
                input.classList.add('is-valid');
                feedback.innerHTML = '<span class="valid-feedback d-block"><i class="fas fa-check me-1"></i>' + result.message + '</span>';
                if (submitBtn) submitBtn.disabled = false;
            } else {
                input.classList.remove('is-valid');
                input.classList.add('is-invalid');
                feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>' + (result.message || 'Subdomain not available') + '</span>';
                if (submitBtn) submitBtn.disabled = true;
            }
        }).catch(() => {
            feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>Error checking availability. Please try again.</span>';
            if (submitBtn) submitBtn.disabled = true;
        });
    }, 500);

    input.addEventListener('input', () => {
        input.value = input.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
        updatePreview();
        checkAvailability();
    });

    if (domainSelect) {
        domainSelect.addEventListener('change', () => {
            updatePreview();
            // Re-check if there's already a value
            if (input.value.trim()) checkAvailability();
        });
    }

    updatePreview();
}

// ============================================
// OTP Input Handling (Registration Page)
// ============================================

function initOTPInputs() {
    const inputs = document.querySelectorAll('.otp-input');
    if (!inputs.length) return;

    inputs.forEach((input, index) => {
        input.addEventListener('input', (e) => {
            const value = e.target.value;
            if (value && index < inputs.length - 1) {
                inputs[index + 1].focus();
            }
            // Update hidden field with combined OTP
            updateOTPHidden();
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !input.value && index > 0) {
                inputs[index - 1].focus();
            }
        });

        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const paste = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
            [...paste].forEach((char, i) => {
                if (inputs[i]) inputs[i].value = char;
            });
            updateOTPHidden();
        });
    });

    if (inputs[0]) inputs[0].focus();

    function updateOTPHidden() {
        const hidden = document.getElementById('phone_otp_hidden');
        if (hidden) {
            hidden.value = [...inputs].map(i => i.value).join('');
        }
    }
}

// ============================================
// OTP Countdown Timer
// ============================================

function initOTPTimer() {
    const timerEl = document.getElementById('otp-timer');
    if (!timerEl) return;

    let remaining = parseInt(timerEl.dataset.seconds || '600');

    const interval = setInterval(() => {
        remaining--;
        const minutes = Math.floor(remaining / 60);
        const seconds = remaining % 60;
        timerEl.textContent = minutes + ':' + seconds.toString().padStart(2, '0');

        if (remaining <= 0) {
            clearInterval(interval);
            timerEl.textContent = 'Expired';
        }
    }, 1000);
}

// ============================================
// Password Strength Indicator (Registration)
// ============================================

function initPasswordStrength() {
    const password = document.getElementById('password');
    const confirm = document.getElementById('confirm-password');
    const strengthBar = document.getElementById('strength-bar');
    const matchFeedback = document.getElementById('password-match');

    if (!password || !strengthBar) return;

    password.addEventListener('input', () => {
        const value = password.value;
        let strength = 0;
        if (value.length >= 8) strength++;
        if (/[a-z]/.test(value) && /[A-Z]/.test(value)) strength++;
        if (/\d/.test(value)) strength++;
        if (/[^a-zA-Z0-9]/.test(value)) strength++;

        strengthBar.className = 'strength-bar';
        if (strength <= 1) strengthBar.classList.add('strength-weak');
        else if (strength <= 2) strengthBar.classList.add('strength-medium');
        else strengthBar.classList.add('strength-strong');

        checkMatch();
    });

    if (confirm) {
        confirm.addEventListener('input', checkMatch);
    }

    function checkMatch() {
        if (!confirm || !matchFeedback || !confirm.value) {
            if (matchFeedback) matchFeedback.innerHTML = '';
            return;
        }
        if (password.value === confirm.value) {
            matchFeedback.innerHTML = '<span class="valid-feedback d-block"><i class="fas fa-check me-1"></i>Passwords match</span>';
        } else {
            matchFeedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>Passwords do not match</span>';
        }
    }
}

// ============================================
// Instance Actions (restart, stop, start)
// ============================================

function initInstanceActions() {
    document.querySelectorAll('[data-saas-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const action = btn.dataset.saasAction;
            const instanceId = btn.dataset.instanceId;

            const messages = {
                restart: { msg: 'Restart this instance? It will be briefly unavailable during restart.', variant: 'warning', yes: 'Yes, restart' },
                stop:    { msg: 'Stop this instance? It will become unavailable until you start it again.', variant: 'danger', yes: 'Yes, stop instance' },
                start:   { msg: 'Start this instance?', variant: 'info', yes: 'Yes, start instance' },
            };
            const cfg = messages[action] || { msg: 'Proceed with this action?', variant: 'warning', yes: 'Confirm' };

            CloudOdoo.showConfirm(cfg.msg, cfg.variant, cfg.yes, function() {
                btn.disabled = true;
                const origHtml = btn.innerHTML;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';

                CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/' + action, {})
                    .then(result => {
                        if (result && result.success) {
                            CloudOdoo.showToast(result.message || 'Action completed', 'success');
                        } else if (result && result.error) {
                            CloudOdoo.showToast(result.error, 'error');
                        } else {
                            CloudOdoo.showToast('Action submitted', 'info');
                        }
                        setTimeout(() => window.location.reload(), 2000);
                    })
                    .catch(err => {
                        CloudOdoo.showToast(err.message || 'Action failed — reloading...', 'error');
                        setTimeout(() => window.location.reload(), 2000);
                    });
            });
        });
    });
}

// ============================================
// Resource Usage Refresh
// ============================================

function initUsageRefresh() {
    const btn = document.getElementById('refresh-usage');
    if (!btn) return;

    const instanceId = btn.dataset.instanceId;
    const INTERVAL = 60; // seconds between auto-refreshes
    var countdownEl = document.getElementById('usage-countdown');
    var secondsLeft = INTERVAL;
    var autoTimer = null;
    var countdownTimer = null;
    var refreshing = false;

    function updateUI(result) {
        if (!result || result.error) return;
        // Update CPU as percentage
        const cpuEl = document.getElementById('cpu-usage');
        if (cpuEl && result.cpu_pct !== undefined) {
            cpuEl.textContent = Math.round(result.cpu_pct) + '%';
            const cpuBar = document.getElementById('cpu-bar');
            if (cpuBar) cpuBar.style.width = Math.round(result.cpu_pct) + '%';
        }
        // Update RAM as percentage
        const ramEl = document.getElementById('ram-usage');
        if (ramEl && result.ram_pct !== undefined) {
            ramEl.textContent = Math.round(result.ram_pct) + '%';
            const ramBar = document.getElementById('ram-bar');
            if (ramBar) ramBar.style.width = Math.round(result.ram_pct) + '%';
        }
        // Update Storage with "X GB / Y GB (Z%)" format
        const storageEl = document.getElementById('storage-usage');
        if (storageEl && result.total_storage !== undefined) {
            var storageTxt = result.total_storage;
            if (result.storage_limit) {
                storageTxt += ' / ' + result.storage_limit + ' GB (' + Math.round(result.storage_pct) + '%)';
            }
            storageEl.textContent = storageTxt;
            const storageBar = document.getElementById('storage-bar');
            if (storageBar) storageBar.style.width = Math.round(result.storage_pct) + '%';
        }
    }

    function doRefresh(showToast) {
        if (refreshing) return;
        refreshing = true;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i>';

        CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/refresh-usage', {})
            .then(function(result) {
                updateUI(result);
                if (showToast) CloudOdoo.showToast('Usage data refreshed', 'success');
            })
            .catch(function() {
                if (showToast) CloudOdoo.showToast('Failed to refresh usage data', 'error');
            })
            .finally(function() {
                refreshing = false;
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-sync-alt"></i>';
                // Reset countdown
                secondsLeft = INTERVAL;
            });
    }

    // Manual refresh button
    btn.addEventListener('click', function() {
        doRefresh(true);
    });

    // Countdown display
    function tickCountdown() {
        secondsLeft--;
        if (countdownEl) {
            countdownEl.textContent = secondsLeft + 's';
        }
        if (secondsLeft <= 0) {
            doRefresh(false);
        }
    }

    // Start auto-refresh cycle
    countdownTimer = setInterval(tickCountdown, 1000);

    // Stop auto-refresh when page is hidden (save resources)
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        } else {
            if (!countdownTimer) {
                secondsLeft = 1; // refresh immediately when coming back
                countdownTimer = setInterval(tickCountdown, 1000);
            }
        }
    });
}

// ============================================
// Loading overlay
// ============================================
// Blocking spinner that covers the screen while a long-running portal
// action (create DB, duplicate, drop, repair feature, reset password,
// Backup Now, restore snapshot, …) is in flight. Two triggers:
//   1. ``initLoadingOverlay`` — on every page load, if there's a
//      ``[data-loading-overlay]`` element on the page (rendered by
//      the template when an op is in flight), show the overlay until
//      the polling reloads the page.
//   2. ``initOverlayOnSubmit`` — when a form with ``data-loading-text``
//      is submitted, show the overlay immediately so the user can't
//      double-click before the redirect lands.

function showLoadingOverlay(text, subtitle) {
    var existing = document.getElementById('saas-loading-overlay');
    if (existing) {
        // Already showing — just refresh the main text if requested.
        if (text) {
            var t = existing.querySelector('.saas-loading-overlay-text-main');
            if (t) t.textContent = text;
        }
        return existing;
    }
    var overlay = document.createElement('div');
    overlay.id = 'saas-loading-overlay';
    overlay.className = 'saas-loading-overlay';
    overlay.setAttribute('role', 'status');
    overlay.setAttribute('aria-live', 'polite');
    overlay.innerHTML = (
        '<div class="spinner-border text-light" role="status">' +
        '<span class="visually-hidden">Loading…</span></div>' +
        '<div class="saas-loading-overlay-text">' +
        '<div class="saas-loading-overlay-text-main"></div>' +
        '<div class="saas-loading-overlay-subtitle"></div>' +
        '</div>'
    );
    overlay.querySelector('.saas-loading-overlay-text-main').textContent =
        text || 'Working on it…';
    overlay.querySelector('.saas-loading-overlay-subtitle').textContent =
        subtitle || 'This page will refresh automatically when it\'s done.';
    document.body.appendChild(overlay);
    document.body.classList.add('saas-overlay-locked');
    return overlay;
}

function hideLoadingOverlay() {
    var el = document.getElementById('saas-loading-overlay');
    if (el) el.remove();
    document.body.classList.remove('saas-overlay-locked');
}

function initLoadingOverlay() {
    var marker = document.querySelector('[data-loading-overlay]');
    if (marker) {
        showLoadingOverlay(
            marker.getAttribute('data-loading-text'),
            marker.getAttribute('data-loading-subtitle'),
        );
    }
}

function _setButtonLoading(btn, text) {
    if (btn.dataset.saasOriginalContent === undefined) {
        btn.dataset.saasOriginalContent = btn.innerHTML;
    }
    btn.innerHTML = (
        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        (text || 'Working…')
    );
    btn.disabled = true;
}

function _lockFormButtons(form) {
    // Disable every other interactive button in the form so the
    // customer can't double-click or trigger another action while
    // this one is in flight.
    var buttons = form.querySelectorAll('button, input[type="submit"]');
    buttons.forEach(function(b) { b.disabled = true; });
}

function initOverlayOnSubmit() {
    document.addEventListener('submit', function(e) {
        var form = e.target;
        if (!form || !form.matches || !form.matches('form[data-loading-text]')) {
            return;
        }
        // Forms that explicitly opt out (e.g. dismiss buttons) get
        // neither the overlay nor the per-button loading state.
        if (form.dataset.loadingSkip === '1') return;
        var text = form.getAttribute('data-loading-text');
        var subtitle = form.getAttribute('data-loading-subtitle');
        // Button-only mode for the quick / per-row actions where a
        // full-screen freeze would feel heavy-handed. The submit
        // button shows the spinner, the rest of the form is disabled,
        // and the existing inline banner / polling on the next page
        // load handles the "still working" state.
        if (form.dataset.loadingButtonOnly === '1') {
            var submitter = e.submitter
                || form.querySelector('button[type="submit"], input[type="submit"]');
            if (submitter) _setButtonLoading(submitter, text);
            _lockFormButtons(form);
            return;
        }
        // Full-screen overlay for the heavier flows (create database,
        // repair feature, restore snapshot, …).
        showLoadingOverlay(text, subtitle);
    }, true);
}

// ============================================
// Provisioning Status Polling
// ============================================

function initStatusPolling() {
    // Poll for provisioning states (provisioning, pending_provision, paid)
    var provEl = document.getElementById('provisioning-poll');
    // Poll for pending_payment state (in case payment is being processed async)
    var payEl = document.getElementById('payment-poll');
    // Poll for pending upgrade (awaiting payment then auto-applied)
    var upgradeEl = document.getElementById('upgrade-poll');
    // Poll for backup completion
    var backupEl = document.getElementById('backup-poll');
    // Poll for restore completion
    var restoreEl = document.getElementById('restore-progress-poll');
    // Poll for DB operation completion (create / duplicate / drop)
    var dbopEl = document.getElementById('dbop-poll');

    var el = provEl || payEl || upgradeEl || backupEl || restoreEl || dbopEl;
    if (!el) return;

    var instanceId = el.dataset.instanceId;
    var attempts = 0;
    var maxAttempts = 60; // 60 * 5s = 5 minutes

    function checkStatus() {
        attempts++;
        if (attempts > maxAttempts) {
            clearInterval(poll);
            var msgEl = el.querySelector('p');
            if (msgEl) {
                msgEl.innerHTML = '<strong style="color:var(--co-warning, #F59E0B);">Taking longer than expected.</strong> ' +
                    'Please refresh the page to check the status, or contact support if the issue persists.';
            }
            return;
        }

        CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/status', {})
            .then(function(result) {
                if (!result) return;
                var shouldReload = false;

                if (provEl) {
                    // Polling for provisioning/paid — reload when state changes to running/failed/etc.
                    var waitingStates = ['provisioning', 'pending_provision', 'paid'];
                    if (result.state && waitingStates.indexOf(result.state) === -1) {
                        shouldReload = true;
                    }
                } else if (payEl) {
                    // Polling for pending_payment — reload when payment is confirmed
                    if (result.state && result.state !== 'pending_payment') {
                        shouldReload = true;
                    }
                } else if (upgradeEl) {
                    // Polling for pending upgrade — reload when pending_plan_id is cleared
                    if (!result.pending_plan_id) {
                        shouldReload = true;
                    }
                } else if (backupEl) {
                    // Polling for backup completion — reload when no backup is running
                    if (!result.backup_running) {
                        shouldReload = true;
                    }
                } else if (restoreEl) {
                    // Polling for restore completion — reload when restoration_invoice_id is cleared
                    if (!result.restoration_pending) {
                        shouldReload = true;
                    }
                } else if (dbopEl) {
                    // Polling for DB op completion — reload when no create/duplicate/drop is in flight
                    if (!result.db_ops_running) {
                        shouldReload = true;
                    }
                }

                if (shouldReload) {
                    clearInterval(poll);
                    window.location.reload();
                }
            })
            .catch(function() {
                // Silently retry on network errors
            });
    }

    // First check after 3 seconds, then every 5 seconds
    setTimeout(checkStatus, 3000);
    var poll = setInterval(checkStatus, 5000);
}

// ============================================
// Create Backup
// ============================================

function initBackupActions() {
    const createBtn = document.getElementById('create-backup-btn');
    if (!createBtn) return;

    createBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (!confirm('Create a new backup?')) return;

        const instanceId = createBtn.dataset.instanceId;
        createBtn.disabled = true;
        createBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

        // POST to the backup endpoint
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/my/instances/' + instanceId + '/create-backup';
        const csrf = document.createElement('input');
        csrf.type = 'hidden';
        csrf.name = 'csrf_token';
        csrf.value = CloudOdoo.getCsrfToken();
        form.appendChild(csrf);
        document.body.appendChild(form);
        form.submit();
    });
}

// ============================================
// Sort Instances
// ============================================

function initInstanceSort() {
    const sortSelect = document.getElementById('sort-select');
    if (!sortSelect) return;

    sortSelect.addEventListener('change', () => {
        const sortby = sortSelect.value;
        window.location.href = '/my/instances?sortby=' + sortby;
    });
}

// ============================================
// Login Form Handler
// ============================================

function initLoginForm() {
    const form = document.getElementById('login-form');
    if (!form) return;

    form.addEventListener('submit', function () {
        const btn = this.querySelector('button[type="submit"]');
        if (btn) {
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Signing in...';
            btn.disabled = true;
        }
    });
}

// ============================================
// Trial Countdown
// ============================================

function initTrialCountdown() {
    var alert = document.getElementById('trial-alert');
    if (!alert) return;
    var endStr = alert.dataset.trialEnd;
    if (!endStr) return;

    var end = new Date(endStr + 'T23:59:59');
    var now = new Date();
    var diffMs = end - now;
    var days = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
    if (days < 0) days = 0;

    var badge = document.getElementById('trial-countdown');
    var icon = document.getElementById('trial-alert-icon');
    if (!badge) return;

    badge.style.display = '';
    if (days === 0) {
        badge.textContent = 'Expires today!';
    } else if (days === 1) {
        badge.textContent = '1 day left';
    } else {
        badge.textContent = days + ' days left';
    }

    if (days <= 2) {
        badge.className = 'trial-countdown-badge urgent ms-2';
        alert.className = alert.className.replace('alert-info', 'alert-danger');
        if (icon) icon.className = 'fas fa-exclamation-triangle';
    } else if (days <= 7) {
        badge.className = 'trial-countdown-badge warning ms-2';
        alert.className = alert.className.replace('alert-info', 'alert-warning');
        if (icon) icon.className = 'fas fa-exclamation-circle';
    } else {
        badge.className = 'trial-countdown-badge normal ms-2';
    }
}

// ============================================
// Global Form Loading States
// ============================================

function initFormLoadingStates() {
    document.addEventListener('submit', function(e) {
        var form = e.target;
        // Skip forms handled by other systems
        if (form.id === 'login-form') return;
        if (form.closest('.o_payment_form')) return;
        if (form.closest('#payment_method')) return;

        var btn = form.querySelector('button[type="submit"]:not([disabled])');
        if (!btn) btn = form.querySelector('button[name]:not([disabled])');
        if (!btn) return;

        btn.dataset.originalHtml = btn.innerHTML;
        btn.disabled = true;
        var loadingText = btn.dataset.loadingText || 'Processing...';
        btn.innerHTML = '<span class="spinner-sm me-2" style="display:inline-block;vertical-align:middle;"></span>' + loadingText;
    });
}

// ============================================
// Instance Folders
// ============================================

var _coInputOnConfirm = null;

function _coShowInputModal(title, placeholder, value, confirmText, onConfirm) {
    var modal = document.getElementById('co-input-modal');
    if (!modal) {
        document.body.insertAdjacentHTML('beforeend',
            '<div id="co-input-modal" class="co-modal-overlay">' +
            '  <div class="co-modal-dialog">' +
            '    <div class="co-modal-content">' +
            '      <div class="co-modal-header">' +
            '        <div style="display:flex;align-items:center;gap:12px;">' +
            '          <div id="co-input-icon" class="co-modal-icon" style="background:rgba(59,130,246,0.15);color:#3B82F6;">' +
            '            <i class="fas fa-folder-plus"></i>' +
            '          </div>' +
            '          <h5 id="co-input-title" style="margin:0;font-size:1.1rem;"></h5>' +
            '        </div>' +
            '        <button type="button" class="co-modal-close" id="co-input-close">&times;</button>' +
            '      </div>' +
            '      <div class="co-modal-body">' +
            '        <input type="text" id="co-input-field" class="form-control"' +
            '               style="background:var(--bg-tertiary,#1a1a1d);border-color:var(--border-color,#27272A);color:var(--text-primary,#FAFAFA);"' +
            '               maxlength="80" autocomplete="off"/>' +
            '      </div>' +
            '      <div class="co-modal-footer">' +
            '        <button type="button" class="btn btn-outline-secondary" id="co-input-cancel">' +
            '          <i class="fas fa-times me-1"></i>Cancel' +
            '        </button>' +
            '        <button type="button" class="btn btn-primary" id="co-input-ok">' +
            '          <i class="fas fa-check me-1"></i>Create' +
            '        </button>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>');
        modal = document.getElementById('co-input-modal');

        var hideInput = function () {
            modal.classList.remove('co-show');
            var b = document.getElementById('co-confirm-backdrop');
            if (b) b.classList.remove('co-show');
            setTimeout(function () {
                modal.style.display = 'none';
                if (b) b.style.display = 'none';
            }, 200);
            _coInputOnConfirm = null;
        };

        document.getElementById('co-input-close').addEventListener('click', hideInput);
        document.getElementById('co-input-cancel').addEventListener('click', hideInput);
        document.getElementById('co-input-ok').addEventListener('click', function () {
            var val = document.getElementById('co-input-field').value.trim();
            var fn = _coInputOnConfirm;
            hideInput();
            if (fn && val) setTimeout(function () { fn(val); }, 50);
        });
        document.getElementById('co-input-field').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('co-input-ok').click();
            }
        });
        modal.addEventListener('click', function (e) {
            if (e.target === modal) hideInput();
        });
    }

    document.getElementById('co-input-title').textContent = title;
    document.getElementById('co-input-field').setAttribute('placeholder', placeholder || '');
    document.getElementById('co-input-field').value = value || '';
    document.getElementById('co-input-ok').innerHTML = '<i class="fas fa-check me-1"></i>' + (confirmText || 'OK');
    _coInputOnConfirm = onConfirm;

    // Reuse the shared backdrop
    var b = document.getElementById('co-confirm-backdrop');
    if (!b) {
        b = document.createElement('div');
        b.id = 'co-confirm-backdrop';
        document.body.appendChild(b);
    }
    b.style.display = 'block';
    modal.style.display = 'flex';
    requestAnimationFrame(function () {
        b.classList.add('co-show');
        modal.classList.add('co-show');
        document.getElementById('co-input-field').focus();
        document.getElementById('co-input-field').select();
    });
}

// ============================================
// Installed Packages List
// ============================================

function initPackageList() {
    var btn = document.getElementById('btn-list-packages');
    if (!btn) return;

    var instanceId = btn.dataset.instanceId;
    var listDiv = document.getElementById('installed-packages-list');
    var loadingDiv = document.getElementById('packages-loading');
    var contentDiv = document.getElementById('packages-content');
    var errorDiv = document.getElementById('packages-error');
    var tbody = document.getElementById('packages-tbody');
    var countDiv = document.getElementById('packages-count');
    var loaded = false;

    btn.addEventListener('click', function() {
        if (listDiv.style.display === 'none') {
            listDiv.style.display = '';
            btn.innerHTML = '<i class="fas fa-times me-1"></i>Hide';

            if (!loaded) {
                loadingDiv.style.display = '';
                contentDiv.style.display = 'none';
                errorDiv.style.display = 'none';

                CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/installed-packages', {})
                    .then(function(result) {
                        loadingDiv.style.display = 'none';
                        if (result.error) {
                            errorDiv.style.display = '';
                            errorDiv.textContent = result.error;
                            return;
                        }
                        contentDiv.style.display = '';
                        tbody.innerHTML = '';
                        (result.packages || []).forEach(function(pkg) {
                            var tr = document.createElement('tr');
                            tr.innerHTML = '<td style="padding:0.4rem 0.5rem;">' +
                                pkg.name + '</td><td style="padding:0.4rem 0.5rem;color:var(--co-text-muted,#71717A);">' +
                                pkg.version + '</td>';
                            tbody.appendChild(tr);
                        });
                        countDiv.textContent = result.count + ' packages installed';
                        loaded = true;
                    })
                    .catch(function() {
                        loadingDiv.style.display = 'none';
                        errorDiv.style.display = '';
                        errorDiv.textContent = 'Failed to load packages';
                    });
            }
        } else {
            listDiv.style.display = 'none';
            btn.innerHTML = '<i class="fas fa-list me-1"></i>View All';
        }
    });
}

// ============================================
// Instance Folders
// ============================================

function initRestoreBanner() {
    var requestBtn = document.getElementById('btn-request-restore');
    var dismissBtn = document.getElementById('btn-dismiss-restore');
    if (!requestBtn) return;

    var instanceId = requestBtn.dataset.instanceId;

    requestBtn.addEventListener('click', function () {
        _coShowInputModal(
            'Request Data Restore',
            'Add a note for support (optional)',
            '',
            'Send Request',
            function (note) {
                requestBtn.disabled = true;
                requestBtn.innerHTML = '<span class="spinner-sm"></span> Sending...';
                CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/request-restore', { note: note })
                    .then(function (res) {
                        if (res.error) {
                            CloudOdoo.showToast(res.error, 'error');
                            requestBtn.disabled = false;
                            requestBtn.innerHTML = '<i class="fas fa-paper-plane me-1"></i>Request Data Restore';
                        } else {
                            CloudOdoo.showToast(res.message, 'success');
                            var banner = document.getElementById('restore-banner');
                            if (banner) {
                                banner.innerHTML = '<div class="text-center p-3" style="color:var(--success);">' +
                                    '<i class="fas fa-check-circle me-2"></i>' +
                                    '<strong>Request sent!</strong> Our support team will contact you shortly.</div>';
                            }
                        }
                    })
                    .catch(function (e) {
                        CloudOdoo.showToast(e.message || 'Failed to send request', 'error');
                        requestBtn.disabled = false;
                        requestBtn.innerHTML = '<i class="fas fa-paper-plane me-1"></i>Request Data Restore';
                    });
            }
        );
    });

    if (dismissBtn) {
        dismissBtn.addEventListener('click', function () {
            CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/dismiss-restore-banner', {})
                .then(function () {
                    var banner = document.getElementById('restore-banner');
                    if (banner) banner.remove();
                })
                .catch(function () {});
        });
    }

    // Decline restore (cancel invoice, keep fresh data)
    var declineBtn = document.getElementById('btn-decline-restore');
    if (declineBtn) {
        declineBtn.addEventListener('click', function () {
            var declineInstanceId = declineBtn.dataset.instanceId;
            _coSetupModal(
                'Decline data restoration? The restoration invoice will be cancelled and your old backup will be removed. You will keep the fresh instance data.',
                'warning', 'Yes, decline restore', 'No, keep option',
                function () {
                    declineBtn.disabled = true;
                    CloudOdoo.jsonRpc('/my/instances/' + declineInstanceId + '/decline-restore', {})
                        .then(function (res) {
                            if (res.error) {
                                CloudOdoo.showToast(res.error, 'error');
                                declineBtn.disabled = false;
                            } else {
                                CloudOdoo.showToast(res.message, 'success');
                                window.location.reload();
                            }
                        })
                        .catch(function (e) {
                            CloudOdoo.showToast(e.message || 'Failed', 'error');
                            declineBtn.disabled = false;
                        });
                }
            );
        });
    }
}

function initBackupButton() {
    var btn = document.getElementById('btn-create-backup');
    if (!btn) return;

    btn.addEventListener('click', function () {
        var instanceId = btn.dataset.instanceId;
        _coSetupModal(
            'Create a new backup of your instance?',
            'info', 'Yes, create backup', 'Cancel',
            function () {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-sm"></span> Creating...';
                CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/create-backup', {})
                    .then(function (res) {
                        if (res.error) {
                            CloudOdoo.showToast(res.error, 'error');
                            btn.disabled = false;
                            btn.innerHTML = '<i class="fas fa-plus me-1"></i>Create Backup';
                        } else {
                            CloudOdoo.showToast('Backup started', 'success');
                            window.location.reload();
                        }
                    })
                    .catch(function (e) {
                        CloudOdoo.showToast(e.message || 'Failed', 'error');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-plus me-1"></i>Create Backup';
                    });
            }
        );
    });
}

function initInstanceFolders() {
    var createBtn = document.getElementById('btn-create-folder');
    if (!createBtn) return;

    // Create folder
    createBtn.addEventListener('click', function () {
        _coShowInputModal('New Folder', 'Folder name', '', 'Create', function (name) {
            CloudOdoo.jsonRpc('/my/instances/folder/create', { name: name })
                .then(function (res) {
                    if (res.error) {
                        CloudOdoo.showToast(res.error, 'error');
                    } else {
                        window.location.reload();
                    }
                })
                .catch(function (e) { CloudOdoo.showToast(e.message, 'error'); });
        });
    });

    // Rename folder
    document.querySelectorAll('.folder-rename-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var folderId = parseInt(this.dataset.folderId);
            var currentName = this.dataset.folderName;
            _coShowInputModal('Rename Folder', 'Folder name', currentName, 'Rename', function (name) {
                if (name === currentName) return;
                CloudOdoo.jsonRpc('/my/instances/folder/' + folderId + '/rename', { name: name })
                    .then(function (res) {
                        if (res.error) {
                            CloudOdoo.showToast(res.error, 'error');
                        } else {
                            window.location.reload();
                        }
                    })
                    .catch(function (e) { CloudOdoo.showToast(e.message, 'error'); });
            });
        });
    });

    // Delete folder
    document.querySelectorAll('.folder-delete-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var folderId = parseInt(this.dataset.folderId);
            var folderName = this.dataset.folderName;
            _coSetupModal(
                'Delete folder "' + folderName + '"? Instances will be moved to Unfiled.',
                'danger', 'Delete', 'Cancel',
                function () {
                    CloudOdoo.jsonRpc('/my/instances/folder/' + folderId + '/delete', {})
                        .then(function (res) {
                            if (res.error) {
                                CloudOdoo.showToast(res.error, 'error');
                            } else {
                                // If currently viewing the deleted folder, go to all
                                var params = new URLSearchParams(window.location.search);
                                if (params.get('folder') === String(folderId)) {
                                    window.location.href = '/my/instances';
                                } else {
                                    window.location.reload();
                                }
                            }
                        })
                        .catch(function (e) { CloudOdoo.showToast(e.message, 'error'); });
                }
            );
        });
    });

    // Add subfolder
    document.querySelectorAll('.folder-add-sub-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var parentId = parseInt(this.dataset.folderId);
            var parentName = this.dataset.folderName;
            _coShowInputModal('New Subfolder in "' + parentName + '"', 'Subfolder name', '', 'Create', function (name) {
                CloudOdoo.jsonRpc('/my/instances/folder/create', { name: name, parent_id: parentId })
                    .then(function (res) {
                        if (res.error) {
                            CloudOdoo.showToast(res.error, 'error');
                        } else {
                            window.location.reload();
                        }
                    })
                    .catch(function (e) { CloudOdoo.showToast(e.message, 'error'); });
            });
        });
    });

    // Checkbox selection & bulk actions
    var selectAll = document.getElementById('select-all-instances');
    var bulkBar = document.getElementById('bulk-actions');
    var countEl = document.getElementById('selected-count');
    var checkboxes = document.querySelectorAll('.instance-checkbox');

    function updateBulkBar() {
        var checked = document.querySelectorAll('.instance-checkbox:checked');
        if (countEl) countEl.textContent = checked.length;
        if (bulkBar) {
            bulkBar.classList.toggle('d-none', checked.length === 0);
            bulkBar.classList.toggle('d-flex', checked.length > 0);
        }
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            checkboxes.forEach(function (cb) { cb.checked = selectAll.checked; });
            updateBulkBar();
        });
    }
    checkboxes.forEach(function (cb) {
        cb.addEventListener('change', updateBulkBar);
    });

    // Move to folder
    document.querySelectorAll('.move-to-folder').forEach(function (item) {
        item.addEventListener('click', function (e) {
            e.preventDefault();
            var folderId = parseInt(this.dataset.folderId) || false;
            var checked = document.querySelectorAll('.instance-checkbox:checked');
            var ids = [];
            checked.forEach(function (cb) { ids.push(parseInt(cb.value)); });
            if (!ids.length) return;
            CloudOdoo.jsonRpc('/my/instances/move', {
                instance_ids: ids,
                folder_id: folderId,
            })
                .then(function (res) {
                    if (res.error) {
                        CloudOdoo.showToast(res.error, 'error');
                    } else {
                        CloudOdoo.showToast('Moved ' + ids.length + ' instance(s)', 'success');
                        setTimeout(function () { window.location.reload(); }, 500);
                    }
                })
                .catch(function (e) { CloudOdoo.showToast(e.message, 'error'); });
        });
    });
}

// ============================================
// Shared Slider Helpers
// ============================================

function generateTicks(containerId, min, max, step) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    for (var i = min; i <= max; i += step) {
        var tick = document.createElement('div');
        tick.className = 'slider-tick';
        var pct = max > min ? ((i - min) / (max - min)) * 100 : 0;
        tick.style.left = pct + '%';
        tick.innerHTML = '<span class="tick-mark"></span><span class="tick-label">' + i + '</span>';
        if ((containerId === 'workers-ticks' || containerId === 'upgrade-workers-ticks') && i >= 4 && i <= 6) {
            tick.classList.add('tick-recommended');
        }
        container.appendChild(tick);
    }
}

function generateStorageTicks(containerId, min, max) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    // Build tick list: always include min and max, plus well-spaced milestones
    var candidates = [min, 25, 50, 100, 150, 200, max];
    var ticks = [];
    var range = max - min;
    // Minimum distance between ticks: 10% of range to avoid label overlap
    var minGap = range * 0.1;

    for (var i = 0; i < candidates.length; i++) {
        var val = candidates[i];
        if (val < min || val > max) continue;
        // Check distance from last tick
        if (ticks.length > 0 && (val - ticks[ticks.length - 1]) < minGap) continue;
        ticks.push(val);
    }
    // Always ensure max is included
    if (ticks[ticks.length - 1] !== max) {
        // Remove last tick if too close to max
        if (ticks.length > 1 && (max - ticks[ticks.length - 1]) < minGap) {
            ticks.pop();
        }
        ticks.push(max);
    }

    ticks.forEach(function(val) {
        var tick = document.createElement('div');
        tick.className = 'slider-tick';
        var pct = range > 0 ? ((val - min) / range) * 100 : 0;
        tick.style.left = pct + '%';
        tick.innerHTML = '<span class="tick-mark"></span><span class="tick-label">' + val + 'GB</span>';
        container.appendChild(tick);
    });
}

// ============================================
// Custom Plan Builder (Pricing Page)
// ============================================

function initCustomPlanBuilder() {
    var configEl = document.getElementById('custom-plan-config');
    if (!configEl) return;

    var config = {
        workerPrice: parseFloat(configEl.dataset.workerPrice) || 15,
        storagePrice: parseFloat(configEl.dataset.storagePrice) || 0.5,
        minWorkers: parseInt(configEl.dataset.minWorkers) || 2,
        maxWorkers: parseInt(configEl.dataset.maxWorkers) || 8,
        minStorage: parseInt(configEl.dataset.minStorage) || 5,
        maxStorage: parseInt(configEl.dataset.maxStorage) || 200,
        usersPerWorkerMin: parseInt(configEl.dataset.usersPerWorkerMin) || 6,
        usersPerWorkerMax: parseInt(configEl.dataset.usersPerWorkerMax) || 10,
        yearlyDiscountPct: parseInt(configEl.dataset.yearlyDiscountPct) || 20,
        currency: configEl.dataset.currency || 'USD',
        productId: configEl.dataset.productId || '',
        minBackups: parseInt(configEl.dataset.minBackups) || 3,
        maxBackups: parseInt(configEl.dataset.maxBackups) || 14,
    };

    var workersSlider = document.getElementById('workers-slider');
    var storageSlider = document.getElementById('storage-slider');
    if (!workersSlider || !storageSlider) return;

    // Billing state
    var currentBilling = 'monthly';
    var YEARLY_DISCOUNT = config.yearlyDiscountPct / 100;

    // Generate tick marks
    generateTicks('workers-ticks', config.minWorkers, config.maxWorkers, 1);
    generateStorageTicks('storage-ticks', config.minStorage, config.maxStorage);

    // Update slider track fill
    function updateSliderTrack(slider) {
        var min = parseFloat(slider.min);
        var max = parseFloat(slider.max);
        var val = parseFloat(slider.value);
        var pct = ((val - min) / (max - min)) * 100;
        slider.style.setProperty('--slider-pct', pct + '%');
    }

    function calculateAndUpdate() {
        var workers = parseInt(workersSlider.value);
        var storage = parseInt(storageSlider.value);

        var workersCost = workers * config.workerPrice;
        var storageCost = storage * config.storagePrice;
        var monthlyTotal = workersCost + storageCost;
        var yearlyFullPrice = monthlyTotal * 12;
        var yearlyDiscounted = yearlyFullPrice * (1 - YEARLY_DISCOUNT);
        var yearlySavings = yearlyFullPrice - yearlyDiscounted;
        var effectiveMonthly = yearlyDiscounted / 12;
        var minUsers = workers * config.usersPerWorkerMin;
        var maxUsers = workers * config.usersPerWorkerMax;

        // Sync number inputs with slider values
        var wInput = document.getElementById('workers-input');
        var sInput = document.getElementById('storage-input');
        if (wInput && wInput !== document.activeElement) wInput.value = workers;
        if (sInput && sInput !== document.activeElement) sInput.value = storage;

        // Update recommendation
        var recEl = document.querySelector('#workers-recommendation .rec-users');
        if (recEl) recEl.textContent = '~' + minUsers + '–' + maxUsers;

        // Update price breakdown (always shows monthly unit prices)
        setText('summary-workers', workers);
        setText('summary-storage', storage);
        setText('summary-workers-cost', CloudOdoo.formatCurrency(workersCost, config.currency) + '/mo');
        setText('summary-storage-cost', CloudOdoo.formatCurrency(storageCost, config.currency) + '/mo');

        // Toggle monthly/yearly display
        var monthlyDisplay = document.getElementById('summary-monthly-display');
        var yearlyDisplay = document.getElementById('summary-yearly-display');

        if (currentBilling === 'yearly') {
            if (monthlyDisplay) monthlyDisplay.style.display = 'none';
            if (yearlyDisplay) yearlyDisplay.style.display = '';
            setText('summary-yearly-total', CloudOdoo.formatCurrency(yearlyDiscounted, config.currency));
            setText('summary-effective-monthly', CloudOdoo.formatCurrency(effectiveMonthly, config.currency) + '/mo');
            setText('summary-yearly-savings', CloudOdoo.formatCurrency(yearlySavings, config.currency));
            setText('summary-yearly-original', CloudOdoo.formatCurrency(yearlyFullPrice, config.currency));
            setText('summary-yearly-discounted', CloudOdoo.formatCurrency(yearlyDiscounted, config.currency));
        } else {
            if (monthlyDisplay) monthlyDisplay.style.display = '';
            if (yearlyDisplay) yearlyDisplay.style.display = 'none';
            setText('summary-monthly-total', CloudOdoo.formatCurrency(monthlyTotal, config.currency));
            setText('summary-yearly-equiv', CloudOdoo.formatCurrency(yearlyFullPrice, config.currency) + '/yr');
        }

        setText('summary-min-users', minUsers);
        setText('summary-max-users', maxUsers);

        // Calculate backup count (same formula as backend)
        var wRange = Math.max(1, config.maxWorkers - config.minWorkers);
        var sRange = Math.max(1, config.maxStorage - config.minStorage);
        var wPct = (workers - config.minWorkers) / wRange;
        var sPct = (storage - config.minStorage) / sRange;
        var planSize = (wPct + sPct) / 2.0;
        var backupCount = Math.max(config.minBackups, Math.min(config.maxBackups,
            config.minBackups + Math.round(planSize * (config.maxBackups - config.minBackups))
        ));
        setText('summary-backups', backupCount);

        // Update CTA link
        var ctaEl = document.getElementById('custom-plan-cta');
        if (ctaEl) {
            ctaEl.href = '/services/' + config.productId + '/custom/configure?workers=' + workers + '&storage=' + storage + '&billing=' + currentBilling;
        }

        // Update slider tracks
        updateSliderTrack(workersSlider);
        updateSliderTrack(storageSlider);

        // Highlight recommended workers range (4-6)
        updateWorkersHighlight(workers);
    }

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function updateWorkersHighlight(currentWorkers) {
        var rec = document.getElementById('workers-recommendation');
        if (!rec) return;
        // Change recommendation style based on range
        if (currentWorkers >= 4 && currentWorkers <= 6) {
            rec.classList.add('rec-optimal');
            rec.classList.remove('rec-normal');
        } else {
            rec.classList.remove('rec-optimal');
            rec.classList.add('rec-normal');
        }
    }

    // Event listeners — sliders
    workersSlider.addEventListener('input', calculateAndUpdate);
    storageSlider.addEventListener('input', calculateAndUpdate);

    // Event listeners — number inputs sync to sliders
    var workersInput = document.getElementById('workers-input');
    var storageInput = document.getElementById('storage-input');
    if (workersInput) {
        workersInput.addEventListener('input', function() {
            var v = Math.max(config.minWorkers, Math.min(config.maxWorkers, parseInt(this.value) || config.minWorkers));
            workersSlider.value = v;
            calculateAndUpdate();
        });
    }
    if (storageInput) {
        storageInput.addEventListener('input', function() {
            var v = Math.max(config.minStorage, Math.min(config.maxStorage, parseInt(this.value) || config.minStorage));
            storageSlider.value = v;
            calculateAndUpdate();
        });
    }

    // Custom builder billing toggle
    var customBillingToggle = document.getElementById('custom-billing-toggle');
    if (customBillingToggle) {
        customBillingToggle.querySelectorAll('.toggle-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                customBillingToggle.querySelectorAll('.toggle-btn').forEach(function(b) {
                    b.classList.remove('active');
                });
                btn.classList.add('active');
                currentBilling = btn.dataset.billing;
                calculateAndUpdate();
            });
        });
    }

    // "Customize this plan" buttons
    document.querySelectorAll('.btn-customize-plan').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            var planWorkers = parseInt(btn.dataset.workers) || 4;
            var planStorage = parseInt(btn.dataset.storage) || 20;

            // Clamp to allowed range
            planWorkers = Math.max(config.minWorkers, Math.min(planWorkers, config.maxWorkers));
            planStorage = Math.max(config.minStorage, Math.min(planStorage, config.maxStorage));

            // Set slider values
            workersSlider.value = planWorkers;
            storageSlider.value = planStorage;

            // Recalculate
            calculateAndUpdate();

            // Scroll to builder
            var builder = document.getElementById('custom-builder');
            if (builder) {
                builder.scrollIntoView({ behavior: 'smooth', block: 'start' });
                // Add a brief highlight animation
                builder.classList.add('builder-highlight');
                setTimeout(function() {
                    builder.classList.remove('builder-highlight');
                }, 1500);
            }
        });
    });

    // Initial calculation
    calculateAndUpdate();
}

// ============================================
// Upgrade / Change Plan Builder
// ============================================

function initUpgradePlanBuilder() {
    var configEl = document.getElementById('upgrade-plan-config');
    if (!configEl) return;

    var config = {
        workerPrice: parseFloat(configEl.dataset.workerPrice) || 15,
        storagePrice: parseFloat(configEl.dataset.storagePrice) || 0.5,
        minWorkers: parseInt(configEl.dataset.minWorkers) || 2,
        maxWorkers: parseInt(configEl.dataset.maxWorkers) || 8,
        minStorage: parseInt(configEl.dataset.minStorage) || 5,
        maxStorage: parseInt(configEl.dataset.maxStorage) || 200,
        yearlyDiscountPct: parseInt(configEl.dataset.yearlyDiscountPct) || 20,
        currency: configEl.dataset.currency || 'USD',
        mode: configEl.dataset.mode || 'upgrade',
        currentWorkers: parseInt(configEl.dataset.currentWorkers) || 0,
        currentStorage: parseInt(configEl.dataset.currentStorage) || 0,
        currentBilling: configEl.dataset.currentBilling || 'monthly',
        minBackups: parseInt(configEl.dataset.minBackups) || 3,
        maxBackups: parseInt(configEl.dataset.maxBackups) || 14,
    };

    var workersSlider = document.getElementById('upgrade-workers-slider');
    var storageSlider = document.getElementById('upgrade-storage-slider');
    if (!workersSlider || !storageSlider) return;

    var currentBilling = config.mode === 'change' ? config.currentBilling : 'monthly';
    var YEARLY_DISCOUNT = config.yearlyDiscountPct / 100;

    // Generate tick marks
    generateTicks('upgrade-workers-ticks', config.minWorkers, config.maxWorkers, 1);
    generateStorageTicks('upgrade-storage-ticks', config.minStorage, config.maxStorage);

    function updateSliderTrack(slider) {
        var min = parseFloat(slider.min);
        var max = parseFloat(slider.max);
        var val = parseFloat(slider.value);
        var pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
        slider.style.setProperty('--slider-pct', pct + '%');
    }

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function calculateAndUpdate() {
        var workers = parseInt(workersSlider.value);
        var storage = parseInt(storageSlider.value);

        var workersCost = workers * config.workerPrice;
        var storageCost = storage * config.storagePrice;
        var monthlyTotal = workersCost + storageCost;
        var yearlyFullPrice = monthlyTotal * 12;
        var yearlyDiscounted = yearlyFullPrice * (1 - YEARLY_DISCOUNT);
        var yearlySavings = yearlyFullPrice - yearlyDiscounted;

        // Sync number inputs with slider values
        var wInput = document.getElementById('upgrade-workers-input');
        var sInput = document.getElementById('upgrade-storage-input');
        if (wInput && wInput !== document.activeElement) wInput.value = workers;
        if (sInput && sInput !== document.activeElement) sInput.value = storage;

        // Update price breakdown
        setText('upgrade-summary-workers', workers);
        setText('upgrade-summary-storage', storage);
        setText('upgrade-summary-workers-cost', CloudOdoo.formatCurrency(workersCost, config.currency) + '/mo');
        setText('upgrade-summary-storage-cost', CloudOdoo.formatCurrency(storageCost, config.currency) + '/mo');

        // Toggle monthly/yearly display
        var monthlyDisplay = document.getElementById('upgrade-summary-monthly-display');
        var yearlyDisplay = document.getElementById('upgrade-summary-yearly-display');

        if (currentBilling === 'yearly') {
            if (monthlyDisplay) monthlyDisplay.style.display = 'none';
            if (yearlyDisplay) yearlyDisplay.style.display = '';
            setText('upgrade-summary-yearly-total', CloudOdoo.formatCurrency(yearlyDiscounted, config.currency));
            setText('upgrade-summary-yearly-savings', CloudOdoo.formatCurrency(yearlySavings, config.currency));
        } else {
            if (monthlyDisplay) monthlyDisplay.style.display = '';
            if (yearlyDisplay) yearlyDisplay.style.display = 'none';
            setText('upgrade-summary-monthly-total', CloudOdoo.formatCurrency(monthlyTotal, config.currency));
        }

        // Calculate backup count
        var wRange = Math.max(1, config.maxWorkers - config.minWorkers);
        var sRange = Math.max(1, config.maxStorage - config.minStorage);
        var wPct = (workers - config.minWorkers) / wRange;
        var sPct = (storage - config.minStorage) / sRange;
        var planSize = (wPct + sPct) / 2.0;
        var backupCount = Math.max(config.minBackups, Math.min(config.maxBackups,
            config.minBackups + Math.round(planSize * (config.maxBackups - config.minBackups))
        ));
        setText('upgrade-summary-backups', backupCount);

        // Update hidden form fields
        var formWorkers = document.getElementById('upgrade-form-workers');
        var formStorage = document.getElementById('upgrade-form-storage');
        var formBilling = document.getElementById('upgrade-form-billing');
        if (formWorkers) formWorkers.value = workers;
        if (formStorage) formStorage.value = storage;
        if (formBilling) formBilling.value = currentBilling;

        // Update slider tracks
        updateSliderTrack(workersSlider);
        updateSliderTrack(storageSlider);

        // Change-plan mode: update action info and submit button
        if (config.mode === 'change') {
            var submitBtn = document.getElementById('upgrade-submit-btn');
            var actionInfo = document.getElementById('upgrade-action-info');
            var reductionNotice = document.getElementById('upgrade-worker-reduction-notice');
            var hasChanges = (workers !== config.currentWorkers ||
                              storage !== config.currentStorage ||
                              currentBilling !== config.currentBilling);

            if (submitBtn) submitBtn.disabled = !hasChanges;

            // Show worker reduction notice
            if (reductionNotice) {
                reductionNotice.style.display = workers < config.currentWorkers ? '' : 'none';
            }

            // Update action info banner
            if (actionInfo) {
                if (!hasChanges) {
                    actionInfo.style.display = 'none';
                } else if (workers < config.currentWorkers) {
                    // Downgrade (worker reduction)
                    actionInfo.style.display = '';
                    actionInfo.style.background = 'rgba(245,158,11,0.06)';
                    actionInfo.style.border = '1px solid rgba(245,158,11,0.15)';
                    actionInfo.innerHTML =
                        '<div class="fw-semibold mb-1" style="color:#F59E0B;">' +
                        '<i class="fas fa-calendar-alt me-1"></i>Scheduled at Next Billing</div>' +
                        '<div style="color:var(--co-text-secondary,#A1A1AA);">' +
                        'Worker reduction will take effect at your next billing cycle. ' +
                        'You keep your current resources until then.</div>';
                    if (submitBtn) {
                        submitBtn.className = 'btn btn-warning btn-lg w-100';
                        submitBtn.innerHTML = '<i class="fas fa-calendar-alt me-2"></i>Schedule Change';
                    }
                } else {
                    // Upgrade (workers same/increased, storage increased)
                    actionInfo.style.display = '';
                    actionInfo.style.background = 'rgba(16,185,129,0.06)';
                    actionInfo.style.border = '1px solid rgba(16,185,129,0.15)';
                    actionInfo.innerHTML =
                        '<div class="fw-semibold mb-1" style="color:#10B981;">' +
                        '<i class="fas fa-bolt me-1"></i>Immediate Upgrade</div>' +
                        '<div style="color:var(--co-text-secondary,#A1A1AA);">' +
                        'Resources will be upgraded instantly with zero downtime. ' +
                        'You\'ll be charged the prorated difference.</div>';
                    if (submitBtn) {
                        submitBtn.className = 'btn btn-primary btn-lg w-100';
                        submitBtn.innerHTML = '<i class="fas fa-arrow-up me-2"></i>Upgrade Now';
                    }
                }
            }
        }
    }

    // Slider event listeners
    workersSlider.addEventListener('input', calculateAndUpdate);
    storageSlider.addEventListener('input', calculateAndUpdate);

    // Number input listeners — sync to sliders
    var upgradeWorkersInput = document.getElementById('upgrade-workers-input');
    var upgradeStorageInput = document.getElementById('upgrade-storage-input');
    if (upgradeWorkersInput) {
        upgradeWorkersInput.addEventListener('input', function() {
            var v = Math.max(config.minWorkers, Math.min(config.maxWorkers, parseInt(this.value) || config.minWorkers));
            workersSlider.value = v;
            calculateAndUpdate();
        });
    }
    if (upgradeStorageInput) {
        upgradeStorageInput.addEventListener('input', function() {
            var v = Math.max(config.minStorage, Math.min(config.maxStorage, parseInt(this.value) || config.minStorage));
            storageSlider.value = v;
            calculateAndUpdate();
        });
    }

    // Billing toggle
    var toggleContainer = document.getElementById('upgrade-billing-toggle');
    if (toggleContainer) {
        toggleContainer.querySelectorAll('.toggle-btn').forEach(function(btn) {
            if (btn.dataset.billing === currentBilling) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
            btn.addEventListener('click', function() {
                toggleContainer.querySelectorAll('.toggle-btn').forEach(function(b) {
                    b.classList.remove('active');
                });
                btn.classList.add('active');
                currentBilling = btn.dataset.billing;
                calculateAndUpdate();
            });
        });
    }

    // Initial calculation
    calculateAndUpdate();
}

// ============================================
// Hosting Plan Builder
// ============================================

function initHostingPlanBuilder() {
    var configEl = document.getElementById('hosting-plan-config');
    if (!configEl) return;

    var config = {
        workerPrice: parseFloat(configEl.dataset.workerPrice) || 10,
        storagePrice: parseFloat(configEl.dataset.storagePrice) || 0.3,
        minWorkers: parseInt(configEl.dataset.minWorkers) || 2,
        maxWorkers: parseInt(configEl.dataset.maxWorkers) || 8,
        minStorage: parseInt(configEl.dataset.minStorage) || 5,
        maxStorage: parseInt(configEl.dataset.maxStorage) || 200,
        yearlyDiscountPct: parseInt(configEl.dataset.yearlyDiscountPct) || 20,
        currency: configEl.dataset.currency || 'USD',
        minBackups: parseInt(configEl.dataset.minBackups) || 3,
        maxBackups: parseInt(configEl.dataset.maxBackups) || 14,
    };

    var workersSlider = document.getElementById('hosting-workers-slider');
    var storageSlider = document.getElementById('hosting-storage-slider');
    if (!workersSlider || !storageSlider) return;

    var currentBilling = 'monthly';
    var YEARLY_DISCOUNT = config.yearlyDiscountPct / 100;

    generateTicks('hosting-workers-ticks', config.minWorkers, config.maxWorkers, 1);
    generateStorageTicks('hosting-storage-ticks', config.minStorage, config.maxStorage);

    function updateSliderTrack(slider) {
        var min = parseFloat(slider.min);
        var max = parseFloat(slider.max);
        var val = parseFloat(slider.value);
        var pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
        slider.style.setProperty('--slider-pct', pct + '%');
    }

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function calculateAndUpdate() {
        var workers = parseInt(workersSlider.value);
        var storage = parseInt(storageSlider.value);

        var workersCost = workers * config.workerPrice;
        var storageCost = storage * config.storagePrice;
        var monthlyTotal = workersCost + storageCost;
        var yearlyFullPrice = monthlyTotal * 12;
        var yearlyDiscounted = yearlyFullPrice * (1 - YEARLY_DISCOUNT);
        var yearlySavings = yearlyFullPrice - yearlyDiscounted;

        // Sync number inputs
        var wInput = document.getElementById('hosting-workers-input');
        var sInput = document.getElementById('hosting-storage-input');
        if (wInput && wInput !== document.activeElement) wInput.value = workers;
        if (sInput && sInput !== document.activeElement) sInput.value = storage;

        setText('hosting-summary-workers', workers);
        setText('hosting-summary-storage', storage);
        setText('hosting-summary-workers-cost', CloudOdoo.formatCurrency(workersCost, config.currency) + '/mo');
        setText('hosting-summary-storage-cost', CloudOdoo.formatCurrency(storageCost, config.currency) + '/mo');

        // Backup count
        var wRange = Math.max(1, config.maxWorkers - config.minWorkers);
        var sRange = Math.max(1, config.maxStorage - config.minStorage);
        var planSize = ((workers - config.minWorkers) / wRange + (storage - config.minStorage) / sRange) / 2.0;
        var backupCount = Math.max(config.minBackups, Math.min(config.maxBackups,
            config.minBackups + Math.round(planSize * (config.maxBackups - config.minBackups))
        ));
        setText('hosting-summary-backups', backupCount);

        // Toggle monthly/yearly
        var monthlyDisplay = document.getElementById('hosting-summary-monthly-display');
        var yearlyDisplay = document.getElementById('hosting-summary-yearly-display');
        if (currentBilling === 'yearly') {
            if (monthlyDisplay) monthlyDisplay.style.display = 'none';
            if (yearlyDisplay) yearlyDisplay.style.display = '';
            setText('hosting-summary-yearly-total', CloudOdoo.formatCurrency(yearlyDiscounted, config.currency));
            setText('hosting-summary-yearly-savings', CloudOdoo.formatCurrency(yearlySavings, config.currency));
        } else {
            if (monthlyDisplay) monthlyDisplay.style.display = '';
            if (yearlyDisplay) yearlyDisplay.style.display = 'none';
            setText('hosting-summary-monthly-total', CloudOdoo.formatCurrency(monthlyTotal, config.currency));
        }

        // Update CTA link
        var ctaEl = document.getElementById('hosting-cta');
        var versionSelect = document.getElementById('hosting-version-select');
        var versionId = versionSelect ? versionSelect.value : '';
        if (ctaEl) {
            ctaEl.href = '/hosting/configure?workers=' + workers + '&storage=' + storage +
                         '&billing=' + currentBilling + '&odoo_version_id=' + versionId;
        }

        updateSliderTrack(workersSlider);
        updateSliderTrack(storageSlider);
    }

    workersSlider.addEventListener('input', calculateAndUpdate);
    storageSlider.addEventListener('input', calculateAndUpdate);

    // Number inputs
    var wInput = document.getElementById('hosting-workers-input');
    var sInput = document.getElementById('hosting-storage-input');
    if (wInput) {
        wInput.addEventListener('input', function() {
            workersSlider.value = Math.max(config.minWorkers, Math.min(config.maxWorkers, parseInt(this.value) || config.minWorkers));
            calculateAndUpdate();
        });
    }
    if (sInput) {
        sInput.addEventListener('input', function() {
            storageSlider.value = Math.max(config.minStorage, Math.min(config.maxStorage, parseInt(this.value) || config.minStorage));
            calculateAndUpdate();
        });
    }

    // Version select updates CTA link
    var versionSelect = document.getElementById('hosting-version-select');
    if (versionSelect) {
        versionSelect.addEventListener('change', calculateAndUpdate);
    }

    // Billing toggle
    var toggleContainer = document.getElementById('hosting-billing-toggle');
    if (toggleContainer) {
        toggleContainer.querySelectorAll('.toggle-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                toggleContainer.querySelectorAll('.toggle-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                currentBilling = btn.dataset.billing;
                calculateAndUpdate();
            });
        });
    }

    calculateAndUpdate();
}

// ============================================
// Page Initialization
// ============================================

function initAll() {
    // Initialize all interactive components
    initThemeToggle();
    initBillingToggle();
    initSubdomainCheck();
    initCustomPlanBuilder();
    initUpgradePlanBuilder();
    initHostingPlanBuilder();
    initOTPInputs();
    initOTPTimer();
    initPasswordStrength();
    initInstanceActions();
    initUsageRefresh();
    initStatusPolling();
    initLoadingOverlay();
    initOverlayOnSubmit();
    initBackupActions();
    initInstanceSort();
    initLoginForm();
    initTrialCountdown();
    initConfirmModals();
    initFormLoadingStates();
    initPackageList();
    initInstanceFolders();
    initBackupButton();
    initRestoreBanner();

    // Update nav active state
    const path = window.location.pathname;
    document.querySelectorAll('.navbar-nav .nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href && path.startsWith(href) && href !== '/') {
            link.classList.add('active');
        }
    });
}

// Run immediately if DOM is already ready (Odoo deferred scripts),
// otherwise wait for DOMContentLoaded.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
} else {
    initAll();
}

// ============================================
// Styled Confirmation Modal (pure CSS/JS, no
// Bootstrap Modal dependency)
// ============================================

var _coModalOnConfirm = null;

function _coShowModal() {
    var m = document.getElementById('co-confirm-modal');
    var b = document.getElementById('co-confirm-backdrop');
    if (!b) {
        b = document.createElement('div');
        b.id = 'co-confirm-backdrop';
        document.body.appendChild(b);
    }
    b.style.display = 'block';
    m.style.display = 'flex';
    requestAnimationFrame(function() {
        b.classList.add('co-show');
        m.classList.add('co-show');
    });
}

function _coHideModal() {
    var m = document.getElementById('co-confirm-modal');
    var b = document.getElementById('co-confirm-backdrop');
    m.classList.remove('co-show');
    if (b) b.classList.remove('co-show');
    setTimeout(function() {
        m.style.display = 'none';
        if (b) b.style.display = 'none';
    }, 200);
    _coModalOnConfirm = null;
}

function _coSetupModal(message, variant, confirmText, cancelText, onConfirm) {
    variant = variant || 'warning';
    confirmText = confirmText || 'Yes, confirm';
    cancelText = cancelText || 'No, keep it';

    var iconMap = {
        warning: { bg: 'rgba(245,158,11,0.15)', color: '#F59E0B', icon: 'fa-exclamation-triangle' },
        danger:  { bg: 'rgba(239,68,68,0.15)',  color: '#EF4444', icon: 'fa-trash-alt' },
        info:    { bg: 'rgba(59,130,246,0.15)',  color: '#3B82F6', icon: 'fa-info-circle' },
    };
    var titleMap = { warning: 'Are you sure?', danger: 'Are you sure?', info: 'Please confirm' };
    var s = iconMap[variant] || iconMap.warning;
    var btnClass = variant === 'danger' ? 'btn-danger' : variant === 'info' ? 'btn-primary' : 'btn-warning';

    var iconEl = document.getElementById('co-confirm-icon');
    iconEl.style.background = s.bg;
    iconEl.style.color = s.color;
    iconEl.innerHTML = '<i class="fas ' + s.icon + '"></i>';
    document.getElementById('co-confirm-title').textContent = titleMap[variant] || 'Confirm';
    document.getElementById('co-confirm-message').textContent = message;
    document.getElementById('co-confirm-yes').className = 'btn ' + btnClass;
    document.getElementById('co-confirm-yes').innerHTML = '<i class="fas fa-check me-1"></i>' + confirmText;
    document.getElementById('co-confirm-no').innerHTML = '<i class="fas fa-times me-1"></i>' + cancelText;

    _coModalOnConfirm = onConfirm;
    _coShowModal();
}

function initConfirmModals() {
    if (document.getElementById('co-confirm-modal')) return;

    // Inject modal HTML — pure CSS positioning, no Bootstrap Modal
    document.body.insertAdjacentHTML('beforeend', `
    <div id="co-confirm-modal" class="co-modal-overlay">
      <div class="co-modal-dialog">
        <div class="co-modal-content">
          <div class="co-modal-header">
            <div style="display:flex;align-items:center;gap:12px;">
              <div id="co-confirm-icon" class="co-modal-icon"></div>
              <h5 id="co-confirm-title" style="margin:0;font-size:1.1rem;">Confirm</h5>
            </div>
            <button type="button" class="co-modal-close" id="co-confirm-close">&times;</button>
          </div>
          <div class="co-modal-body">
            <p id="co-confirm-message" style="margin:0;"></p>
          </div>
          <div class="co-modal-footer">
            <button type="button" class="btn btn-outline-secondary" id="co-confirm-no">
              <i class="fas fa-times me-1"></i>No, keep it
            </button>
            <button type="button" class="btn" id="co-confirm-yes">
              <i class="fas fa-check me-1"></i>Yes, confirm
            </button>
          </div>
        </div>
      </div>
    </div>`);

    // Wire up close/cancel buttons
    document.getElementById('co-confirm-close').addEventListener('click', _coHideModal);
    document.getElementById('co-confirm-no').addEventListener('click', _coHideModal);
    document.getElementById('co-confirm-yes').addEventListener('click', function() {
        // Grab callback BEFORE hiding (hide clears it)
        var fn = _coModalOnConfirm;
        _coHideModal();
        if (fn) {
            setTimeout(fn, 50);
        }
    });

    // Close on backdrop click
    document.getElementById('co-confirm-modal').addEventListener('click', function(e) {
        if (e.target === this) _coHideModal();
    });

    // Close on Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && document.getElementById('co-confirm-modal').classList.contains('co-show')) {
            _coHideModal();
        }
    });

    // Intercept all elements with data-confirm attribute
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('[data-confirm]');
        if (!trigger) return;

        e.preventDefault();
        e.stopPropagation();

        _coSetupModal(
            trigger.dataset.confirm,
            trigger.dataset.confirmVariant || 'warning',
            trigger.dataset.confirmYes || 'Yes, confirm',
            trigger.dataset.confirmNo || 'No, keep it',
            function() {
                if (trigger.type === 'submit' || trigger.tagName === 'BUTTON') {
                    var form = trigger.closest('form');
                    if (form) {
                        // ``requestSubmit`` (vs ``submit``) fires the
                        // submit event, which our loading-overlay
                        // handler listens for. Without it, confirmed
                        // long-running actions would slip through
                        // without freezing the screen.
                        if (typeof form.requestSubmit === 'function') {
                            form.requestSubmit();
                        } else {
                            form.submit();
                        }
                    }
                } else if (trigger.href) {
                    window.location.href = trigger.href;
                }
            }
        );
    });
}

// ============================================
// Injected Styles (toast + modal)
// ============================================

(function() {
    const style = document.createElement('style');
    style.textContent = `
        .toast-notification {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: 1rem 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-width: 280px;
            box-shadow: var(--shadow-lg);
            color: var(--text-primary);
        }
        .toast-success { border-color: var(--success); }
        .toast-success i { color: var(--success); }
        .toast-error { border-color: var(--danger); }
        .toast-error i { color: var(--danger); }
        .toast-info i { color: var(--info); }
        .fade-out { opacity: 0; transform: translateX(20px); transition: all 0.3s ease; }

        /* Confirmation modal (pure CSS, no Bootstrap Modal) */
        .co-modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 10000;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s ease;
        }
        .co-modal-overlay.co-show { opacity: 1; }
        #co-confirm-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 9999;
            background: rgba(0,0,0,0.6);
            backdrop-filter: blur(4px);
            opacity: 0;
            transition: opacity 0.2s ease;
        }
        #co-confirm-backdrop.co-show { opacity: 1; }
        .co-modal-dialog {
            max-width: 440px;
            width: 90%;
            margin: auto;
        }
        .co-modal-content {
            background: var(--bg-card, #111113);
            border: 1px solid var(--border-color, #27272A);
            border-radius: var(--radius-lg, 14px);
            color: var(--text-primary, #FAFAFA);
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            transform: translateY(10px) scale(0.98);
            transition: transform 0.2s ease;
        }
        .co-modal-overlay.co-show .co-modal-content {
            transform: translateY(0) scale(1);
        }
        .co-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-color, #27272A);
        }
        .co-modal-icon {
            width: 42px; height: 42px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.1rem; flex-shrink: 0;
        }
        .co-modal-close {
            background: none; border: none; color: var(--text-muted, #71717A);
            font-size: 1.5rem; cursor: pointer; padding: 0; line-height: 1;
        }
        .co-modal-close:hover { color: var(--text-primary, #FAFAFA); }
        .co-modal-body {
            padding: 1.5rem;
            color: var(--text-secondary, #A1A1AA);
            font-size: 0.95rem; line-height: 1.5;
        }
        .co-modal-footer {
            display: flex; justify-content: flex-end; gap: 0.75rem;
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border-color, #27272A);
        }
    `;
    document.head.appendChild(style);
})();

// ============================================
// Navbar: Collapsible folder toggles
// ============================================

(function () {
    'use strict';
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('.folder-toggle').forEach(function (toggle) {
            toggle.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var targetId = toggle.getAttribute('data-target');
                var submenu = document.getElementById(targetId);
                if (!submenu) return;
                var isOpen = submenu.classList.contains('show');
                submenu.classList.toggle('show', !isOpen);
                toggle.classList.toggle('open', !isOpen);
            });
        });

    });
})();


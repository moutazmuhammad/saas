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

    btn.addEventListener('click', () => {
        const instanceId = btn.dataset.instanceId;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i>';

        CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/refresh-usage', {})
            .then(result => {
                if (result && result.cpu_usage !== undefined) {
                    // Update the displayed values
                    const cpuEl = document.getElementById('cpu-usage');
                    const ramEl = document.getElementById('ram-usage');
                    const storageEl = document.getElementById('storage-usage');
                    if (cpuEl) {
                        cpuEl.textContent = result.cpu_usage + '%';
                        const bar = document.getElementById('cpu-bar');
                        if (bar) bar.style.width = result.cpu_usage + '%';
                    }
                    if (ramEl && result.ram_usage !== undefined) {
                        ramEl.textContent = result.ram_usage_display;
                        const bar = document.getElementById('ram-bar');
                        if (bar) bar.style.width = result.ram_pct + '%';
                    }
                    if (storageEl && result.storage_usage !== undefined) {
                        storageEl.textContent = result.storage_usage_display;
                        const bar = document.getElementById('storage-bar');
                        if (bar) bar.style.width = result.storage_pct + '%';
                    }
                    CloudOdoo.showToast('Usage data refreshed', 'success');
                }
            })
            .catch(() => {
                CloudOdoo.showToast('Failed to refresh usage data', 'error');
            })
            .finally(() => {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-sync-alt"></i>';
            });
    });
}

// ============================================
// Provisioning Status Polling
// ============================================

function initStatusPolling() {
    const el = document.getElementById('provisioning-poll');
    if (!el) return;

    const instanceId = el.dataset.instanceId;
    let attempts = 0;
    const maxAttempts = 60; // 60 * 10s = 10 minutes

    function checkStatus() {
        attempts++;
        if (attempts > maxAttempts) {
            clearInterval(poll);
            el.querySelector('div > p').textContent =
                'Provisioning is taking longer than expected. Please refresh the page manually.';
            return;
        }

        CloudOdoo.jsonRpc('/my/instances/' + instanceId + '/status', {})
            .then(result => {
                if (result && result.state &&
                    result.state !== 'provisioning' &&
                    result.state !== 'pending_provision') {
                    clearInterval(poll);
                    window.location.reload();
                }
            })
            .catch(() => {
                // Silently retry on network errors
            });
    }

    // First check after 5 seconds, then every 10 seconds
    setTimeout(checkStatus, 5000);
    const poll = setInterval(checkStatus, 10000);
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
// Page Initialization
// ============================================

function initAll() {
    // Initialize all interactive components
    initThemeToggle();
    initBillingToggle();
    initSubdomainCheck();
    initOTPInputs();
    initOTPTimer();
    initPasswordStrength();
    initInstanceActions();
    initUsageRefresh();
    initStatusPolling();
    initBackupActions();
    initInstanceSort();
    initLoginForm();
    initConfirmModals();
    initInstanceFolders();

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
                    if (form) form.submit();
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

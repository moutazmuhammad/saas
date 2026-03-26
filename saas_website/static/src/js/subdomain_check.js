/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';

publicWidget.registry.SaasSubdomainCheck = publicWidget.Widget.extend({
    selector: '#subdomain',
    events: {
        'input': '_onInput',
    },

    start() {
        this._super(...arguments);
        this._feedback = document.getElementById('subdomain-feedback');
        this._domainSelect = document.getElementById('domain_id');
        this._domainSuffix = document.getElementById('domain-suffix');
        this._submitBtn = this.el.closest('form')?.querySelector('[type="submit"]');
        this._timer = null;
        this._requestId = 0;

        // Re-check and update suffix when domain changes
        if (this._domainSelect) {
            this._domainSelect.addEventListener('change', () => {
                const option = this._domainSelect.selectedOptions[0];
                if (this._domainSuffix && option) {
                    this._domainSuffix.textContent = '.' + option.textContent.trim();
                }
                this._onInput({ target: this.el });
            });
        }
    },

    _onInput(ev) {
        clearTimeout(this._timer);
        const subdomain = ev.target.value.trim().toLowerCase();

        if (!subdomain) {
            this._showFeedback('', '');
            this._setSubmitEnabled(true);
            return;
        }

        // Client-side format check
        if (!/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/.test(subdomain)) {
            this._showFeedback(
                'text-danger',
                '<i class="fa fa-times me-1"></i>Invalid format. Use lowercase letters, digits, and hyphens.',
            );
            this._setSubmitEnabled(false);
            return;
        }

        this._showFeedback('text-muted', '<i class="fa fa-spinner fa-spin me-1"></i>Checking...');
        this._setSubmitEnabled(false);

        // Debounce server check
        this._timer = setTimeout(async () => {
            const currentRequestId = ++this._requestId;
            const domainId = this._domainSelect ? parseInt(this._domainSelect.value) : 0;
            try {
                const result = await rpc('/saas/check-subdomain', {
                    subdomain: subdomain,
                    domain_id: domainId,
                });
                // Ignore stale responses from earlier requests
                if (currentRequestId !== this._requestId) return;
                if (result.available) {
                    this._showFeedback(
                        'text-success',
                        '<i class="fa fa-check me-1"></i>' + result.message,
                    );
                    this._setSubmitEnabled(true);
                } else {
                    this._showFeedback(
                        'text-danger',
                        '<i class="fa fa-times me-1"></i>' + result.message,
                    );
                    this._setSubmitEnabled(false);
                }
            } catch {
                // Ignore stale responses from earlier requests
                if (currentRequestId !== this._requestId) return;
                this._showFeedback(
                    'text-danger',
                    '<i class="fa fa-exclamation-triangle me-1"></i>Could not verify availability. Please try again.',
                );
                this._setSubmitEnabled(false);
            }
        }, 500);
    },

    _showFeedback(cls, html) {
        if (!this._feedback) return;
        this._feedback.className = 'form-text ' + cls;
        this._feedback.innerHTML = html;
    },

    _setSubmitEnabled(enabled) {
        if (!this._submitBtn) return;
        this._submitBtn.disabled = !enabled;
    },
});

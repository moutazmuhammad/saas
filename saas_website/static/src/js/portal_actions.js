/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';

/**
 * Portal self-service actions: restart, stop, start.
 * Binds to .saas-action links with data-action and data-instance-id attributes.
 */
publicWidget.registry.SaasPortalActions = publicWidget.Widget.extend({
    selector: '.saas-action',
    events: {
        'click': '_onClick',
    },

    async _onClick(ev) {
        ev.preventDefault();
        const el = ev.currentTarget;
        const action = el.dataset.action;
        const instanceId = parseInt(el.dataset.instanceId);

        if (!action || !instanceId) {
            console.warn('[SaasPortalActions] Missing required data attributes — action:', action, 'instanceId:', instanceId);
            return;
        }

        const confirmMsg = {
            restart: 'Are you sure you want to restart this instance?',
            stop: 'Are you sure you want to stop this instance?',
            start: 'Are you sure you want to start this instance?',
        }[action];

        if (confirmMsg && !confirm(confirmMsg)) return;

        // Remove any previous inline error message
        const prevError = el.parentElement.querySelector('.saas-action-error');
        if (prevError) prevError.remove();

        // Disable the button while action is in progress
        el.classList.add('disabled');
        const originalHtml = el.innerHTML;
        el.innerHTML = '<i class="fa fa-spinner fa-spin me-2"></i>Processing...';

        const actionLabel = action.charAt(0).toUpperCase() + action.slice(1);

        try {
            const result = await rpc('/my/instances/' + instanceId + '/' + action, {});
            if (result.error) {
                this._showError(el, result.error);
                el.innerHTML = originalHtml;
                el.classList.remove('disabled');
            } else {
                // Show success feedback, then reload to reflect new state
                el.innerHTML = '<i class="fa fa-check me-2"></i>' + actionLabel + ' initiated. Refreshing...';
                setTimeout(() => location.reload(), 2000);
            }
        } catch {
            this._showError(el, 'An error occurred. Please try again.');
            el.innerHTML = originalHtml;
            el.classList.remove('disabled');
        }
    },

    /**
     * Display an inline error message next to the action button.
     * Inserts a Bootstrap alert after the button element.
     */
    _showError(el, message) {
        // Remove any previous error for this button
        const prevError = el.parentElement.querySelector('.saas-action-error');
        if (prevError) prevError.remove();

        const errorEl = document.createElement('div');
        errorEl.className = 'saas-action-error alert alert-danger mt-2 mb-0 py-1 px-2 small';
        errorEl.role = 'alert';
        errorEl.textContent = message;
        el.insertAdjacentElement('afterend', errorEl);
    },
});

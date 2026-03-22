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

        if (!action || !instanceId) return;

        const confirmMsg = {
            restart: 'Are you sure you want to restart this instance?',
            stop: 'Are you sure you want to stop this instance?',
            start: 'Are you sure you want to start this instance?',
        }[action];

        if (confirmMsg && !confirm(confirmMsg)) return;

        // Disable the button while action is in progress
        el.classList.add('disabled');
        const originalHtml = el.innerHTML;
        el.innerHTML = '<i class="fa fa-spinner fa-spin me-2"></i>Processing...';

        try {
            const result = await rpc('/my/instances/' + instanceId + '/' + action, {});
            if (result.error) {
                alert(result.error);
                el.innerHTML = originalHtml;
                el.classList.remove('disabled');
            } else {
                // Reload page after a brief delay to show new state
                setTimeout(() => location.reload(), 2000);
            }
        } catch {
            alert('An error occurred. Please try again.');
            el.innerHTML = originalHtml;
            el.classList.remove('disabled');
        }
    },
});

/**
 * CloudOdoo - Main Application JavaScript
 * Handles all dynamic functionality across pages
 */

// ============================================
// Mock Data Store (simulates backend data)
// ============================================

const AppData = {
    // Current user state
    currentUser: null,
    isLoggedIn: false,

    // Services/Products
    services: [
        {
            id: 1,
            name: 'Odoo ERP',
            subtitle: 'Complete Business Suite',
            icon: 'fas fa-cubes',
            description: 'All-in-one business management software including CRM, Sales, Inventory, Accounting, and more.',
            features: [
                'Sales & CRM Management',
                'Inventory & Warehouse',
                'Accounting & Invoicing',
                'Project Management',
                'HR & Recruitment'
            ],
            plans: [
                { id: 1, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 2, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 10, backups: 3, users: 5, monthlyPrice: 29, yearlyPrice: 279, popular: false },
                { id: 3, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 25, backups: 5, users: 15, monthlyPrice: 79, yearlyPrice: 759, popular: true },
                { id: 4, name: 'Enterprise', isTrial: false, cpu: 4, ram: 4096, storage: 50, backups: 10, users: 50, monthlyPrice: 199, yearlyPrice: 1909, popular: false }
            ]
        },
        {
            id: 2,
            name: 'Odoo CRM',
            subtitle: 'Customer Relationship Management',
            icon: 'fas fa-users',
            description: 'Track leads, close opportunities, and get accurate forecasts.',
            features: [
                'Lead Management',
                'Pipeline Visualization',
                'Email Integration',
                'Activity Scheduling',
                'Reporting & Analytics'
            ],
            plans: [
                { id: 5, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 6, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 10, backups: 3, users: 5, monthlyPrice: 19, yearlyPrice: 182, popular: false },
                { id: 7, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 20, backups: 5, users: 15, monthlyPrice: 49, yearlyPrice: 470, popular: true },
                { id: 8, name: 'Enterprise', isTrial: false, cpu: 4, ram: 4096, storage: 40, backups: 10, users: 50, monthlyPrice: 129, yearlyPrice: 1238, popular: false }
            ]
        },
        {
            id: 3,
            name: 'Odoo Accounting',
            subtitle: 'Financial Management',
            icon: 'fas fa-calculator',
            description: 'Manage your finances effortlessly with automated invoicing, bank synchronization, and reports.',
            features: [
                'Automated Invoicing',
                'Bank Reconciliation',
                'Multi-Currency Support',
                'Tax Management',
                'Financial Reports'
            ],
            plans: [
                { id: 9, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 10, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 10, backups: 3, users: 3, monthlyPrice: 24, yearlyPrice: 230, popular: false },
                { id: 11, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 25, backups: 5, users: 10, monthlyPrice: 59, yearlyPrice: 566, popular: true },
                { id: 12, name: 'Enterprise', isTrial: false, cpu: 4, ram: 4096, storage: 50, backups: 10, users: 30, monthlyPrice: 149, yearlyPrice: 1430, popular: false }
            ]
        },
        {
            id: 4,
            name: 'Odoo eCommerce',
            subtitle: 'Online Store Solution',
            icon: 'fas fa-shopping-cart',
            description: 'Build and manage your online store with powerful eCommerce features.',
            features: [
                'Drag & Drop Builder',
                'Payment Integration',
                'Inventory Sync',
                'SEO Optimization',
                'Mobile Responsive'
            ],
            plans: [
                { id: 13, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 14, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 15, backups: 3, users: 2, monthlyPrice: 34, yearlyPrice: 326, popular: false },
                { id: 15, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 30, backups: 5, users: 5, monthlyPrice: 89, yearlyPrice: 854, popular: true },
                { id: 16, name: 'Enterprise', isTrial: false, cpu: 4, ram: 8192, storage: 100, backups: 15, users: 20, monthlyPrice: 249, yearlyPrice: 2390, popular: false }
            ]
        },
        {
            id: 5,
            name: 'Odoo HR',
            subtitle: 'Human Resources Suite',
            icon: 'fas fa-user-tie',
            description: 'Manage employees, recruitment, time off, and payroll in one place.',
            features: [
                'Employee Directory',
                'Recruitment Pipeline',
                'Time Off Management',
                'Expense Tracking',
                'Performance Reviews'
            ],
            plans: [
                { id: 17, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 18, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 10, backups: 3, users: 10, monthlyPrice: 19, yearlyPrice: 182, popular: false },
                { id: 19, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 20, backups: 5, users: 50, monthlyPrice: 49, yearlyPrice: 470, popular: true },
                { id: 20, name: 'Enterprise', isTrial: false, cpu: 4, ram: 4096, storage: 40, backups: 10, users: 200, monthlyPrice: 129, yearlyPrice: 1238, popular: false }
            ]
        },
        {
            id: 6,
            name: 'Odoo Project',
            subtitle: 'Project Management',
            icon: 'fas fa-tasks',
            description: 'Plan, track, and collaborate on projects with your team.',
            features: [
                'Kanban Boards',
                'Gantt Charts',
                'Time Tracking',
                'Team Collaboration',
                'Milestone Tracking'
            ],
            plans: [
                { id: 21, name: 'Trial', isTrial: true, cpu: 1, ram: 512, storage: 5, backups: 0, users: 1, monthlyPrice: 0, yearlyPrice: 0 },
                { id: 22, name: 'Starter', isTrial: false, cpu: 1, ram: 1024, storage: 10, backups: 3, users: 5, monthlyPrice: 15, yearlyPrice: 144, popular: false },
                { id: 23, name: 'Professional', isTrial: false, cpu: 2, ram: 2048, storage: 20, backups: 5, users: 20, monthlyPrice: 39, yearlyPrice: 374, popular: true },
                { id: 24, name: 'Enterprise', isTrial: false, cpu: 4, ram: 4096, storage: 50, backups: 10, users: 100, monthlyPrice: 99, yearlyPrice: 950, popular: false }
            ]
        }
    ],

    // Available domains
    domains: [
        { id: 1, name: 'cloudodoo.com' },
        { id: 2, name: 'odoocloud.io' },
        { id: 3, name: 'myodoo.app' }
    ],

    // Taken subdomains (for validation)
    takenSubdomains: ['demo', 'test', 'admin', 'api', 'www', 'mail', 'support'],

    // Countries list
    countries: [
        { id: 1, name: 'United States', code: 'US' },
        { id: 2, name: 'United Kingdom', code: 'GB' },
        { id: 3, name: 'Germany', code: 'DE' },
        { id: 4, name: 'France', code: 'FR' },
        { id: 5, name: 'Canada', code: 'CA' },
        { id: 6, name: 'Australia', code: 'AU' },
        { id: 7, name: 'India', code: 'IN' },
        { id: 8, name: 'Japan', code: 'JP' },
        { id: 9, name: 'Brazil', code: 'BR' },
        { id: 10, name: 'UAE', code: 'AE' }
    ],

    // User instances (for logged in users)
    instances: [
        {
            id: 1,
            name: 'my-company',
            serviceId: 1,
            serviceName: 'Odoo ERP',
            planId: 3,
            planName: 'Professional',
            domain: 'cloudodoo.com',
            url: 'https://my-company.cloudodoo.com',
            state: 'running',
            isTrial: false,
            cpuUsage: 25,
            ramUsage: 1024,
            ramLimit: 2048,
            storageUsage: 8.5,
            storageLimit: 25,
            createdAt: '2024-01-15',
            nextBilling: '2024-03-15',
            billingPeriod: 'monthly',
            backups: [
                { id: 1, name: 'Backup 2024-02-14', status: 'completed', date: '2024-02-14' },
                { id: 2, name: 'Backup 2024-02-07', status: 'completed', date: '2024-02-07' }
            ],
            invoices: [
                { id: 'INV-2024-001', date: '2024-02-15', amount: 79, status: 'paid' },
                { id: 'INV-2024-002', date: '2024-01-15', amount: 79, status: 'paid' }
            ]
        },
        {
            id: 2,
            name: 'test-instance',
            serviceId: 2,
            serviceName: 'Odoo CRM',
            planId: 5,
            planName: 'Trial',
            domain: 'cloudodoo.com',
            url: 'https://test-instance.cloudodoo.com',
            state: 'running',
            isTrial: true,
            trialEndsAt: '2024-03-01',
            cpuUsage: 10,
            ramUsage: 256,
            ramLimit: 512,
            storageUsage: 1.2,
            storageLimit: 5,
            createdAt: '2024-02-15',
            backups: [],
            invoices: []
        },
        {
            id: 3,
            name: 'staging-erp',
            serviceId: 1,
            serviceName: 'Odoo ERP',
            planId: 2,
            planName: 'Starter',
            domain: 'odoocloud.io',
            url: 'https://staging-erp.odoocloud.io',
            state: 'stopped',
            isTrial: false,
            cpuUsage: 0,
            ramUsage: 0,
            ramLimit: 1024,
            storageUsage: 4.3,
            storageLimit: 10,
            createdAt: '2024-01-20',
            nextBilling: '2024-03-20',
            billingPeriod: 'monthly',
            backups: [
                { id: 3, name: 'Backup 2024-02-10', status: 'completed', date: '2024-02-10' }
            ],
            invoices: [
                { id: 'INV-2024-003', date: '2024-02-20', amount: 29, status: 'not_paid' }
            ]
        }
    ]
};

// ============================================
// Utility Functions
// ============================================

const Utils = {
    // Format currency
    formatCurrency(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(amount);
    },

    // Format date
    formatDate(dateStr) {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    },

    // Format bytes to GB/MB
    formatStorage(mb) {
        if (mb >= 1024) {
            return (mb / 1024).toFixed(1) + ' GB';
        }
        return mb + ' MB';
    },

    // Get URL parameters
    getUrlParams() {
        const params = new URLSearchParams(window.location.search);
        const obj = {};
        for (const [key, value] of params) {
            obj[key] = value;
        }
        return obj;
    },

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

    // Validate subdomain format
    isValidSubdomain(subdomain) {
        const regex = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
        return regex.test(subdomain);
    },

    // Check if subdomain is available
    isSubdomainAvailable(subdomain) {
        return !AppData.takenSubdomains.includes(subdomain.toLowerCase());
    },

    // Calculate yearly discount percentage
    getYearlyDiscount(monthlyPrice, yearlyPrice) {
        const expectedYearly = monthlyPrice * 12;
        const discount = ((expectedYearly - yearlyPrice) / expectedYearly) * 100;
        return Math.round(discount);
    },

    // Show toast notification
    showToast(message, type = 'info') {
        const toastContainer = document.getElementById('toast-container') || createToastContainer();
        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type} fade-in`;
        toast.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
            <span>${message}</span>
        `;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
};

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = 'position:fixed;top:100px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;';
    document.body.appendChild(container);
    return container;
}

// ============================================
// Page Controllers
// ============================================

// Services Catalog Page
const ServicesPage = {
    init() {
        const container = document.getElementById('services-grid');
        if (!container) return;

        this.renderServices(container);
    },

    renderServices(container) {
        if (AppData.services.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="empty-state">
                        <div class="empty-state-icon">
                            <i class="fas fa-box-open"></i>
                        </div>
                        <h5>No services available</h5>
                        <p>Please check back soon for available services.</p>
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = AppData.services.map(service => `
            <div class="col-md-6 col-lg-4">
                <div class="service-card">
                    <div class="service-icon">
                        <i class="${service.icon}"></i>
                    </div>
                    <h4>${service.name}</h4>
                    <p class="service-subtitle">${service.subtitle}</p>
                    <ul class="feature-list">
                        ${service.features.slice(0, 5).map(f => `
                            <li><i class="fas fa-check"></i>${f}</li>
                        `).join('')}
                    </ul>
                    <p class="plan-count">
                        <i class="fas fa-layer-group me-1"></i>
                        ${service.plans.filter(p => !p.isTrial).length} plans available
                    </p>
                    <a href="/service-plans.html?id=${service.id}" class="btn btn-primary w-100">
                        View Plans
                    </a>
                </div>
            </div>
        `).join('');
    }
};

// Service Plans Page
const PlansPage = {
    currentBilling: 'monthly',
    service: null,

    init() {
        const params = Utils.getUrlParams();
        const serviceId = parseInt(params.id);
        
        this.service = AppData.services.find(s => s.id === serviceId);
        
        if (!this.service) {
            window.location.href = '/services.html';
            return;
        }

        this.renderHeader();
        this.renderTrialBanner();
        this.setupBillingToggle();
        this.renderPlans();
    },

    renderHeader() {
        const header = document.getElementById('service-header');
        if (!header) return;

        header.innerHTML = `
            <div class="d-flex align-items-start gap-4">
                <div class="service-icon" style="width:80px;height:80px;font-size:2rem;">
                    <i class="${this.service.icon}"></i>
                </div>
                <div>
                    <h1 class="mb-2">${this.service.name}</h1>
                    <p class="text-muted mb-3">${this.service.subtitle}</p>
                    <p class="mb-0">${this.service.description}</p>
                </div>
            </div>
        `;
    },

    renderTrialBanner() {
        const banner = document.getElementById('trial-banner');
        if (!banner) return;

        const trialPlan = this.service.plans.find(p => p.isTrial);
        if (!trialPlan) {
            banner.style.display = 'none';
            return;
        }

        banner.innerHTML = `
            <div class="trial-banner">
                <div class="d-md-flex align-items-center justify-content-between">
                    <div class="mb-3 mb-md-0">
                        <h5 class="mb-1"><i class="fas fa-gift me-2"></i>Start with a Free Trial</h5>
                        <p class="mb-0 text-muted">No credit card required. Get ${trialPlan.cpu} vCPU, ${Utils.formatStorage(trialPlan.ram)} RAM, ${trialPlan.storage}GB storage.</p>
                    </div>
                    <a href="/configure.html?service=${this.service.id}&plan=${trialPlan.id}" class="btn btn-success">
                        <i class="fas fa-rocket me-2"></i>Start Free Trial
                    </a>
                </div>
            </div>
        `;
    },

    setupBillingToggle() {
        const toggle = document.getElementById('billing-toggle');
        if (!toggle) return;

        const discount = Utils.getYearlyDiscount(
            this.service.plans.find(p => !p.isTrial)?.monthlyPrice || 0,
            this.service.plans.find(p => !p.isTrial)?.yearlyPrice || 0
        );

        toggle.innerHTML = `
            <div class="billing-toggle">
                <button class="toggle-btn active" data-billing="monthly">Monthly</button>
                <button class="toggle-btn" data-billing="yearly">Yearly <span class="yearly-badge">Save ${discount}%</span></button>
            </div>
        `;

        toggle.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                toggle.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentBilling = btn.dataset.billing;
                this.renderPlans();
            });
        });
    },

    renderPlans() {
        const container = document.getElementById('plans-grid');
        if (!container) return;

        const paidPlans = this.service.plans.filter(p => !p.isTrial);

        container.innerHTML = paidPlans.map(plan => {
            const price = this.currentBilling === 'monthly' ? plan.monthlyPrice : Math.round(plan.yearlyPrice / 12);
            const originalPrice = plan.monthlyPrice;
            const showDiscount = this.currentBilling === 'yearly' && price < originalPrice;

            return `
                <div class="col-md-6 col-lg-4">
                    <div class="plan-card ${plan.popular ? 'popular' : ''}">
                        ${plan.popular ? '<span class="plan-badge">Most Popular</span>' : ''}
                        <h4 class="plan-name">${plan.name}</h4>
                        <div class="plan-price">
                            ${showDiscount ? `<span class="original">${Utils.formatCurrency(originalPrice)}</span>` : ''}
                            <span class="amount">${Utils.formatCurrency(price)}</span>
                            <span class="period">/${this.currentBilling === 'monthly' ? 'mo' : 'mo (billed yearly)'}</span>
                        </div>
                        <ul class="plan-specs">
                            <li><i class="fas fa-microchip"></i>${plan.cpu} vCPU</li>
                            <li><i class="fas fa-memory"></i>${Utils.formatStorage(plan.ram)} RAM</li>
                            <li><i class="fas fa-hdd"></i>${plan.storage} GB Storage</li>
                            <li><i class="fas fa-shield-alt"></i>${plan.backups} Backups</li>
                            <li><i class="fas fa-users"></i>Up to ${plan.users} Users</li>
                        </ul>
                        <a href="/configure.html?service=${this.service.id}&plan=${plan.id}&billing=${this.currentBilling}" 
                           class="btn ${plan.popular ? 'btn-primary' : 'btn-outline-light'} w-100">
                            Get Started
                        </a>
                    </div>
                </div>
            `;
        }).join('');
    }
};

// Configure Page
const ConfigurePage = {
    service: null,
    plan: null,
    billing: 'monthly',
    subdomainValid: false,

    init() {
        const params = Utils.getUrlParams();
        const serviceId = parseInt(params.service);
        const planId = parseInt(params.plan);
        this.billing = params.billing || 'monthly';

        this.service = AppData.services.find(s => s.id === serviceId);
        if (!this.service) {
            window.location.href = '/services.html';
            return;
        }

        this.plan = this.service.plans.find(p => p.id === planId);
        if (!this.plan) {
            window.location.href = `/service-plans.html?id=${serviceId}`;
            return;
        }

        this.renderForm();
        this.renderSummary();
        this.setupSubdomainValidation();
        this.setupFormSubmit();
    },

    renderForm() {
        const form = document.getElementById('configure-form');
        if (!form) return;

        form.innerHTML = `
            <h4 class="mb-4">Configure Your Instance</h4>
            
            <div class="mb-4">
                <label class="form-label">Choose your subdomain</label>
                <div class="input-icon">
                    <i class="fas fa-globe"></i>
                    <input type="text" class="form-control" id="subdomain-input" 
                           placeholder="my-company" autocomplete="off">
                </div>
                <div id="subdomain-feedback" class="mt-2"></div>
            </div>

            <div class="mb-4">
                <label class="form-label">Select your domain</label>
                <select class="form-select" id="domain-select">
                    ${AppData.domains.map(d => `
                        <option value="${d.id}">${d.name}</option>
                    `).join('')}
                </select>
            </div>

            <div class="subdomain-preview mb-4">
                <i class="fas fa-link me-2"></i>
                <span id="url-preview">your-subdomain.${AppData.domains[0].name}</span>
            </div>

            <button type="submit" class="btn ${this.plan.isTrial ? 'btn-success' : 'btn-primary'} btn-lg w-100" 
                    id="submit-btn" disabled>
                <i class="fas fa-${this.plan.isTrial ? 'rocket' : 'credit-card'} me-2"></i>
                ${this.plan.isTrial ? 'Start Free Trial' : 'Continue to Payment'}
            </button>
        `;
    },

    renderSummary() {
        const summary = document.getElementById('order-summary');
        if (!summary) return;

        const price = this.billing === 'monthly' ? this.plan.monthlyPrice : this.plan.yearlyPrice;

        summary.innerHTML = `
            <div class="order-summary">
                <h5><i class="fas fa-shopping-cart me-2"></i>Order Summary</h5>
                
                <div class="d-flex align-items-center gap-3 mb-3 pb-3 border-bottom" style="border-color:var(--border-color)!important;">
                    <div class="service-icon" style="width:48px;height:48px;font-size:1.25rem;">
                        <i class="${this.service.icon}"></i>
                    </div>
                    <div>
                        <div class="fw-semibold">${this.service.name}</div>
                        <div class="text-muted small">${this.plan.name} Plan</div>
                    </div>
                </div>

                ${this.plan.isTrial ? `
                    <div class="alert-banner alert-success mb-3">
                        <i class="fas fa-gift"></i>
                        <div>
                            <strong>Free Trial</strong>
                            <p class="small mb-0 mt-1">14 days free, no credit card required</p>
                        </div>
                    </div>
                ` : ''}

                <div class="summary-item">
                    <span class="label"><i class="fas fa-microchip me-2"></i>CPU</span>
                    <span class="value">${this.plan.cpu} vCPU</span>
                </div>
                <div class="summary-item">
                    <span class="label"><i class="fas fa-memory me-2"></i>RAM</span>
                    <span class="value">${Utils.formatStorage(this.plan.ram)}</span>
                </div>
                <div class="summary-item">
                    <span class="label"><i class="fas fa-hdd me-2"></i>Storage</span>
                    <span class="value">${this.plan.storage} GB</span>
                </div>
                <div class="summary-item">
                    <span class="label"><i class="fas fa-shield-alt me-2"></i>Backups</span>
                    <span class="value">${this.plan.backups || 'Not included'}</span>
                </div>

                ${!this.plan.isTrial ? `
                    <div class="summary-total">
                        <span>Total</span>
                        <span>${Utils.formatCurrency(price)}${this.billing === 'monthly' ? '/mo' : '/yr'}</span>
                    </div>
                ` : ''}

                <p class="text-muted small mt-3 mb-0">
                    <i class="fas fa-info-circle me-1"></i>
                    You can upgrade or downgrade anytime
                </p>
            </div>
        `;
    },

    setupSubdomainValidation() {
        const input = document.getElementById('subdomain-input');
        const feedback = document.getElementById('subdomain-feedback');
        const preview = document.getElementById('url-preview');
        const domainSelect = document.getElementById('domain-select');
        const submitBtn = document.getElementById('submit-btn');

        const updatePreview = () => {
            const subdomain = input.value.toLowerCase() || 'your-subdomain';
            const domain = AppData.domains.find(d => d.id === parseInt(domainSelect.value))?.name;
            preview.innerHTML = `<span class="subdomain">${subdomain}</span>.${domain}`;
        };

        const validateSubdomain = Utils.debounce(() => {
            const value = input.value.toLowerCase().trim();
            
            if (!value) {
                feedback.innerHTML = '';
                input.classList.remove('is-valid', 'is-invalid');
                this.subdomainValid = false;
                submitBtn.disabled = true;
                return;
            }

            // Show loading
            feedback.innerHTML = '<span class="text-muted"><span class="spinner-sm me-2"></span>Checking availability...</span>';

            // Simulate API call
            setTimeout(() => {
                if (!Utils.isValidSubdomain(value)) {
                    input.classList.remove('is-valid');
                    input.classList.add('is-invalid');
                    feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>Invalid format. Use lowercase letters, numbers, and hyphens only.</span>';
                    this.subdomainValid = false;
                } else if (!Utils.isSubdomainAvailable(value)) {
                    input.classList.remove('is-valid');
                    input.classList.add('is-invalid');
                    feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>This subdomain is already taken.</span>';
                    this.subdomainValid = false;
                } else {
                    input.classList.remove('is-invalid');
                    input.classList.add('is-valid');
                    feedback.innerHTML = '<span class="valid-feedback d-block"><i class="fas fa-check me-1"></i>Subdomain is available!</span>';
                    this.subdomainValid = true;
                }
                submitBtn.disabled = !this.subdomainValid;
            }, 500);
        }, 500);

        input.addEventListener('input', () => {
            input.value = input.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
            updatePreview();
            validateSubdomain();
        });

        domainSelect.addEventListener('change', updatePreview);
    },

    setupFormSubmit() {
        const form = document.getElementById('configure-form');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            
            if (!this.subdomainValid) return;

            const subdomain = document.getElementById('subdomain-input').value;
            const domainId = document.getElementById('domain-select').value;

            if (this.plan.isTrial) {
                // Simulate creating trial instance
                Utils.showToast('Creating your trial instance...', 'info');
                setTimeout(() => {
                    window.location.href = '/my-instances.html';
                }, 1500);
            } else {
                // Go to checkout
                window.location.href = `/checkout.html?service=${this.service.id}&plan=${this.plan.id}&subdomain=${subdomain}&domain=${domainId}&billing=${this.billing}`;
            }
        });
    }
};

// Registration Page
const RegisterPage = {
    currentStep: 1,
    formData: {},
    otpTimer: null,
    otpExpiry: 600, // 10 minutes in seconds

    init() {
        this.renderStep1();
        this.populateCountries();
    },

    renderStep1() {
        const container = document.getElementById('registration-container');
        if (!container) return;

        container.innerHTML = `
            <div class="step-indicator">
                <div class="step active">
                    <span class="step-number">1</span>
                    <span class="step-label">Account Details</span>
                </div>
                <div class="step-line"></div>
                <div class="step">
                    <span class="step-number">2</span>
                    <span class="step-label">Verify Phone</span>
                </div>
            </div>

            <h3 class="text-center mb-2">Create Your Account</h3>
            <p class="text-center text-muted mb-4">Get started in minutes</p>

            <form id="register-form">
                <div class="row g-3">
                    <div class="col-12">
                        <div class="input-icon">
                            <i class="fas fa-user"></i>
                            <input type="text" class="form-control" id="fullname" placeholder="Full Name" required>
                        </div>
                    </div>
                    <div class="col-12">
                        <div class="input-icon">
                            <i class="fas fa-envelope"></i>
                            <input type="email" class="form-control" id="email" placeholder="Email Address" required>
                        </div>
                    </div>
                    <div class="col-12">
                        <div class="input-icon">
                            <i class="fas fa-phone"></i>
                            <input type="tel" class="form-control" id="phone" placeholder="Phone Number" required>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="input-icon">
                            <i class="fas fa-building"></i>
                            <input type="text" class="form-control" id="company" placeholder="Company Name (optional)">
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="input-icon">
                            <i class="fas fa-globe"></i>
                            <select class="form-select" id="country" required style="padding-left:2.75rem;">
                                <option value="">Select Country</option>
                            </select>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="input-icon">
                            <i class="fas fa-map-marker-alt"></i>
                            <input type="text" class="form-control" id="city" placeholder="City" required>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="input-icon">
                            <i class="fas fa-briefcase"></i>
                            <input type="text" class="form-control" id="jobtitle" placeholder="Job Title (optional)">
                        </div>
                    </div>
                    <div class="col-12">
                        <div class="input-icon">
                            <i class="fas fa-lock"></i>
                            <input type="password" class="form-control" id="password" placeholder="Password (min 8 characters)" required minlength="8">
                        </div>
                        <div class="password-strength mt-2">
                            <div class="strength-bar" id="strength-bar"></div>
                        </div>
                    </div>
                    <div class="col-12">
                        <div class="input-icon">
                            <i class="fas fa-lock"></i>
                            <input type="password" class="form-control" id="confirm-password" placeholder="Confirm Password" required>
                        </div>
                        <div id="password-match" class="mt-2"></div>
                    </div>
                </div>

                <button type="submit" class="btn btn-primary btn-lg w-100 mt-4">
                    Continue <i class="fas fa-arrow-right ms-2"></i>
                </button>

                <p class="text-center text-muted mt-4 mb-0">
                    Already have an account? <a href="/login.html">Sign in</a>
                </p>
            </form>
        `;

        this.populateCountries();
        this.setupPasswordValidation();
        this.setupStep1Submit();
    },

    populateCountries() {
        const select = document.getElementById('country');
        if (!select) return;

        AppData.countries.forEach(country => {
            const option = document.createElement('option');
            option.value = country.id;
            option.textContent = country.name;
            select.appendChild(option);
        });
    },

    setupPasswordValidation() {
        const password = document.getElementById('password');
        const confirm = document.getElementById('confirm-password');
        const strengthBar = document.getElementById('strength-bar');
        const matchFeedback = document.getElementById('password-match');

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

            this.checkPasswordMatch();
        });

        confirm.addEventListener('input', () => this.checkPasswordMatch());
    },

    checkPasswordMatch() {
        const password = document.getElementById('password');
        const confirm = document.getElementById('confirm-password');
        const feedback = document.getElementById('password-match');

        if (!confirm.value) {
            feedback.innerHTML = '';
            return;
        }

        if (password.value === confirm.value) {
            feedback.innerHTML = '<span class="valid-feedback d-block"><i class="fas fa-check me-1"></i>Passwords match</span>';
        } else {
            feedback.innerHTML = '<span class="invalid-feedback d-block"><i class="fas fa-times me-1"></i>Passwords do not match</span>';
        }
    },

    setupStep1Submit() {
        const form = document.getElementById('register-form');
        form.addEventListener('submit', (e) => {
            e.preventDefault();

            const password = document.getElementById('password').value;
            const confirm = document.getElementById('confirm-password').value;

            if (password !== confirm) {
                Utils.showToast('Passwords do not match', 'error');
                return;
            }

            this.formData = {
                fullname: document.getElementById('fullname').value,
                email: document.getElementById('email').value,
                phone: document.getElementById('phone').value,
                company: document.getElementById('company').value,
                country: document.getElementById('country').value,
                city: document.getElementById('city').value,
                jobtitle: document.getElementById('jobtitle').value,
                password: password
            };

            this.renderStep2();
        });
    },

    renderStep2() {
        const container = document.getElementById('registration-container');
        
        container.innerHTML = `
            <div class="step-indicator">
                <div class="step completed">
                    <span class="step-number"><i class="fas fa-check"></i></span>
                    <span class="step-label">Account Details</span>
                </div>
                <div class="step-line completed"></div>
                <div class="step active">
                    <span class="step-number">2</span>
                    <span class="step-label">Verify Phone</span>
                </div>
            </div>

            <div class="text-center">
                <div class="mb-4">
                    <div class="empty-state-icon mx-auto mb-3">
                        <i class="fas fa-sms"></i>
                    </div>
                    <h3 class="mb-2">Verify Your Phone Number</h3>
                    <p class="text-muted">We sent a 6-digit code to <strong>${this.formData.phone}</strong></p>
                </div>

                <form id="otp-form">
                    <div class="otp-inputs mb-4">
                        <input type="text" class="otp-input" maxlength="1" data-index="0">
                        <input type="text" class="otp-input" maxlength="1" data-index="1">
                        <input type="text" class="otp-input" maxlength="1" data-index="2">
                        <input type="text" class="otp-input" maxlength="1" data-index="3">
                        <input type="text" class="otp-input" maxlength="1" data-index="4">
                        <input type="text" class="otp-input" maxlength="1" data-index="5">
                    </div>

                    <p class="text-muted mb-4">
                        Code expires in <span class="countdown-timer" id="otp-timer">10:00</span>
                    </p>

                    <button type="submit" class="btn btn-primary btn-lg w-100 mb-3">
                        Verify & Create Account
                    </button>

                    <button type="button" class="btn btn-outline-secondary w-100" id="resend-btn">
                        <i class="fas fa-redo me-2"></i>Resend Code
                    </button>
                </form>
            </div>
        `;

        this.setupOTPInputs();
        this.startOTPTimer();
        this.setupStep2Submit();
    },

    setupOTPInputs() {
        const inputs = document.querySelectorAll('.otp-input');
        
        inputs.forEach((input, index) => {
            input.addEventListener('input', (e) => {
                const value = e.target.value;
                if (value && index < inputs.length - 1) {
                    inputs[index + 1].focus();
                }
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !input.value && index > 0) {
                    inputs[index - 1].focus();
                }
            });

            input.addEventListener('paste', (e) => {
                e.preventDefault();
                const paste = e.clipboardData.getData('text').slice(0, 6);
                [...paste].forEach((char, i) => {
                    if (inputs[i]) inputs[i].value = char;
                });
            });
        });

        inputs[0].focus();
    },

    startOTPTimer() {
        let remaining = this.otpExpiry;
        const timerEl = document.getElementById('otp-timer');

        this.otpTimer = setInterval(() => {
            remaining--;
            const minutes = Math.floor(remaining / 60);
            const seconds = remaining % 60;
            timerEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;

            if (remaining <= 0) {
                clearInterval(this.otpTimer);
                timerEl.textContent = 'Expired';
            }
        }, 1000);
    },

    setupStep2Submit() {
        const form = document.getElementById('otp-form');
        const resendBtn = document.getElementById('resend-btn');

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const otp = [...document.querySelectorAll('.otp-input')].map(i => i.value).join('');
            
            if (otp.length !== 6) {
                Utils.showToast('Please enter the complete 6-digit code', 'error');
                return;
            }

            // Simulate verification (accept any 6-digit code)
            Utils.showToast('Account created successfully!', 'success');
            
            // Store user data
            AppData.currentUser = this.formData;
            AppData.isLoggedIn = true;

            // Redirect
            const params = Utils.getUrlParams();
            if (params.redirect) {
                window.location.href = decodeURIComponent(params.redirect);
            } else {
                window.location.href = '/my-instances.html';
            }
        });

        resendBtn.addEventListener('click', () => {
            clearInterval(this.otpTimer);
            this.otpExpiry = 600;
            this.startOTPTimer();
            Utils.showToast('New code sent!', 'success');
        });
    }
};

// My Instances Page
const InstancesPage = {
    sortBy: 'date',

    init() {
        this.renderInstances();
        this.setupSort();
    },

    setupSort() {
        const sortSelect = document.getElementById('sort-select');
        if (!sortSelect) return;

        sortSelect.addEventListener('change', (e) => {
            this.sortBy = e.target.value;
            this.renderInstances();
        });
    },

    renderInstances() {
        const container = document.getElementById('instances-list');
        if (!container) return;

        let instances = [...AppData.instances];

        // Sort
        if (this.sortBy === 'date') {
            instances.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
        } else if (this.sortBy === 'name') {
            instances.sort((a, b) => a.name.localeCompare(b.name));
        } else if (this.sortBy === 'status') {
            instances.sort((a, b) => a.state.localeCompare(b.state));
        }

        if (instances.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">
                        <i class="fas fa-server"></i>
                    </div>
                    <h5>No instances yet</h5>
                    <p>Create your first cloud instance to get started.</p>
                    <a href="/services.html" class="btn btn-primary">
                        <i class="fas fa-plus me-2"></i>Browse Services
                    </a>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="table-responsive">
                <table class="table table-dark-custom">
                    <thead>
                        <tr>
                            <th>Instance</th>
                            <th>Service</th>
                            <th>Plan</th>
                            <th>Status</th>
                            <th>URL</th>
                            <th>Created</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${instances.map(inst => `
                            <tr>
                                <td>
                                    <a href="/instance-detail.html?id=${inst.id}" class="fw-semibold text-primary">
                                        ${inst.name}
                                    </a>
                                </td>
                                <td>${inst.serviceName}</td>
                                <td>
                                    ${inst.planName}
                                    ${inst.isTrial ? '<span class="badge bg-info ms-1">Trial</span>' : ''}
                                </td>
                                <td>
                                    <span class="badge-status badge-${inst.state}">
                                        ${inst.state === 'running' ? '<i class="fas fa-circle"></i>' : ''}
                                        ${inst.state === 'provisioning' ? '<span class="spinner-sm"></span>' : ''}
                                        ${inst.state.charAt(0).toUpperCase() + inst.state.slice(1)}
                                    </span>
                                </td>
                                <td>
                                    ${inst.state === 'running' ? `
                                        <a href="${inst.url}" target="_blank" class="text-muted small">
                                            ${inst.name}.${inst.domain} <i class="fas fa-external-link-alt ms-1"></i>
                                        </a>
                                    ` : '<span class="text-muted">—</span>'}
                                </td>
                                <td class="text-muted">${Utils.formatDate(inst.createdAt)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }
};

// Instance Detail Page
const InstanceDetailPage = {
    instance: null,
    pollingInterval: null,

    init() {
        const params = Utils.getUrlParams();
        const instanceId = parseInt(params.id);
        
        this.instance = AppData.instances.find(i => i.id === instanceId);
        
        if (!this.instance) {
            window.location.href = '/my-instances.html';
            return;
        }

        this.renderPage();
        this.setupPolling();
    },

    renderPage() {
        this.renderInstanceInfo();
        this.renderResourceUsage();
        this.renderAlerts();
        this.renderBilling();
        this.renderBackups();
        this.renderActions();
        this.renderPlanDetails();
    },

    renderInstanceInfo() {
        const container = document.getElementById('instance-info');
        if (!container) return;

        container.innerHTML = `
            <div class="info-card">
                <div class="d-flex justify-content-between align-items-start mb-3">
                    <div>
                        <h4 class="mb-1">${this.instance.name}</h4>
                        <span class="badge-status badge-${this.instance.state}">
                            ${this.instance.state === 'running' ? '<i class="fas fa-circle"></i>' : ''}
                            ${this.instance.state === 'provisioning' ? '<span class="spinner-sm"></span>' : ''}
                            ${this.instance.state.charAt(0).toUpperCase() + this.instance.state.slice(1)}
                        </span>
                    </div>
                </div>
                
                <div class="row g-3">
                    <div class="col-md-6">
                        <div class="text-muted small">URL</div>
                        ${this.instance.state === 'running' ? `
                            <a href="${this.instance.url}" target="_blank">
                                ${this.instance.url} <i class="fas fa-external-link-alt ms-1"></i>
                            </a>
                        ` : '<span class="text-muted">Not available</span>'}
                    </div>
                    <div class="col-md-6">
                        <div class="text-muted small">Service</div>
                        <div>${this.instance.serviceName}</div>
                    </div>
                    <div class="col-md-6">
                        <div class="text-muted small">Plan</div>
                        <div>${this.instance.planName} ${this.instance.isTrial ? '<span class="badge bg-info">Trial</span>' : ''}</div>
                    </div>
                    <div class="col-md-6">
                        <div class="text-muted small">Domain</div>
                        <div>${this.instance.name}.${this.instance.domain}</div>
                    </div>
                </div>
            </div>
        `;
    },

    renderResourceUsage() {
        const container = document.getElementById('resource-usage');
        if (!container) return;

        if (!['running', 'stopped'].includes(this.instance.state)) {
            container.innerHTML = '';
            return;
        }

        const cpuPct = this.instance.cpuUsage;
        const ramPct = Math.round((this.instance.ramUsage / this.instance.ramLimit) * 100);
        const storagePct = Math.round((this.instance.storageUsage / this.instance.storageLimit) * 100);

        const getBarColor = (pct) => {
            if (pct < 60) return 'bg-success';
            if (pct < 80) return 'bg-warning';
            return 'bg-danger';
        };

        container.innerHTML = `
            <div class="info-card">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h5 class="mb-0">Resource Usage</h5>
                    <button class="btn btn-sm btn-outline-secondary" id="refresh-usage">
                        <i class="fas fa-sync-alt"></i>
                    </button>
                </div>

                <div class="resource-item">
                    <div class="resource-header">
                        <span class="resource-label"><i class="fas fa-microchip me-2"></i>CPU</span>
                        <span class="resource-value">${cpuPct}%</span>
                    </div>
                    <div class="progress">
                        <div class="progress-bar ${getBarColor(cpuPct)}" style="width:${cpuPct}%"></div>
                    </div>
                </div>

                <div class="resource-item">
                    <div class="resource-header">
                        <span class="resource-label"><i class="fas fa-memory me-2"></i>RAM</span>
                        <span class="resource-value">${Utils.formatStorage(this.instance.ramUsage)} / ${Utils.formatStorage(this.instance.ramLimit)}</span>
                    </div>
                    <div class="progress">
                        <div class="progress-bar ${getBarColor(ramPct)}" style="width:${ramPct}%"></div>
                    </div>
                </div>

                <div class="resource-item mb-0">
                    <div class="resource-header">
                        <span class="resource-label"><i class="fas fa-hdd me-2"></i>Storage</span>
                        <span class="resource-value">${this.instance.storageUsage} GB / ${this.instance.storageLimit} GB</span>
                    </div>
                    <div class="progress">
                        <div class="progress-bar ${getBarColor(storagePct)}" style="width:${storagePct}%"></div>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('refresh-usage')?.addEventListener('click', () => {
            Utils.showToast('Refreshing usage data...', 'info');
            // Simulate refresh
            setTimeout(() => {
                this.instance.cpuUsage = Math.floor(Math.random() * 60) + 10;
                this.renderResourceUsage();
            }, 1000);
        });
    },

    renderAlerts() {
        const container = document.getElementById('instance-alerts');
        if (!container) return;

        let alertHtml = '';

        if (this.instance.isTrial && this.instance.state === 'running') {
            alertHtml += `
                <div class="alert-banner alert-info">
                    <i class="fas fa-info-circle"></i>
                    <div class="flex-grow-1">
                        <strong>Free Trial Active</strong>
                        <p class="mb-2">Your trial ends on ${Utils.formatDate(this.instance.trialEndsAt)}. Upgrade to keep your instance running.</p>
                        <a href="/upgrade.html?id=${this.instance.id}" class="btn btn-sm btn-primary">Upgrade Now</a>
                    </div>
                </div>
            `;
        }

        if (this.instance.state === 'pending_payment') {
            alertHtml += `
                <div class="alert-banner alert-warning">
                    <i class="fas fa-exclamation-triangle"></i>
                    <div class="flex-grow-1">
                        <strong>Payment Required</strong>
                        <p class="mb-2">Complete your payment to activate this instance.</p>
                        <a href="/checkout.html?instance=${this.instance.id}" class="btn btn-sm btn-warning">Complete Payment</a>
                    </div>
                </div>
            `;
        }

        if (this.instance.state === 'provisioning') {
            alertHtml += `
                <div class="alert-banner alert-info">
                    <i class="fas fa-spinner fa-spin"></i>
                    <div>
                        <strong>Setting Up Your Instance</strong>
                        <p class="mb-0">This usually takes a few minutes. The page will refresh automatically.</p>
                    </div>
                </div>
            `;
        }

        container.innerHTML = alertHtml;
    },

    renderBilling() {
        const container = document.getElementById('billing-section');
        if (!container) return;

        container.innerHTML = `
            <div class="info-card">
                <h5>Invoices</h5>
                ${this.instance.invoices.length === 0 ? `
                    <p class="text-muted mb-0">No invoices yet</p>
                ` : `
                    <div class="table-responsive">
                        <table class="table table-dark-custom mb-0">
                            <thead>
                                <tr>
                                    <th>Invoice</th>
                                    <th>Date</th>
                                    <th>Amount</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${this.instance.invoices.map(inv => `
                                    <tr>
                                        <td><a href="#">${inv.id}</a></td>
                                        <td>${Utils.formatDate(inv.date)}</td>
                                        <td>${Utils.formatCurrency(inv.amount)}</td>
                                        <td>
                                            <span class="badge-status badge-${inv.status === 'paid' ? 'running' : 'failed'}">
                                                ${inv.status === 'paid' ? 'Paid' : 'Not Paid'}
                                            </span>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        `;
    },

    renderBackups() {
        const container = document.getElementById('backups-section');
        if (!container) return;

        const canBackup = !this.instance.isTrial && this.instance.state === 'running';
        const service = AppData.services.find(s => s.id === this.instance.serviceId);
        const plan = service?.plans.find(p => p.id === this.instance.planId);
        const backupLimit = plan?.backups || 0;

        container.innerHTML = `
            <div class="info-card">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h5 class="mb-0">Backups</h5>
                    <div class="d-flex align-items-center gap-3">
                        <span class="text-muted small">${this.instance.backups.length} / ${backupLimit} used</span>
                        <button class="btn btn-sm btn-primary" ${!canBackup ? 'disabled' : ''} id="create-backup">
                            <i class="fas fa-plus me-1"></i>Create Backup
                        </button>
                    </div>
                </div>

                ${this.instance.isTrial ? `
                    <p class="text-muted small mb-3"><i class="fas fa-info-circle me-1"></i>Backups are not available on the trial plan</p>
                ` : ''}

                ${this.instance.backups.length === 0 ? `
                    <p class="text-muted mb-0">No backups yet</p>
                ` : `
                    <div class="table-responsive">
                        <table class="table table-dark-custom mb-0">
                            <thead>
                                <tr>
                                    <th>Backup</th>
                                    <th>Date</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${this.instance.backups.map(backup => `
                                    <tr>
                                        <td>${backup.name}</td>
                                        <td>${Utils.formatDate(backup.date)}</td>
                                        <td>
                                            <span class="badge-status badge-${backup.status === 'completed' ? 'running' : 'provisioning'}">
                                                ${backup.status === 'running' ? '<span class="spinner-sm"></span>' : ''}
                                                ${backup.status.charAt(0).toUpperCase() + backup.status.slice(1)}
                                            </span>
                                        </td>
                                        <td>
                                            ${backup.status === 'completed' ? `
                                                <button class="btn btn-sm btn-outline-secondary" data-backup="${backup.id}">
                                                    <i class="fas fa-undo"></i> Restore
                                                </button>
                                            ` : ''}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        `;

        document.getElementById('create-backup')?.addEventListener('click', () => {
            Utils.showToast('Creating backup...', 'info');
        });
    },

    renderActions() {
        const container = document.getElementById('instance-actions');
        if (!container) return;

        let actionsHtml = '<div class="actions-card"><h6>Actions</h6>';

        if (this.instance.state === 'running') {
            actionsHtml += `
                <a href="${this.instance.url}" target="_blank" class="action-btn action-primary">
                    <i class="fas fa-external-link-alt"></i>Open Instance
                </a>
                <button class="action-btn" data-action="restart">
                    <i class="fas fa-redo"></i>Restart
                </button>
                <button class="action-btn" data-action="stop">
                    <i class="fas fa-stop"></i>Stop
                </button>
            `;
        }

        if (this.instance.state === 'stopped') {
            actionsHtml += `
                <button class="action-btn action-primary" data-action="start">
                    <i class="fas fa-play"></i>Start
                </button>
            `;
        }

        if (this.instance.isTrial) {
            actionsHtml += `
                <a href="/upgrade.html?id=${this.instance.id}" class="action-btn">
                    <i class="fas fa-arrow-up"></i>Upgrade Plan
                </a>
            `;
        } else {
            actionsHtml += `
                <a href="/change-plan.html?id=${this.instance.id}" class="action-btn">
                    <i class="fas fa-exchange-alt"></i>Change Plan
                </a>
            `;
        }

        actionsHtml += '</div>';
        container.innerHTML = actionsHtml;

        // Setup action handlers
        container.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.currentTarget.dataset.action;
                this.handleAction(action);
            });
        });
    },

    renderPlanDetails() {
        const container = document.getElementById('plan-details');
        if (!container) return;

        const service = AppData.services.find(s => s.id === this.instance.serviceId);
        const plan = service?.plans.find(p => p.id === this.instance.planId);

        if (!plan) return;

        container.innerHTML = `
            <div class="info-card">
                <h6 class="text-muted text-uppercase small mb-3">Current Plan</h6>
                <h5 class="mb-3">${plan.name}</h5>
                
                <ul class="plan-specs mb-0">
                    <li><i class="fas fa-microchip"></i>${plan.cpu} vCPU</li>
                    <li><i class="fas fa-memory"></i>${Utils.formatStorage(plan.ram)} RAM</li>
                    <li><i class="fas fa-hdd"></i>${plan.storage} GB Storage</li>
                    <li><i class="fas fa-shield-alt"></i>${plan.backups} Backups</li>
                </ul>

                ${!this.instance.isTrial && this.instance.nextBilling ? `
                    <div class="mt-3 pt-3 border-top" style="border-color:var(--border-color)!important;">
                        <div class="text-muted small">Next billing date</div>
                        <div>${Utils.formatDate(this.instance.nextBilling)}</div>
                    </div>
                ` : ''}
            </div>
        `;
    },

    handleAction(action) {
        const actionNames = {
            restart: 'Restarting',
            stop: 'Stopping',
            start: 'Starting'
        };

        if (confirm(`Are you sure you want to ${action} this instance?`)) {
            Utils.showToast(`${actionNames[action]} instance...`, 'info');
            
            // Simulate action
            setTimeout(() => {
                if (action === 'stop') {
                    this.instance.state = 'stopped';
                    this.instance.cpuUsage = 0;
                    this.instance.ramUsage = 0;
                } else if (action === 'start') {
                    this.instance.state = 'running';
                    this.instance.cpuUsage = 15;
                    this.instance.ramUsage = Math.round(this.instance.ramLimit * 0.3);
                }
                
                Utils.showToast('Action completed successfully', 'success');
                this.renderPage();
            }, 1500);
        }
    },

    setupPolling() {
        if (['provisioning', 'pending_payment'].includes(this.instance.state)) {
            this.pollingInterval = setInterval(() => {
                // In real app, would fetch status from server
                console.log('Polling instance status...');
            }, 3000);

            // Stop after 10 minutes
            setTimeout(() => {
                if (this.pollingInterval) {
                    clearInterval(this.pollingInterval);
                }
            }, 600000);
        }
    }
};

// Checkout Page
const CheckoutPage = {
    init() {
        const params = Utils.getUrlParams();
        
        // Get service and plan info
        const serviceId = parseInt(params.service);
        const planId = parseInt(params.plan);
        const service = AppData.services.find(s => s.id === serviceId);
        const plan = service?.plans.find(p => p.id === planId);
        
        if (!service || !plan) {
            window.location.href = '/services.html';
            return;
        }

        this.renderCheckout(service, plan, params);
    },

    renderCheckout(service, plan, params) {
        const container = document.getElementById('checkout-content');
        if (!container) return;

        const billing = params.billing || 'monthly';
        const price = billing === 'monthly' ? plan.monthlyPrice : plan.yearlyPrice;

        container.innerHTML = `
            <div class="row g-4">
                <div class="col-lg-7">
                    <div class="info-card">
                        <h5>Order Summary</h5>
                        
                        <div class="d-flex align-items-center gap-3 mb-4">
                            <div class="service-icon" style="width:56px;height:56px;font-size:1.5rem;">
                                <i class="${service.icon}"></i>
                            </div>
                            <div>
                                <h5 class="mb-0">${service.name}</h5>
                                <span class="text-muted">${plan.name} Plan</span>
                            </div>
                        </div>

                        <table class="table table-dark-custom">
                            <tbody>
                                <tr>
                                    <td>Instance Domain</td>
                                    <td class="text-end">${params.subdomain}.${AppData.domains.find(d => d.id === parseInt(params.domain))?.name}</td>
                                </tr>
                                <tr>
                                    <td>Billing Period</td>
                                    <td class="text-end">${billing === 'monthly' ? 'Monthly' : 'Yearly'}</td>
                                </tr>
                                <tr>
                                    <td>CPU</td>
                                    <td class="text-end">${plan.cpu} vCPU</td>
                                </tr>
                                <tr>
                                    <td>RAM</td>
                                    <td class="text-end">${Utils.formatStorage(plan.ram)}</td>
                                </tr>
                                <tr>
                                    <td>Storage</td>
                                    <td class="text-end">${plan.storage} GB</td>
                                </tr>
                            </tbody>
                            <tfoot>
                                <tr>
                                    <td class="fw-bold fs-5">Total</td>
                                    <td class="text-end fw-bold fs-5">${Utils.formatCurrency(price)}${billing === 'monthly' ? '/mo' : '/yr'}</td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>

                <div class="col-lg-5">
                    <div class="info-card">
                        <h5>Payment Method</h5>
                        
                        <form id="payment-form">
                            <div class="mb-3">
                                <label class="form-label">Card Number</label>
                                <div class="input-icon">
                                    <i class="fas fa-credit-card"></i>
                                    <input type="text" class="form-control" placeholder="1234 5678 9012 3456" required>
                                </div>
                            </div>
                            
                            <div class="row g-3 mb-3">
                                <div class="col-6">
                                    <label class="form-label">Expiry</label>
                                    <input type="text" class="form-control" placeholder="MM/YY" required>
                                </div>
                                <div class="col-6">
                                    <label class="form-label">CVC</label>
                                    <input type="text" class="form-control" placeholder="123" required>
                                </div>
                            </div>

                            <div class="mb-4">
                                <label class="form-label">Cardholder Name</label>
                                <input type="text" class="form-control" placeholder="John Doe" required>
                            </div>

                            <button type="submit" class="btn btn-primary btn-lg w-100">
                                <i class="fas fa-lock me-2"></i>Pay ${Utils.formatCurrency(price)}
                            </button>

                            <div class="text-center mt-3">
                                <small class="text-muted">
                                    <i class="fas fa-shield-alt me-1"></i>
                                    Secured by SSL encryption
                                </small>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('payment-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            Utils.showToast('Processing payment...', 'info');
            setTimeout(() => {
                Utils.showToast('Payment successful!', 'success');
                setTimeout(() => {
                    window.location.href = '/my-instances.html';
                }, 1000);
            }, 2000);
        });
    }
};

// Upgrade/Change Plan Page
const ChangePlanPage = {
    instance: null,
    currentBilling: 'monthly',

    init() {
        const params = Utils.getUrlParams();
        const instanceId = parseInt(params.id);
        
        this.instance = AppData.instances.find(i => i.id === instanceId);
        
        if (!this.instance) {
            window.location.href = '/my-instances.html';
            return;
        }

        this.render();
    },

    render() {
        const container = document.getElementById('change-plan-content');
        if (!container) return;

        const service = AppData.services.find(s => s.id === this.instance.serviceId);
        const currentPlan = service?.plans.find(p => p.id === this.instance.planId);
        const availablePlans = service?.plans.filter(p => !p.isTrial && p.id !== this.instance.planId) || [];

        const isUpgrade = this.instance.isTrial;

        container.innerHTML = `
            <div class="page-header">
                <nav aria-label="breadcrumb">
                    <ol class="breadcrumb">
                        <li class="breadcrumb-item"><a href="/my-instances.html">My Instances</a></li>
                        <li class="breadcrumb-item"><a href="/instance-detail.html?id=${this.instance.id}">${this.instance.name}</a></li>
                        <li class="breadcrumb-item active">${isUpgrade ? 'Upgrade' : 'Change Plan'}</li>
                    </ol>
                </nav>
                <h1>${isUpgrade ? 'Upgrade Your Plan' : 'Change Plan'}</h1>
                <p>Currently on: <strong>${currentPlan?.name || 'Unknown'} Plan</strong></p>
            </div>

            <div class="text-center mb-4" id="billing-toggle">
                <div class="billing-toggle">
                    <button class="toggle-btn active" data-billing="monthly">Monthly</button>
                    <button class="toggle-btn" data-billing="yearly">Yearly <span class="yearly-badge">Save 20%</span></button>
                </div>
            </div>

            <div class="row g-4" id="plans-container">
                ${availablePlans.map(plan => {
                    const price = this.currentBilling === 'monthly' ? plan.monthlyPrice : Math.round(plan.yearlyPrice / 12);
                    const isUpgradePlan = !currentPlan || plan.monthlyPrice > (currentPlan.monthlyPrice || 0);

                    return `
                        <div class="col-md-6 col-lg-4">
                            <div class="plan-card ${plan.popular ? 'popular' : ''}">
                                ${plan.popular ? '<span class="plan-badge">Most Popular</span>' : ''}
                                <span class="badge ${isUpgradePlan ? 'bg-success' : 'bg-secondary'} mb-2">
                                    ${isUpgradePlan ? 'Upgrade' : 'Downgrade'}
                                </span>
                                <h4 class="plan-name">${plan.name}</h4>
                                <div class="plan-price">
                                    <span class="amount">${Utils.formatCurrency(price)}</span>
                                    <span class="period">/mo</span>
                                </div>
                                <ul class="plan-specs">
                                    <li><i class="fas fa-microchip"></i>${plan.cpu} vCPU</li>
                                    <li><i class="fas fa-memory"></i>${Utils.formatStorage(plan.ram)} RAM</li>
                                    <li><i class="fas fa-hdd"></i>${plan.storage} GB Storage</li>
                                    <li><i class="fas fa-shield-alt"></i>${plan.backups} Backups</li>
                                </ul>
                                <button class="btn ${isUpgradePlan ? 'btn-primary' : 'btn-outline-secondary'} w-100" 
                                        data-plan="${plan.id}">
                                    ${isUpgradePlan ? 'Upgrade Now' : 'Schedule Downgrade'}
                                </button>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>

            <div class="text-center mt-4">
                <a href="/instance-detail.html?id=${this.instance.id}" class="btn btn-outline-secondary">
                    <i class="fas fa-arrow-left me-2"></i>Back to Instance
                </a>
            </div>
        `;

        // Setup billing toggle
        container.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentBilling = btn.dataset.billing;
                this.render();
            });
        });

        // Setup plan buttons
        container.querySelectorAll('[data-plan]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const planId = parseInt(e.currentTarget.dataset.plan);
                Utils.showToast('Processing plan change...', 'info');
                setTimeout(() => {
                    window.location.href = `/checkout.html?service=${this.instance.serviceId}&plan=${planId}&billing=${this.currentBilling}`;
                }, 1000);
            });
        });
    }
};

// ============================================
// Page Router / Initializer
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;

    // Initialize based on current page
    if (path === '/services.html') {
        ServicesPage.init();
    } else if (path === '/service-plans.html') {
        PlansPage.init();
    } else if (path === '/configure.html') {
        ConfigurePage.init();
    } else if (path === '/register.html') {
        RegisterPage.init();
    } else if (path === '/my-instances.html') {
        InstancesPage.init();
    } else if (path === '/instance-detail.html') {
        InstanceDetailPage.init();
    } else if (path === '/checkout.html') {
        CheckoutPage.init();
    } else if (path === '/upgrade.html' || path === '/change-plan.html') {
        ChangePlanPage.init();
    }

    // Update nav active state
    document.querySelectorAll('.navbar-nav .nav-link').forEach(link => {
        if (link.getAttribute('href') === path) {
            link.classList.add('active');
        }
    });
});

// Add toast styles dynamically
const toastStyles = document.createElement('style');
toastStyles.textContent = `
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
    }
    .toast-success { border-color: var(--success); }
    .toast-success i { color: var(--success); }
    .toast-error { border-color: var(--danger); }
    .toast-error i { color: var(--danger); }
    .toast-info i { color: var(--info); }
    .fade-out { opacity: 0; transform: translateX(20px); transition: all 0.3s ease; }
`;
document.head.appendChild(toastStyles);

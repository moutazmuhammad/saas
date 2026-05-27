// Static content for the public /docs page. (Documentation articles are
// editorial content, not backend data — kept local on purpose.)

export interface DocFolder {
  id: string;
  title: string;
  description: string;
  articles: { id: string; title: string; readMinutes: number }[];
}

export const DOC_FOLDERS: DocFolder[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    description: "Provision your first instance and connect a domain.",
    articles: [
      { id: "quickstart", title: "Quickstart in 5 minutes", readMinutes: 5 },
      { id: "domains", title: "Connecting a custom domain", readMinutes: 7 },
      { id: "team", title: "Inviting your team", readMinutes: 3 },
    ],
  },
  {
    id: "instances",
    title: "Instances & Scaling",
    description: "Workers, storage, and zero-downtime scaling.",
    articles: [
      { id: "workers", title: "Understanding workers", readMinutes: 6 },
      { id: "scaling", title: "Scaling without downtime", readMinutes: 8 },
      { id: "regions", title: "Choosing a region", readMinutes: 4 },
    ],
  },
  {
    id: "databases",
    title: "Databases",
    description: "Create, clone, back up, and restore databases.",
    articles: [
      { id: "create-db", title: "Creating a database", readMinutes: 4 },
      { id: "restore", title: "Restoring from a backup", readMinutes: 6 },
      { id: "passwords", title: "Rotating database passwords", readMinutes: 3 },
    ],
  },
  {
    id: "billing",
    title: "Billing",
    description: "Invoices, billing cycles, and payment methods.",
    articles: [
      { id: "cycles", title: "Monthly vs yearly billing", readMinutes: 4 },
      { id: "invoices", title: "Reading your invoice", readMinutes: 3 },
    ],
  },
];

export type DatabaseGraphColumn = {
  name: string;
  type?: string | null;
  description?: string | null;
  isPrimaryKey: boolean;
  nullable?: boolean | null;
  validValues?: string[];
  reference?: {
    source?: string | null;
    column?: string | null;
  } | null;
};

export type DatabaseGraphMetric = {
  id: string;
  label: string;
  description?: string | null;
  aggregateExpression?: string | null;
  dateColumn?: string | null;
  currencyColumn?: string | null;
};

export type DatabaseGraphDimension = {
  id: string;
  label: string;
  column?: string | null;
  labelColumn?: string | null;
  key?: string | null;
};

export type DatabaseGraphDataProduct = {
  id: string;
  label: string;
  description?: string | null;
};

export type DatabaseGraphNode = {
  id: string;
  label: string;
  tableName: string;
  sourceRole: string;
  businessEntity?: string | null;
  grain?: string | null;
  primaryKey?: string | null;
  businessMeaning?: string | null;
  importantColumns: string[];
  keywords: string[];
  rowCount?: number | null;
  columns: DatabaseGraphColumn[];
  metrics: DatabaseGraphMetric[];
  dimensions: DatabaseGraphDimension[];
  dataProducts: DatabaseGraphDataProduct[];
};

export type DatabaseGraphEdge = {
  id: string;
  from: string;
  to: string;
  fromColumn: string | string[];
  toColumn: string | string[];
  relationshipType?: string | null;
  recommendedJoinType?: string | null;
  businessMeaning?: string | null;
  requiredFor: string[];
  warnings: string[];
  validation: Record<string, unknown>;
};

export type DatabaseGraphGroup = {
  id: string;
  label: string;
  nodeIds: string[];
};

export type DatabaseGraphResponse = {
  database: {
    name?: string | null;
    domain?: string | null;
    description?: string | null;
  };
  summary: {
    tableCount: number;
    relationshipCount: number;
    metricCount: number;
    dimensionCount: number;
    dataProductCount: number;
  };
  nodes: DatabaseGraphNode[];
  edges: DatabaseGraphEdge[];
  groups: DatabaseGraphGroup[];
  warnings: string[];
};

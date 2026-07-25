import { RiskConfig } from "./types";

export const config: RiskConfig = {
  policies: {
    latencyMs: 3000,
    tokenBudget: 25000,
    toolFailureThreshold: 1,
    repeatedToolThreshold: 3,
    retryThreshold: 3,
    warningThreshold: 1,
  },
};

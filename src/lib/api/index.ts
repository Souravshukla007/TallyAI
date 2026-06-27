import type { TallyAIApi } from "./client";
import { mockApi } from "./mock";
import { httpApi } from "./http-adapter";

/**
 * The single API instance the UI imports: `import { api } from "@/lib/api"`.
 *
 * Defaults to the mock implementation (in-memory demo fixtures). Set
 * `NEXT_PUBLIC_USE_MOCK=false` to target the real FastAPI backend via the HTTP
 * adapter; configure its base URL with `NEXT_PUBLIC_API_URL`.
 */
export const USE_MOCK = (process.env.NEXT_PUBLIC_USE_MOCK ?? "true") !== "false";

export const api: TallyAIApi = USE_MOCK ? mockApi : httpApi;

export type {
  TallyAIApi,
  AskRunHandle,
  RunEvent,
  RunEventHandlers,
  NewMetricInput,
} from "./client";

import { createEnv } from "@t3-oss/env-core";
import { z } from "zod";

export const env = createEnv({
  server: {},
  clientPrefix: "BUN_PUBLIC_",
  client: {
    BUN_PUBLIC_API_BASE_URL: z.url().default("http://localhost:8000"),
  },
  runtimeEnvStrict: {
    BUN_PUBLIC_API_BASE_URL: process.env.BUN_PUBLIC_API_BASE_URL,
  },
});

import { defineConfig } from "vite";

const env = {
    GALAXY_DATASET_ID: "",
    GALAXY_KEY: "",
    GALAXY_ROOT: "http://127.0.0.1:8080",
    // Names a built-in provider (galaxy | gemini | deepseek | local). Setting it is
    // enough; LLM_ROOT/LLM_PATH below are only for an endpoint the registry lacks.
    LLM_PROVIDER: "",
    LLM_ROOT: "",
    // Path the /llm proxy rewrites to; Gemini's shim is /v1beta/openai.
    LLM_PATH: "",
    // Provider key, kept in the environment because the manifest is committed.
    LLM_KEY: "",
    // Overrides <ai_model> for a dev run; empty means use the manifest.
    LLM_MODEL: "",
    // The context window that decides when the brain compacts; lower it for a small model.
    LLM_CONTEXT_WINDOW: "",
    // How much recent conversation compaction keeps; clamped to what the window holds.
    LLM_KEEP_RECENT_TOKENS: "",
};

type EnvKeyType = keyof typeof env;

Object.keys(env).forEach((key) => {
    if (process.env[key]) {
        env[key as EnvKeyType] = process.env[key] as string;
    } else {
        console.log(`${key} not available. Please provide as environment variable.`);
    }
});

const proxyGalaxy = () => ({
    changeOrigin: true,
    rewrite: (path: string) => {
        if (env.GALAXY_KEY) {
            const separator = path.includes("?") ? "&" : "?";
            return `${path}${separator}key=${env.GALAXY_KEY}`;
        }
        return path;
    },
    target: env.GALAXY_ROOT,
});

// The /llm proxy needs a concrete origin even when a provider supplies it.
const LLM_TARGETS: Record<string, { root: string; path: string }> = {
    gemini: { root: "https://generativelanguage.googleapis.com", path: "/v1beta/openai" },
    deepseek: { root: "https://api.deepseek.com", path: "/v1" },
    local: { root: "http://127.0.0.1:11434", path: "/v1" },
};
const llmTarget = LLM_TARGETS[env.LLM_PROVIDER] || { root: "http://127.0.0.1:11434", path: "/v1" };
const llmRoot = env.LLM_ROOT || llmTarget.root;
const llmPath = env.LLM_PATH || llmTarget.path;

// https://vitejs.dev/config/
export const viteConfigCharts = defineConfig({
    build: {
        outDir: "./static",
        emptyOutDir: true,
        rollupOptions: {
            output: {
                manualChunks: () => "app.js",
                entryFileNames: "[name].js",
                chunkFileNames: "[name].js",
                assetFileNames: "[name][extname]",
            },
        },
    },
    define: {
        "process.env.credentials": JSON.stringify(env.GALAXY_KEY ? "omit" : "include"),
        "process.env.dataset_id": JSON.stringify(env.GALAXY_DATASET_ID),
        "process.env.llm_provider": JSON.stringify(env.LLM_PROVIDER),
        "process.env.llm_model": JSON.stringify(env.LLM_MODEL),
        "process.env.llm_context_window": JSON.stringify(env.LLM_CONTEXT_WINDOW),
        "process.env.llm_keep_recent_tokens": JSON.stringify(env.LLM_KEEP_RECENT_TOKENS),
    },
    resolve: {
        alias: {
            "@": "/src",
        },
    },
    server: {
        proxy: {
            "/api": proxyGalaxy(),
            // Galaxy serves its OpenAPI spec here; the scoped catalog fetches it.
            "/openapi.json": proxyGalaxy(),
            // Dev LLM proxy; the key is attached here so it never reaches page JS.
            "/llm": {
                changeOrigin: true,
                target: llmRoot,
                rewrite: (path: string) => path.replace(/^\/llm/, llmPath),
                headers: env.LLM_KEY ? { Authorization: `Bearer ${env.LLM_KEY}` } : undefined,
            },
        },
    },
});

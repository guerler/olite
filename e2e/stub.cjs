// Stands in for the provider and Galaxy; scripted per scenario via /__script.
const http = require("http");

let script = "confirm";     // confirm | slow | compact
let calls = 0;
const seen = [];            // every Galaxy request the brain actually made
const prompts = [];         // what the brain sent us, so compaction can be checked

function json(res, code, body) {
    const text = JSON.stringify(body);
    res.writeHead(code, {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
    });
    res.end(text);
}

// A realistic `usage` is what lets the compaction scenario trigger.
const message = (content, tool_calls, promptTokens = 30000) => ({
    choices: [{ finish_reason: tool_calls ? "tool_calls" : "stop", message: { role: "assistant", content, tool_calls } }],
    usage: { prompt_tokens: promptTokens, completion_tokens: 20, total_tokens: promptTokens + 20 },
});

const deleteHistory = [{
    id: "call_1",
    type: "function",
    function: { name: "update_history", arguments: JSON.stringify({ history_id: "h1", deleted: true }) },
}];

const server = http.createServer(async (req, res) => {
    const url = req.url || "";
    if (req.method === "OPTIONS") return json(res, 204, {});

    if (url.startsWith("/__script")) {
        script = new URL(url, "http://x").searchParams.get("name") || "confirm";
        calls = 0;
        seen.length = 0;
        return json(res, 200, { script });
    }
    if (url.startsWith("/__seen")) return json(res, 200, { seen, calls, prompts });

    if (url.includes("/chat/completions")) {
        calls += 1;
        const body = await new Promise((resolve) => {
            let raw = "";
            req.on("data", (c) => (raw += c));
            req.on("end", () => {
                try {
                    resolve(JSON.parse(raw));
                } catch {
                    resolve({});
                }
            });
        });
        prompts.push({
            hasTools: Array.isArray(body.tools) && body.tools.length > 0,
            roles: (body.messages || []).map((m) => m.role),
            text: JSON.stringify(body.messages || []).slice(0, 4000),
        });
        // A summarization request is the one with no tools, whatever the scenario.
        const isSummarization = !prompts[prompts.length - 1].hasTools;
        if (isSummarization) {
            return json(res, 200, message("## Goal\nthe summarized goal"));
        }
        if (script === "slow") {
            // Long enough that Stop lands while the request is in flight.
            await new Promise((r) => setTimeout(r, 60000));
            return json(res, 200, message("too late"));
        }
        if (script === "compact") {
            return json(res, 200, message("ok"));
        }
        // Keyed on the last message; by turn two the transcript always has a tool result.
        const messages = body.messages || [];
        const last = messages[messages.length - 1] || {};
        return json(res, 200, last.role === "tool" ? message("Done.") : message("", deleteHistory));
    }

    // Everything else is Galaxy; record it so tests can assert on the PUT.
    seen.push(`${req.method} ${url}`);
    if (url.includes("/api/histories")) return json(res, 200, { id: "h1", name: "stub" });
    return json(res, 200, {});
});

server.listen(8099, () => console.log("stub on 8099"));

// Stands in for both the provider and Galaxy, so the destructive-op gate can be
const http = require("http");

let script = "confirm";     // confirm | slow
let calls = 0;
const seen = [];            // every Galaxy request the brain actually made

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

const message = (content, tool_calls) => ({
    choices: [{ finish_reason: tool_calls ? "tool_calls" : "stop", message: { role: "assistant", content, tool_calls } }],
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
    if (url.startsWith("/__seen")) return json(res, 200, { seen, calls });

    if (url.includes("/chat/completions")) {
        calls += 1;
        if (script === "slow") {
            // Long enough that Stop lands while the request is in flight.
            await new Promise((r) => setTimeout(r, 60000));
            return json(res, 200, message("too late"));
        }
        // First turn asks to delete; after the tool result comes back, say something.
        return json(res, 200, calls === 1 ? message("", deleteHistory) : message("Done."));
    }

    // Everything else is Galaxy. Record it — the assertion is whether the PUT
    seen.push(`${req.method} ${url}`);
    if (url.includes("/api/histories")) return json(res, 200, { id: "h1", name: "stub" });
    return json(res, 200, {});
});

server.listen(8099, () => console.log("stub on 8099"));

/** olite shell — a lean vanilla-TS compositor (the olite counterpart of Orbit's app.ts). */
import "./orbit/styles.css";
import { ChatPanel } from "./orbit/chat/chat-panel";
import { applyOrbitTheme } from "./orbit/theme";
import { parseIncoming } from "./incoming";
import { PyodideManager } from "./pyodide/pyodide-manager";
import { runOlite } from "./pyodide-runner";
import { renderArtifact } from "./artifacts";

const PLUGIN_NAME = "olite";
const PROMPT_DEFAULT = "You are olite. Communicate only by calling tools.";

async function main() {
    const scriptUrl = new URL(import.meta.url);
    const containerId = scriptUrl.searchParams.get("container") || "app";

    // Dev-only: synthesize data-incoming from the plugin XML (no framework host).
    if ((import.meta as any).env.DEV) {
        const { parseXML } = await import("galaxy-charts-xml-parser");
        const pageUrl = new URL(window.location.href);
        const dataIncoming = {
            root: "/",
            visualization_config: {
                dataset_id: pageUrl.searchParams.get("dataset_id") || "__test__",
                settings: {},
            },
            visualization_plugin: await parseXML("olite.xml"),
        };
        document.getElementById(containerId)!.dataset.incoming = JSON.stringify(dataIncoming);
    }

    const container = document.getElementById(containerId)!;
    const incoming = parseIncoming(container);
    applyOrbitTheme("dark", document.documentElement);

    // Build Orbit's chat-pane structure so the vendored styles.css applies as-is.
    container.innerHTML = `
      <div id="app-main">
        <div id="chat-pane" class="pane">
          <div id="messages"></div>
          <div id="input-area">
            <div class="composer-row">
              <textarea id="input" rows="1" aria-label="Chat input"
                placeholder="Ask olite to run something..."></textarea>
              <button id="send-btn" title="Send" aria-label="Send message">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
          <div id="input-hint"><span>Enter to send</span></div>
        </div>
        <div id="divider"></div>
        <div id="artifact-pane" class="pane">
          <div id="artifact-content"></div>
        </div>
      </div>`;

    // Start with the artifact pane collapsed; it reveals when a tool produces one.
    document.body.classList.add("artifact-collapsed");

    const chat = new ChatPanel(container.querySelector<HTMLElement>("#messages")!);
    const input = container.querySelector<HTMLTextAreaElement>("#input")!;
    const sendBtn = container.querySelector<HTMLButtonElement>("#send-btn")!;
    const artifactContent = container.querySelector<HTMLElement>("#artifact-content")!;

    const config = buildConfig(incoming);
    // Runtime context: reveals whether relative fetches resolve against this page or
    console.log("[olite] context", {
        href: window.location.href,
        origin: window.location.origin,
        isIframe: window.top !== window.self,
        galaxy_root: config.galaxy_root,
        openapi_url: `${config.galaxy_root}openapi.json`,
    });
    const convo: Array<{ role: string; content: string }> = [
        { role: "system", content: incoming.specs.ai_prompt || PROMPT_DEFAULT },
    ];

    // Boot Pyodide (brain lives inside it).
    const isDev = (import.meta as any).env.DEV;
    const base = isDev ? "" : `static/plugins/visualizations/${PLUGIN_NAME}/`;
    const indexURL = `${incoming.root}${base}static/pyodide`;
    const pyodide = new PyodideManager({
        indexURL,
        extraPackages: [`${indexURL}/olite-0.0.0-py3-none-any.whl`],
    });
    let ready = false;
    const readyInfo = chat.addInfoMessage("Loading olite...");
    pyodide
        .initialize()
        .then(() => {
            ready = true;
            readyInfo.textContent = "olite ready. Ask me to run something.";
        })
        .catch((e) => chat.addErrorMessage(`Failed to load olite: ${e}`));

    let busy = false;
    async function submit() {
        const text = input.value.trim();
        if (!text || busy || !ready) {
            return;
        }
        busy = true;
        input.value = "";
        chat.addUserMessage(text);
        chat.showThinking();
        convo.push({ role: "user", content: text });
        const sent = convo.length;
        try {
            console.groupCollapsed("[olite] turn");
            console.log("request", { galaxy_root: config.galaxy_root, capabilities: config.capabilities, text });
            const reply = await runOlite(pyodide, config, convo);
            console.log("diagnostics", reply.diagnostics);
            console.log("trace", reply.logs);
            console.log("messages", reply.messages);
            console.groupEnd();
            // Surface a broken Galaxy catalog once, prominently: an empty galaxy_ops is
            const cat = reply.diagnostics && reply.diagnostics.catalog;
            if (cat && !cat.loaded) {
                chat.addErrorMessage(`Galaxy catalog did not load (root=${config.galaxy_root}): ${cat.error}`);
            }
            chat.hideThinking();
            renderMessages(chat, (reply.messages || []).slice(sent));
            convo.length = 0;
            convo.push(...trimConvo(reply.messages || []));
            const artifacts = reply.artifacts || [];
            if (artifacts.length) {
                document.body.classList.remove("artifact-collapsed");
                artifactContent.innerHTML = "";
                for (const a of artifacts) {
                    await renderArtifact(artifactContent, a);
                }
            }
        } catch (e) {
            chat.hideThinking();
            chat.addErrorMessage(String(e));
        }
        busy = false;
    }

    sendBtn.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void submit();
        }
    });
}

// Keep the system prompt plus the most recent turns so the context stays within
const MAX_MESSAGES = 16;

function trimConvo(messages: any[]): any[] {
    if (messages.length <= MAX_MESSAGES + 1) {
        return messages;
    }
    let cut = messages.length - MAX_MESSAGES;
    while (cut < messages.length && messages[cut].role !== "user") {
        cut++;
    }
    return [messages[0], ...messages.slice(cut)];
}

function buildConfig(incoming: ReturnType<typeof parseIncoming>) {
    const s = incoming.specs;
    return {
        ai_base_url: s.ai_api_base_url || `${incoming.root}api/plugins/${PLUGIN_NAME}`,
        ai_api_key: s.ai_api_key,
        ai_model: s.ai_model,
        galaxy_root: incoming.root,
        galaxy_key: s.galaxy_api_key,
        // Demo grants write so the kill-gate can submit jobs; real deployments gate
        capabilities: ["llm", "local", "read", "write"],
    };
}

/** Render the loop's new messages into ChatPanel: assistant text + tool cards. */
function renderMessages(chat: ChatPanel, messages: any[]) {
    for (const m of messages) {
        if (m.role === "assistant") {
            if (m.content) {
                chat.startAssistantMessage();
                chat.appendDelta(m.content);
                chat.finishAssistantMessage();
            }
            for (const tc of m.tool_calls || []) {
                chat.addToolCard(tc.id, tc.function?.name || "tool");
            }
        } else if (m.role === "tool") {
            chat.updateToolCard(m.tool_call_id, toolStatus(m.content), m.content);
        }
    }
}

function toolStatus(content: string): "done" | "error" {
    try {
        const parsed = JSON.parse(content);
        if (parsed && parsed.ok === false) {
            return "error";
        }
    } catch {
        // non-JSON tool output (e.g. run_python) is a success
    }
    return "done";
}

void main();

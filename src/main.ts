/** olite shell: mounts Orbit's ChatPanel, boots the Pyodide brain, drives the chat. */
import "./orbit/styles.css";
import { ChatPanel } from "./orbit/chat/chat-panel";
import { applyOrbitTheme } from "./orbit/theme";
import { parseIncoming } from "./incoming";
import { PyodideManager } from "./pyodide/pyodide-manager";
import { runOlite } from "./pyodide-runner";
import { renderArtifact } from "./artifacts";
import { InvocationWatcher, galaxyStateReader, isFailure } from "./invocations";

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

    // Orbit's layout chain, so the vendored styles.css applies as-is.
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
              <!-- Orbit's abort button; the vendored styles.css already has #abort-btn. -->
              <button id="abort-btn" title="Stop (Esc)" class="hidden" aria-label="Stop the current response">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
                <span>Stop</span>
              </button>
            </div>
          </div>
          <div id="input-hint"><span>Enter to send</span></div>
        </div>
        <div id="divider"></div>
        <div id="artifact-pane" class="pane">
          <div id="artifact-content"></div>
        </div>
      </div>
      <!-- Orbit's request modal, reduced to the confirm variant. -->
      <div id="ext-overlay" class="modal-overlay hidden">
        <div class="modal">
          <div class="modal-header"><h2 id="ext-title">Request</h2></div>
          <div class="modal-body"><div id="ext-message" class="ext-message"></div></div>
          <div class="modal-footer">
            <div class="modal-actions">
              <button id="ext-deny" class="plan-btn">No</button>
              <button id="ext-accept" class="plan-btn primary">Yes</button>
            </div>
          </div>
        </div>
      </div>`;

    // Start with the artifact pane collapsed; it reveals when a tool produces one.
    document.body.classList.add("artifact-collapsed");

    const messagesEl = container.querySelector<HTMLElement>("#messages")!;
    const chat = new ChatPanel(messagesEl);
    const input = container.querySelector<HTMLTextAreaElement>("#input")!;
    const sendBtn = container.querySelector<HTMLButtonElement>("#send-btn")!;
    const abortBtn = container.querySelector<HTMLButtonElement>("#abort-btn")!;
    const artifactContent = container.querySelector<HTMLElement>("#artifact-content")!;
    const extOverlay = container.querySelector<HTMLElement>("#ext-overlay")!;
    const extTitle = container.querySelector<HTMLElement>("#ext-title")!;
    const extMessage = container.querySelector<HTMLElement>("#ext-message")!;
    const extAccept = container.querySelector<HTMLButtonElement>("#ext-accept")!;
    const extDeny = container.querySelector<HTMLButtonElement>("#ext-deny")!;

    const config = buildConfig(incoming);
    // Runtime context: where relative fetches resolve and what origin Galaxy calls hit.
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

    // Advances submitted Galaxy work between turns, so no turn blocks on a job.
    const watcher = new InvocationWatcher({
        readState: galaxyStateReader(config.galaxy_root, (process.env.credentials as RequestCredentials) || "include"),
        onSettled: (w, state) => {
            const what = w.kind === "invocation" ? "Workflow invocation" : "Galaxy job";
            if (isFailure(w.kind, state)) {
                chat.addErrorMessage(`${what} ${w.id} finished as ${state}.`);
            } else {
                chat.addInfoMessage(`${what} ${w.id} finished (${state}). Ask me to check the results.`);
            }
        },
    });

    let busy = false;
    async function submit() {
        const text = input.value.trim();
        if (!text || busy || !ready) {
            return;
        }
        busy = true;
        input.value = "";
        // Stop replaces Send for the duration of the turn, as in Orbit.
        sendBtn.classList.add("hidden");
        abortBtn.classList.remove("hidden");
        chat.addUserMessage(text);
        chat.showThinking();
        convo.push({ role: "user", content: text });
        // Cards rendered live from loop events; the final reconcile skips these ids.
        const streamed = new Set<string>();
        const onEvent = (ev: any) => {
            if (ev.type === "tool_start") {
                streamed.add(ev.id);
                chat.hideThinking();
                chat.addToolCard(ev.id, ev.name || "tool");
            } else if (ev.type === "compacted") {
                // Never let history disappear without saying so.
                chat.addInfoMessage("Summarized the earlier conversation to make room.");
            } else if (ev.type === "context_overflow") {
                // Compaction was needed and could not help; say so before the provider does.
                chat.addErrorMessage(
                    "This conversation no longer fits in the model's context window, and summarizing " +
                        "cannot free enough room. Start a new conversation, or configure a larger window.",
                );
            } else if (ev.type === "tool_end") {
                // The brain states the outcome; toolStatus only guesses at it.
                const status = ev.is_error ? "error" : toolStatus(ev.content || "");
                chat.updateToolCard(ev.id, status, ev.content || "");
                // Galaxy returns the ids, so the model never has to register them.
                watcher.ingest(ev.name || "", ev.content || "");
            }
        };
        try {
            console.groupCollapsed("[olite] turn");
            console.log("request", { galaxy_root: config.galaxy_root, capabilities: config.capabilities, text });
            const reply = await runOlite(pyodide, config, convo, onEvent);
            console.log("diagnostics", reply.diagnostics);
            console.log("trace", reply.logs);
            console.log("messages", reply.messages);
            console.groupEnd();
            // Surface a broken Galaxy catalog once; it is otherwise a silent dead end.
            const cat = reply.diagnostics && reply.diagnostics.catalog;
            if (cat && !cat.loaded) {
                chat.addErrorMessage(`Galaxy catalog did not load (root=${config.galaxy_root}): ${cat.error}`);
            }
            chat.hideThinking();
            // The brain names this turn's messages; compaction moves them, so no slicing.
            const spoke = renderMessages(chat, reply.new_messages || [], streamed);
            // Exactly one explanation for a quiet turn, most specific first.
            if (reply.aborted) {
                chat.addInfoMessage("Stopped.");
            } else if (reply.exhausted) {
                // Orbit has no step cap; olite's must not look like completion.
                chat.addInfoMessage("I ran out of steps for one turn while still working. Say \"continue\" to pick it up.");
            } else if (!spoke && !reply.done) {
                // A reply with no tool calls ends the loop, even with no text either.
                // `done` means the model called finish, whose summary is its reply.
                chat.addInfoMessage("The model ended the turn without a reply. Ask again, or rephrase.");
            }
            convo.length = 0;
            convo.push(...(reply.messages || []));
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
        abortBtn.classList.add("hidden");
        sendBtn.classList.remove("hidden");
        busy = false;
    }

    function abortCurrentTurn() {
        if (busy) {
            pyodide.abort();
        }
    }

    // The brain has parked a turn on a yes/no; follows Orbit's openExtConfirm.
    function showConfirm(confirmId: string, request: any) {
        extTitle.textContent = request?.title || "Confirm";
        extMessage.textContent = request?.message || "";
        extOverlay.classList.remove("hidden");

        const respond = (approved: boolean) => {
            extOverlay.classList.add("hidden");
            extAccept.removeEventListener("click", onYes);
            extDeny.removeEventListener("click", onNo);
            container.removeEventListener("keydown", onKey, true);
            pyodide.respondToConfirm(confirmId, approved);
            chat.addInfoMessage(approved ? `Approved: ${request?.message || ""}` : "Declined.");
        };
        const onYes = () => respond(true);
        const onNo = () => respond(false);
        const onKey = (e: Event) => {
            const key = (e as KeyboardEvent).key;
            if (key === "Escape") {
                // Stopped here so Escape answers the modal and not the Stop handler.
                e.preventDefault();
                e.stopPropagation();
                respond(false);
            }
        };
        extAccept.addEventListener("click", onYes);
        extDeny.addEventListener("click", onNo);
        container.addEventListener("keydown", onKey, true);
        extAccept.focus();
    }

    pyodide.onConfirm = showConfirm;

    sendBtn.addEventListener("click", submit);
    abortBtn.addEventListener("click", abortCurrentTurn);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void submit();
        }
    });
    // Esc stops the turn; bound on the container because olite lives in an iframe.
    container.addEventListener("keydown", (e) => {
        if ((e as KeyboardEvent).key === "Escape" && busy) {
            abortCurrentTurn();
        }
    });

    // Approve / Edit / Reject on a plan draft card; wording follows loom's handler.
    messagesEl.addEventListener("plan-draft-action", (e) => {
        const { action, body } = (e as CustomEvent<{ action: string; body: string }>).detail;
        if (action === "approve") {
            input.value = "I approve the plan above. Show the full parameter table for review before executing.";
            void submit();
        } else if (action === "reject") {
            input.value = "Reject the plan above — let's rethink it.";
            void submit();
        } else if (action === "edit") {
            // Edit hands the draft back for the user to change; it does not submit.
            input.value = "Here is the plan with my edits — please revise your draft accordingly:\n\n```plan\n" + body + "\n```";
            input.focus();
        }
    });
}

// No window here: the brain compacts, and trimming on top would delete the summary.

function buildConfig(incoming: ReturnType<typeof parseIncoming>) {
    const s = incoming.specs;
    return {
        ai_base_url: s.ai_api_base_url || `${incoming.root}api/plugins/${PLUGIN_NAME}`,
        ai_api_key: s.ai_api_key,
        // Dev only: switch provider by env instead of editing a committed file.
        ai_model: (process.env.llm_model as string) || s.ai_model,
        // When the brain compacts; configuration, since there is no model registry.
        ai_context_window: Number(process.env.llm_context_window) || undefined,
        ai_keep_recent_tokens: Number(process.env.llm_keep_recent_tokens) || undefined,
        galaxy_root: incoming.root,
        galaxy_key: s.galaxy_api_key,
        // Demo grants write; real deployments gate it via the install/trust tier.
        capabilities: ["llm", "local", "read", "write"],
    };
}

/** Render the turn's messages; returns whether any assistant prose was shown. */
function renderMessages(chat: ChatPanel, messages: any[], streamed: Set<string> = new Set()): boolean {
    let spoke = false;
    for (const m of messages) {
        // `finish` carries the model's closing words in a tool argument rather than in
        // content, so render its summary as the reply or the turn ends showing nothing.
        if (m.role === "tool" && m.name === "finish" && m.content) {
            spoke = true;
            chat.startAssistantMessage();
            chat.appendDelta(m.content);
            chat.finishAssistantMessage();
            continue;
        }
        if (m.role === "assistant") {
            if (m.content) {
                spoke = true;
                chat.startAssistantMessage();
                chat.appendDelta(m.content);
                chat.finishAssistantMessage();
            }
            for (const tc of m.tool_calls || []) {
                if (!streamed.has(tc.id)) {
                    chat.addToolCard(tc.id, tc.function?.name || "tool");
                }
            }
        } else if (m.role === "tool") {
            if (!streamed.has(m.tool_call_id)) {
                chat.updateToolCard(m.tool_call_id, toolStatus(m.content), m.content);
            }
        }
    }
    return spoke;
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

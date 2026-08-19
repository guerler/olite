// The live path nothing else covers: a real workflow invoked on a real Galaxy, through the
// four-stage gate, with the record written to a Galaxy Page. Needs a real model and key.
const { chromium } = require("playwright");

const OUT = process.env.OUT || "/tmp";
const APP = process.env.APP_URL || "http://localhost:5173/";
const GALAXY = process.env.GALAXY_ROOT || "http://127.0.0.1:8080";
const KEY = process.env.GALAXY_KEY;
const HISTORY = process.env.HISTORY_ID;
const WORKFLOW = process.env.WORKFLOW_ID;
const DATASET = process.env.DATASET_ID;

let failed = 0;
const check = (name, ok, detail) => {
    if (!ok) failed += 1;
    console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};
const api = async (path) => {
    const sep = path.includes("?") ? "&" : "?";
    const r = await fetch(`${GALAXY}/${path}${sep}key=${KEY}`);
    return r.ok ? r.json() : null;
};

(async () => {
    for (const [k, v] of Object.entries({ KEY, HISTORY, WORKFLOW, DATASET })) {
        if (!v) { console.log(`FAIL  missing env ${k}`); process.exit(1); }
    }
    const invocationsBefore = (await api(`api/invocations?workflow_id=${WORKFLOW}`)) || [];

    const browser = await chromium.launch();
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
    const wait = async (fn, ms, arg) => {
        const end = Date.now() + ms;
        while (Date.now() < end) {
            if (await page.evaluate(fn, arg)) return true;
            await page.waitForTimeout(1000);
        }
        return false;
    };
    const idle = () => wait(() => !document.querySelector("#send-btn").classList.contains("hidden"), 600000);
    const say = async (text) => {
        await page.fill("#input", text);
        await page.click("#send-btn");
        return idle();
    };

    await page.goto(`${APP}?history_id=${HISTORY}`, { waitUntil: "domcontentloaded" });
    check("booted", await wait(() => /olite ready|Resumed this history/i.test(document.body.innerText), 300000));

    // Stage 1-2: ask for a plan, expect a draft card rather than execution.
    const asked = await say(
        `Invoke the workflow with id ${WORKFLOW} on dataset ${DATASET} in this history. ` +
        `Draft a plan first and wait for my approval.`);
    check("first turn completed", asked);

    const hasCard = await wait(() => !!document.querySelector(".plan-draft-approve"), 60000);
    check("plan draft card offered", hasCard);

    const invocationsMid = (await api(`api/invocations?workflow_id=${WORKFLOW}`)) || [];
    check("gate held before approval", invocationsMid.length === invocationsBefore.length,
          `${invocationsBefore.length} -> ${invocationsMid.length} invocations`);

    if (hasCard) {
        await page.click(".plan-draft-approve");
        check("plan approved, turn ran", await idle());
    }

    // Stage 3-4: parameters are reviewed in chat, then approved in words.
    check("parameters approved, turn ran", await say("The parameters look right. Go ahead and invoke it."));

    // The watcher advances the invocation between turns; give it room.
    const invoked = await (async () => {
        const end = Date.now() + 300000;
        while (Date.now() < end) {
            const now = (await api(`api/invocations?workflow_id=${WORKFLOW}`)) || [];
            if (now.length > invocationsBefore.length) return now[0];
            await page.waitForTimeout(5000);
        }
        return null;
    })();
    check("workflow was invoked", !!invoked, invoked ? `invocation ${invoked.id}` : "no new invocation");

    if (invoked) {
        const settled = await (async () => {
            const end = Date.now() + 420000;
            while (Date.now() < end) {
                const d = await api(`api/invocations/${invoked.id}`);
                if (d && ["scheduled", "cancelled", "failed"].includes(d.state)) return d.state;
                await page.waitForTimeout(5000);
            }
            return null;
        })();
        check("invocation reached a terminal state", !!settled, settled || "still pending");
        check("watcher reported it in chat",
              await wait(() => /invocation .* finished|Workflow invocation/i.test(document.body.innerText), 240000));
    }

    // The agent may invoke into a history other than the bound one, so check both: the
    // bound history's record must carry the shell-written session block, and whichever
    // record the agent wrote must describe the work.
    const pages = (await api("api/pages?limit=500")) || [];
    const read = async (p) => ((await api(`api/pages/${p.id}`)) || {}).content || "";

    const bound = pages.find((p) => p.slug === `olite-${HISTORY}`);
    check("bound history has a record", !!bound, bound ? bound.id : `no olite-${HISTORY}`);
    if (bound) {
        const content = await read(bound);
        check("shell wrote the session block", content.includes("```olite-session"),
              `${content.length} chars`);
        require("fs").writeFileSync(`${OUT}/live-record-bound.md`, content);
    }

    const olitePages = pages.filter((p) => (p.slug || "").startsWith("olite-"));
    let narrated = null;
    for (const p of olitePages) {
        const c = await read(p);
        if (/invocation|workflow/i.test(c) && c.length > 200) narrated = { page: p, content: c };
    }
    check("some record describes the work", !!narrated,
          narrated ? `${narrated.page.slug} (${narrated.content.length} chars)` : "none did");
    if (narrated) require("fs").writeFileSync(`${OUT}/live-record.md`, narrated.content);

    check("the work stayed in the bound history",
          !!(narrated && narrated.page.slug === `olite-${HISTORY}`),
          narrated ? `wrote to ${narrated.page.slug}` : "n/a");

    await page.screenshot({ path: `${OUT}/live-workflow.png`, fullPage: true });
    console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
    await browser.close();
    process.exit(failed ? 1 : 0);
})();

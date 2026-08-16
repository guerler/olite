// Drives the destructive-op gate and Stop through the real page: real worker, real
const { chromium } = require("playwright");
const OUT = process.env.OUT || "/tmp";
const APP = process.env.APP_URL || "http://localhost:5173/";
const STUB = "http://127.0.0.1:8099";

const results = [];
function check(name, ok, detail) {
    results.push({ name, ok, detail });
    console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

async function waitFor(page, fn, ms, arg) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
        if (await page.evaluate(fn, arg)) return true;
        await page.waitForTimeout(500);
    }
    return false;
}

const modalOpen = () => {
    const el = document.querySelector("#ext-overlay");
    return !!el && !el.classList.contains("hidden");
};
const text = (page) => page.evaluate(() => document.body.innerText);

async function script(name) {
    await fetch(`${STUB}/__script?name=${name}`);
}
async function seen() {
    return (await (await fetch(`${STUB}/__seen`)).json()).seen;
}

async function ask(page, msg) {
    await page.fill("#input", msg);
    await page.click("#send-btn");
}

(async () => {
    const b = await chromium.launch();
    const p = await b.newPage({ viewport: { width: 1100, height: 900 } });
    const logs = [];
    p.on("console", (m) => logs.push(`[${m.type()}] ${m.text()}`));
    p.on("pageerror", (e) => logs.push(`[pageerror] ${e.message}`));

    await p.goto(APP, { waitUntil: "domcontentloaded" });
    const ready = await waitFor(p, () => /olite ready/i.test(document.body.innerText), 240000);
    check("page loads and the brain reports ready", ready);
    if (!ready) {
        console.log(logs.slice(-25).join("\n"));
        await b.close();
        process.exit(1);
    }

    // ---- 1. a destructive op asks, and declining stops it ---------------------
    await script("confirm");
    await ask(p, "delete my history");
    const asked = await waitFor(p, modalOpen, 90000);
    check("a destructive op opens the confirmation modal", asked);
    await p.screenshot({ path: `${OUT}/c1-modal.png` });

    if (asked) {
        const headline = await p.evaluate(() => document.querySelector("#ext-message").textContent);
        check(
            "the modal states the scope honestly",
            /entire history/i.test(headline) && /Recoverable/i.test(headline),
            headline.slice(0, 90),
        );
        await p.click("#ext-deny");
        await waitFor(p, () => document.querySelector("#ext-overlay").classList.contains("hidden"), 10000);
        await waitFor(p, () => !document.querySelector(".thinking-indicator"), 60000);
        const puts = (await seen()).filter((s) => s.startsWith("PUT"));
        check("declining sends nothing to Galaxy", puts.length === 0, JSON.stringify(puts));
        check("the decline is visible in chat", /Declined/i.test(await text(p)));
        const cardClass = await p.evaluate(() => {
            const cards = [...document.querySelectorAll("[class*='tool']")];
            return cards.map((c) => c.className).join(" | ");
        });
        check(
            "the refused call does not render as a successful card",
            !/done|success|ok\b/i.test(cardClass) || /error|fail/i.test(cardClass),
            cardClass.slice(0, 120),
        );
    }

    // ---- 2. approving lets it through ---------------------------------------
    await script("confirm");
    await ask(p, "delete my history");
    const asked2 = await waitFor(p, modalOpen, 90000);
    check("it asks again rather than remembering the earlier answer", asked2);
    if (asked2) {
        await p.click("#ext-accept");
        await waitFor(p, () => document.querySelector("#ext-overlay").classList.contains("hidden"), 10000);
        await waitFor(p, () => !document.querySelector(".thinking-indicator"), 90000);
        const puts = (await seen()).filter((s) => s.startsWith("PUT"));
        check("approving lets the request through to Galaxy", puts.length === 1, JSON.stringify(puts));
        await p.screenshot({ path: `${OUT}/c2-approved.png` });
    }

    // ---- 3. Stop ends a turn parked on a slow provider -----------------------
    await script("slow");
    await ask(p, "do something slow");
    await p.waitForTimeout(3000);
    const stopVisible = await p.evaluate(
        () => !document.querySelector("#abort-btn").classList.contains("hidden"),
    );
    check("Stop replaces Send while a turn is in flight", stopVisible);
    await p.click("#abort-btn");
    const stopped = await waitFor(p, () => /Stopped\./.test(document.body.innerText), 30000);
    check("Stop ends the turn without waiting for the provider", stopped);
    const backToSend = await p.evaluate(
        () => !document.querySelector("#send-btn").classList.contains("hidden"),
    );
    check("Send comes back after the stop", backToSend);
    check(
        "a stopped turn is not also reported as an empty reply",
        !/ended the turn without a reply/i.test(await text(p)),
    );
    await p.screenshot({ path: `${OUT}/c3-stopped.png` });

    console.log("\n" + logs.filter((l) => /error|Error|refus|destructive/.test(l)).slice(-12).join("\n"));
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
    await b.close();
    process.exit(failed.length ? 1 : 0);
})();

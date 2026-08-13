function toDict(payload: any) {
    return `json.loads(${JSON.stringify(JSON.stringify(payload))})`;
}

export async function runOlite(pyodide: any, config: any, transcripts: any) {
    const inputs = { transcripts };
    const raw = await pyodide.runPythonAsync([
        "import json",
        "from olite import run",
        `config = ${toDict(config)}`,
        `inputs = ${toDict(inputs)}`,
        "result = await run(config, inputs)",
        "json.dumps(result)",
    ]);
    if (typeof raw !== "string") {
        throw new Error("Did not return JSON.");
    }
    return JSON.parse(raw);
}

import { describe, expect, it } from "vitest";
import { applyJobOutcome } from "./record-jobs";

const RECORD = `## Record

### Plan A: Filter and sort [galaxy]

- [ ] 1. **Filter rows** where column 3 > 500 using **Filter1**
  - Input dataset: \`40876639881ca029\` (1.tabular)
  - Output dataset: \`d071e794759ab192\` (Filter on dataset 1)
- [ ] 2. **Sort rows** by column 2 descending using **Sort**
  - Output dataset: \`8c49be448cfe29bc\` (Sort on dataset 2)

*Submitted jobs are currently running.*
`;

const ok = (id: string) => ({ id, kind: "job" as const, state: "ok", failed: false });

describe("applyJobOutcome", () => {
    it("flips the step carrying the id and records the state", () => {
        const out = applyJobOutcome(RECORD, ok("d071e794759ab192"));
        expect(out).toContain("- [x] 1. **Filter rows**");
        expect(out).toContain("Status: finished (ok)");
        // The other step is untouched.
        expect(out).toContain("- [ ] 2. **Sort rows**");
    });

    it("is idempotent — the poller may see the same terminal state repeatedly", () => {
        const once = applyJobOutcome(RECORD, ok("d071e794759ab192"));
        expect(applyJobOutcome(once, ok("d071e794759ab192"))).toBe(once);
    });

    it("leaves the record alone when the id is not mentioned", () => {
        expect(applyJobOutcome(RECORD, ok("ffffffffffffffff"))).toBe(RECORD);
    });

    it("closes out the running line only when nothing is left pending", () => {
        const one = applyJobOutcome(RECORD, ok("d071e794759ab192"));
        expect(one).toContain("*Submitted jobs are currently running.*");
        const both = applyJobOutcome(one, ok("8c49be448cfe29bc"));
        expect(both).toContain("*All submitted jobs have finished.*");
        expect(both).not.toContain("currently running");
    });

    it("does not tick a failed step, but does record why", () => {
        const out = applyJobOutcome(RECORD, {
            id: "d071e794759ab192", kind: "job", state: "error", failed: true,
        });
        expect(out).toContain("- [ ] 1. **Filter rows**");
        expect(out).toContain("Status: failed (error)");
    });

    it("does nothing to an empty record", () => {
        expect(applyJobOutcome("", ok("d071e794759ab192"))).toBe("");
    });
});

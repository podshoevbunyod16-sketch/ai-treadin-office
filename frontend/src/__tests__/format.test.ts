import { describe, expect, it } from "vitest";
import { fmtDuration, fmtPrice, fmtServerTime, pnlClass, signalLabel } from "../format";

describe("format", () => {
  it("formats prices and durations", () => {
    expect(fmtPrice(1.123456, 5)).toBe("1.12346");
    expect(fmtPrice(0)).toBe("—");
    expect(fmtDuration(59)).toBe("59с");
    expect(fmtDuration(3725)).toBe("1ч 2м");
    expect(fmtDuration(90061)).toBe("1д 1ч 1м");
  });
  it("formats server time and pnl", () => {
    expect(fmtServerTime(0)).toBe("—");
    expect(fmtServerTime(1700000000)).toBe("2023-11-14 22:13:20");
    expect(pnlClass(5)).toBe("pos");
    expect(pnlClass(-1)).toBe("neg");
    expect(signalLabel(1)).toBe("ЛОНГ");
    expect(signalLabel(null)).toBe("—");
  });
});

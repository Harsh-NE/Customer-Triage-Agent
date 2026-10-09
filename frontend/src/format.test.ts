import { fmtAge, fmtDuration, fmtMoney, fmtPct, fmtTokens, reasonLabel, splitQuestion } from "./format";

describe("formatting", () => {
  it("durations", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(42)).toBe("42s");
    expect(fmtDuration(272)).toBe("4m 32s");
    expect(fmtDuration(3 * 3600 + 120)).toBe("3h 2m");
    expect(fmtDuration(26 * 3600)).toBe("1d 2h");
  });
  it("ages", () => {
    expect(fmtAge(0)).toBe("just now");
    expect(fmtAge(34)).toBe("34 min");
    expect(fmtAge(60)).toBe("1 h");
    expect(fmtAge(60 * 49)).toBe("2 d");
  });
  it("money keeps precision for tiny LLM amounts and never shows null as zero", () => {
    expect(fmtMoney(null)).toBe("—");
    expect(fmtMoney(0)).toBe("$0");
    expect(fmtMoney(0.0008)).toBe("$0.0008");
    expect(fmtMoney(0.0024)).toBe("$0.0024");
    expect(fmtMoney(0.42)).toBe("$0.4200");
    expect(fmtMoney(18.4213)).toBe("$18.42");
  });
  it("percentages, tokens, reasons", () => {
    expect(fmtPct(0.838)).toBe("83.8%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtTokens(950)).toBe("950");
    expect(fmtTokens(12_300)).toBe("12.3k");
    expect(fmtTokens(2_840_000)).toBe("2.84M");
    expect(reasonLabel("RETRY_EXHAUSTED")).toBe("Suggested fixes did not work");
    expect(reasonLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
    expect(reasonLabel(null)).toBe("—");
  });
});

describe("splitQuestion", () => {
  const menu = "Which of these sounds closest to your problem?\n  1. Unable to connect to the Docker daemon\n  2. Certificates not set up correctly\n(reply with the number, or tell me if none of these fit)";
  it("keeps only the prompt when the options are rendered as buttons", () => {
    expect(splitQuestion(menu, ["Unable to connect to the Docker daemon", "Certificates not set up correctly"])).toBe("Which of these sounds closest to your problem?");
  });
  it("leaves open-ended questions untouched", () => {
    const q = "Could you copy the exact error message you see, including any error code?";
    expect(splitQuestion(q, [])).toBe(q);
  });
  it("never returns an empty prompt", () => {
    expect(splitQuestion("1. only a list", ["only a list"])).toBe("1. only a list");
  });
});

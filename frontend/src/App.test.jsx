import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import { axe } from "vitest-axe";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const report = {
  report_id: "report-1",
  status: "complete",
  cached: false,
  question: { question_type: "fact", question_type_origin: "classifier" },
  recommendation_message: "No automated recommendation",
  recommended_answer: null,
  model_comparison: [{ id: "answer-1", model: "deterministic", score: 0, parse_status: "parsed", answer: "Returned answer", claims: [] }],
  evidence: [],
  consensus: [],
  disagreements: [],
  warnings: [],
  constraints_check: {},
};

const comparisonReport = {
  ...report,
  status: "partial",
  model_comparison: [
    { id: "openai-answer", model: "gpt-test", provider: "openai", score: 0.4, parse_status: "parsed", answer: "Structured answer", claims: [] },
    { id: "deepseek-answer", model: "deepseek-test", provider: "deepseek", score: 0, parse_status: "degraded", parse_diagnostics: ["repair response failed schema validation"], answer: "Unstructured fallback", claims: [], failure_class: "protocol_error" },
  ],
};

describe("single-turn question form", () => {
  it("submits once and renders the answer and classification origin", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => report });
    render(<App />);
    const input = screen.getByLabelText("Question");
    fireEvent.change(input, { target: { value: "Who wrote this?" } });
    const form = input.closest("form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Cross-check results" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("classifier", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Returned answer")).toBeInTheDocument();
  });

  it("preserves entered values when the API rejects a request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, json: async () => ({ error: { message: "Invalid question" } }) });
    render(<App />);
    const input = screen.getByLabelText("Question");
    fireEvent.change(input, { target: { value: "Keep this text" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Invalid question"));
    expect(input).toHaveValue("Keep this text");
  });

  it("keeps both providers auditable and labels a degraded response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => comparisonReport });
    render(<App />);
    const input = screen.getByLabelText("Question");
    fireEvent.change(input, { target: { value: "Compare answers" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => expect(screen.getAllByText("Structured answer").length).toBeGreaterThan(0));
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("deepseek")).toBeInTheDocument();
    expect(screen.getByText("Degraded plain text")).toBeInTheDocument();
    expect(screen.getByText(/Provider status: protocol_error/)).toBeInTheDocument();
  });

  it("surfaces partial provider status and keeps unsafe evidence non-clickable", async () => {
    const partial = {
      ...report,
      status: "partial",
      warnings: ["A provider timed out."],
      model_comparison: [{ ...report.model_comparison[0], provider_status: "timeout", retry_count: 2, failure_class: "deadline" }],
      evidence: [
        { url: "javascript:alert(1)", title: "unsafe" },
        { url: "https://example.com/source", title: "safe" },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => partial });
    render(<App />);
    const input = screen.getByLabelText("Question");
    fireEvent.change(input, { target: { value: "Who?" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => expect(screen.getByText("timeout", { selector: "strong" })).toBeInTheDocument());
    expect(screen.getByText(/2 retries/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /javascript/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "example.com" })).toHaveAttribute("rel", "noreferrer noopener");
  });

  it("renders assurance sections and submits feedback without discarding typed values", async () => {
    const assurance = {
      ...report,
      consensus: [{ cluster_id: "c1", claim_text: "Verified fact", support_models: ["m1", "m2"], evidence_ids: ["e1"] }],
      disagreements: [{ cluster_id: "c2", claim_text: "Uncertain fact", reason: "singleton claim", answer_ids: ["answer-1"] }],
      constraints_check: { budget: { status: "satisfied", reason: "within budget" } },
      model_comparison: [{ ...report.model_comparison[0], score_components: { fact_verification: { score: 1, weight: .3 } }, claims: [{ id: "claim-1", claim: "Verified fact", verification_status: "verified", evidence_ids: ["e1"] }] }],
      evidence: [{ id: "e1", url: "https://example.com", title: "Evidence" }],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({ ok: true, json: async () => assurance })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ feedback_id: "f1" }) });
    render(<App />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Who?" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Consensus" })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Disagreements" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Constraint checks" })).toBeInTheDocument();
    expect(screen.getByText("fact_verification")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Helpful"));
    fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "Useful" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit feedback" }));
    await waitFor(() => expect(screen.getByText("Feedback saved.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/api/feedback"), expect.any(Object));
  });

  it("uses evidence-only language for high-compliance reports", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => ({ ...report, evidence_only: true, recommended_answer: { ...report.model_comparison[0] } }) });
    render(<App />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "medical advice" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form"));
    await waitFor(() => expect(screen.getByText("Evidence summary", { selector: ".eyebrow" })).toBeInTheDocument());
    expect(screen.queryByText("Recommendation", { selector: ".eyebrow" })).not.toBeInTheDocument();
  });

  it("has no automated accessibility violations in the complete report flow", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => report });
    const { container } = render(<App />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Accessible report" } });
    fireEvent.submit(screen.getByLabelText("Question").closest("form"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Cross-check results" })).toBeInTheDocument());
    expect(await axe(container)).toHaveNoViolations();
  });
});

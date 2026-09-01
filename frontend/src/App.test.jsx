import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

afterEach(() => vi.restoreAllMocks());

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
});

import { useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function safeHttpUrl(value) {
  if (!value || typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function StatusBadge({ status }) {
  const labels = {
    verified: "✓ Verified",
    unverified: "⚠ Unverified",
    unavailable: "⚠ Unavailable",
    conflict: "✕ Conflict",
    pending: "… Pending",
    not_applicable: "— Not applicable",
  };
  return <span className={`status-badge status-${status || "unverified"}`}>{labels[status] || "⚠ Unverified"}</span>;
}

function ModelCard({ answer, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="model-card" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span>{answer.model}</span>
        <span className="model-meta">{answer.parse_status} · score {Number(answer.score || 0).toFixed(2)}</span>
      </summary>
      <div className="model-card-body">
        <p>{answer.answer}</p>
        {answer.reasoning ? <p className="rationale"><strong>Rationale:</strong> {answer.reasoning}</p> : null}
        {answer.claims?.length ? (
          <ul className="claim-list">
            {answer.claims.map((claim) => (
              <li key={claim.id || claim.claim}>
                <StatusBadge status={claim.verification_status} /> {claim.claim}
              </li>
            ))}
          </ul>
        ) : <p className="muted">No structured claims were returned.</p>}
      </div>
    </details>
  );
}

function Report({ report }) {
  const evidence = useMemo(() => (Array.isArray(report.evidence) ? report.evidence : []), [report.evidence]);
  return (
    <section className="report" aria-labelledby="report-heading">
      <div className="report-heading-row">
        <div>
          <p className="eyebrow">{report.status === "partial" ? "Partial report" : "Report"}</p>
          <h2 id="report-heading">Cross-check results</h2>
        </div>
        {report.cached ? <span className="cache-pill">Cached</span> : null}
      </div>
      <p className="classification">
        Question type: <strong>{report.question?.question_type}</strong> · selected by <strong>{report.question?.question_type_origin}</strong>
      </p>

      <article className="recommendation" aria-labelledby="recommendation-heading">
        <p className="eyebrow">Recommendation</p>
        <h3 id="recommendation-heading">
          {report.recommended_answer ? `Answer from ${report.recommended_answer.model}` : "No automated recommendation"}
        </h3>
        {report.recommended_answer ? <p>{report.recommended_answer.answer}</p> : <p>{report.recommendation_message}</p>}
      </article>

      {report.warnings?.length ? (
        <aside className="notice warning" role="status">
          <strong>Some checks need attention.</strong>
          <ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </aside>
      ) : null}

      <section className="report-section" aria-labelledby="models-heading">
        <h3 id="models-heading">Model answers</h3>
        {report.model_comparison?.map((answer, index) => <ModelCard answer={answer} defaultOpen={index === 0} key={answer.id || answer.model} />)}
      </section>

      <section className="report-section" aria-labelledby="evidence-heading">
        <h3 id="evidence-heading">Evidence</h3>
        {evidence.length ? (
          <ul className="evidence-list">
            {evidence.map((item, index) => {
              const url = safeHttpUrl(item.url);
              return <li key={item.id || `${item.url}-${index}`}>
                {url ? <a href={url.href} target="_blank" rel="noreferrer noopener">{url.hostname}</a> : <span className="muted">Source unavailable</span>}
                {item.title ? <span> — {item.title}</span> : null}
              </li>;
            })}
          </ul>
        ) : <p className="muted">No independent evidence was attached in this tracer report.</p>}
      </section>

      <p className="notice disclaimer" role="note">AI-generated content may be wrong; verify important information.</p>
    </section>
  );
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [constraints, setConstraints] = useState("");
  const [questionType, setQuestionType] = useState("auto");
  const [outputFormat, setOutputFormat] = useState("plain");
  const [models, setModels] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("");
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);
    setReport(null);
    setStage("Validating your question…");
    const body = { question };
    if (constraints.trim()) {
      try { body.constraints = JSON.parse(constraints); }
      catch { body.constraints = constraints; }
    }
    if (questionType !== "auto") body.question_type = questionType;
    if (outputFormat !== "plain") body.expected_output_format = outputFormat;
    if (models.trim()) body.models = models.split(",").map((model) => model.trim()).filter(Boolean);
    try {
      setStage("Comparing configured models…");
      const response = await fetch(`${API_BASE}/api/query`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.error?.message || "The question could not be processed.");
      }
      setStage("Report ready.");
      setReport(payload);
    } catch (cause) {
      setStage("");
      setError(cause instanceof Error ? cause.message : "The question could not be processed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">CrossCheck AI</p>
        <h1>Ask once. Inspect the evidence.</h1>
        <p className="hero-copy">A focused, single-turn comparison of model answers with visible uncertainty.</p>
      </header>

      <form className="query-form" onSubmit={submit}>
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What would you like to cross-check?"
          maxLength={10000}
          required
          rows={4}
        />
        <button type="button" className="advanced-toggle" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>
          {advanced ? "Hide advanced options" : "Show advanced options"}
        </button>
        {advanced ? (
          <div className="advanced-fields">
            <label htmlFor="constraints">Constraints <span className="muted">(JSON or natural language)</span></label>
            <textarea id="constraints" value={constraints} onChange={(event) => setConstraints(event.target.value)} rows={3} />
            <label htmlFor="question-type">Question type</label>
            <select id="question-type" value={questionType} onChange={(event) => setQuestionType(event.target.value)}>
              <option value="auto">Auto-detect</option><option value="fact">Fact</option><option value="code">Code</option><option value="constraint">Constraint</option>
            </select>
            <label htmlFor="output-format">Expected output</label>
            <select id="output-format" value={outputFormat} onChange={(event) => setOutputFormat(event.target.value)}>
              <option value="plain">Plain answer</option><option value="list">List</option><option value="table">Comparison table</option><option value="steps">Steps</option>
            </select>
            <label htmlFor="models">Models <span className="muted">(comma-separated, optional)</span></label>
            <input id="models" value={models} onChange={(event) => setModels(event.target.value)} placeholder="Use server defaults" />
          </div>
        ) : null}
        <button className="submit-button" type="submit" disabled={loading || !question.trim()}>
          {loading ? "Checking…" : "Cross-check answer"}
        </button>
        <p className="status-line" aria-live="polite">{stage}</p>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
      </form>

      {report ? <Report report={report} /> : null}
    </main>
  );
}

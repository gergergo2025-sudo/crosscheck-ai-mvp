import { useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function safeHttpUrl(value) {
  if (!value || typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname || url.username || url.password || /[\u0000-\u001f\u007f]/.test(value)) return null;
    return url;
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

function ParseBadge({ status }) {
  const degraded = status === "degraded";
  return (
    <span className={`parse-badge ${degraded ? "parse-degraded" : "parse-structured"}`}>
      {degraded ? "Degraded plain text" : "Structured answer"}
    </span>
  );
}

function ModelCard({ answer, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="model-card" id={`answer-${answer.id}`} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className="model-title">
          <strong>{answer.model}</strong>
          {answer.provider ? (
            <span className="model-provider">
              {answer.provider}{answer.provider_status && answer.provider_status !== "ok" ? ` · ${answer.provider_status}` : ""}
            </span>
          ) : null}
        </span>
        <span className="model-meta"><ParseBadge status={answer.parse_status} /> · score {Number(answer.score || 0).toFixed(2)}</span>
      </summary>
      <div className="model-card-body">
        {answer.provider_status && answer.provider_status !== "ok" ? (
          <p className="provider-status" role="status" aria-label={`Provider status for ${answer.model}`}>
            Provider status: <strong>{answer.provider_status}</strong>
            {answer.retry_count ? ` · ${answer.retry_count} retr${answer.retry_count === 1 ? "y" : "ies"}` : null}
            {answer.failure_class ? ` · ${answer.failure_class}` : null}
          </p>
        ) : null}
        {answer.failure_class && (!answer.provider_status || answer.provider_status === "ok") ? (
          <p className="notice warning provider-failure">Provider status: {answer.failure_class}</p>
        ) : null}
        <p>{answer.answer}</p>
        {answer.reasoning ? <p className="rationale"><strong>Rationale:</strong> {answer.reasoning}</p> : null}
        {answer.claims?.length ? (
          <ul className="claim-list">
            {answer.claims.map((claim) => (
              <li key={claim.id || claim.claim}>
                <StatusBadge status={claim.verification_status} /> {claim.claim}
                {claim.evidence_ids?.map((id) => <a className="evidence-ref" href={`#evidence-${id}`} key={id}>evidence</a>)}
              </li>
            ))}
            </ul>
        ) : <p className="muted">{answer.parse_status === "degraded" ? "Degraded response: no structured claims are available." : "No structured claims were returned."}</p>}
        {answer.parse_diagnostics?.length ? (
          <p className="parse-diagnostics muted">{answer.parse_diagnostics.join(" ")}</p>
        ) : null}
        {answer.score_components && Object.keys(answer.score_components).length ? (
          <div className="score-breakdown">
            <strong>Score breakdown</strong>
            <dl>{Object.entries(answer.score_components).map(([name, component]) => (
              <div key={name}><dt>{name}</dt><dd>{component?.score == null ? component?.reason : Number(component.score).toFixed(2)}</dd></div>
            ))}</dl>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function FeedbackForm({ report }) {
  const claims = report.model_comparison?.flatMap((answer) => answer.claims || []) || [];
  const [helpful, setHelpful] = useState(null);
  const [claimId, setClaimId] = useState("");
  const [comment, setComment] = useState("");
  const [suggestedAnswer, setSuggestedAnswer] = useState("");
  const [state, setState] = useState({ loading: false, message: "", error: false });

  async function submitFeedback(event) {
    event.preventDefault();
    if (helpful == null || state.loading) return;
    setState({ loading: true, message: "", error: false });
    const body = { report_id: report.report_id, helpful };
    if (claimId) body.claim_id = claimId;
    if (comment.trim()) body.comment = comment;
    if (suggestedAnswer.trim()) body.suggested_answer = suggestedAnswer;
    try {
      const response = await fetch(`${API_BASE}/api/feedback`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.error?.message || "Feedback could not be saved.");
      setState({ loading: false, message: "Feedback saved.", error: false });
    } catch (cause) {
      setState({ loading: false, message: cause instanceof Error ? cause.message : "Feedback could not be saved.", error: true });
    }
  }

  return <form className="feedback-form" onSubmit={submitFeedback} aria-labelledby="feedback-heading">
    <h3 id="feedback-heading">Feedback</h3>
    <fieldset><legend>Was this report helpful?</legend>
      <label><input type="radio" name="helpful" aria-label="Helpful" checked={helpful === true} onChange={() => setHelpful(true)} /> Helpful</label>
      <label><input type="radio" name="helpful" aria-label="Not helpful" checked={helpful === false} onChange={() => setHelpful(false)} /> Not helpful</label>
    </fieldset>
    <label htmlFor="error-claim">Erroneous claim <span className="muted">(optional)</span></label>
    <select id="error-claim" value={claimId} onChange={(event) => setClaimId(event.target.value)}><option value="">None selected</option>{claims.map((claim) => <option value={claim.id} key={claim.id}>{claim.claim}</option>)}</select>
    <label htmlFor="feedback-comment">Comment</label><textarea id="feedback-comment" aria-label="Comment" value={comment} maxLength={5000} onChange={(event) => setComment(event.target.value)} />
    <label htmlFor="suggested-answer">Suggested answer</label><textarea id="suggested-answer" value={suggestedAnswer} maxLength={20000} onChange={(event) => setSuggestedAnswer(event.target.value)} />
    <button type="submit" disabled={helpful == null || state.loading}>{state.loading ? "Saving…" : "Submit feedback"}</button>
    {state.message ? <p role={state.error ? "alert" : "status"}>{state.message}</p> : null}
  </form>;
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
        <p className="eyebrow">{report.evidence_only ? "Evidence summary" : "Recommendation"}</p>
        <h3 id="recommendation-heading">
          {report.evidence_only ? "Decision endorsement suppressed" : report.recommended_answer ? `Answer from ${report.recommended_answer.model}` : "No automated recommendation"}
        </h3>
        {!report.evidence_only && report.recommended_answer ? <p>{report.recommended_answer.answer}</p> : <p>{report.recommendation_message}</p>}
      </article>

      {report.warnings?.length ? (
        <aside className="notice warning" role="status">
          <strong>Some checks need attention.</strong>
          <ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </aside>
      ) : null}

      <div className="report-layout"><div className="assurance-column">
      <section className="report-section" aria-labelledby="consensus-heading"><h3 id="consensus-heading">Consensus</h3>
        {report.consensus?.length ? <ul>{report.consensus.map((item) => <li key={item.cluster_id}><StatusBadge status="verified" /> {item.claim_text}<span className="muted"> — {item.support_models?.join(", ")}</span></li>)}</ul> : <p className="muted">No independently verified multi-provider consensus.</p>}
      </section>
      <section className="report-section" aria-labelledby="disagreements-heading"><h3 id="disagreements-heading">Disagreements</h3>
        {report.disagreements?.length ? <ul>{report.disagreements.map((item, index) => <li key={item.cluster_id || index}>{item.claim_text} <span className="muted">— {item.reason}</span>{item.answer_ids?.map((id) => <a className="answer-ref" href={`#answer-${id}`} key={id}>view answer</a>)}</li>)}</ul> : <p className="muted">No disagreement items.</p>}
      </section>
      <section className="report-section" aria-labelledby="constraints-heading"><h3 id="constraints-heading">Constraint checks</h3>
        {Object.keys(report.constraints_check || {}).length ? <dl className="constraint-list">{Object.entries(report.constraints_check).map(([name, check]) => <div key={name}><dt>{name}</dt><dd><StatusBadge status={check.status === "satisfied" ? "verified" : check.status === "violated" ? "conflict" : "unverified"} /> {check.reason}</dd></div>)}</dl> : <p className="muted">No submitted constraints.</p>}
      </section>
      <section className="report-section" aria-labelledby="evidence-heading">
        <h3 id="evidence-heading">Evidence</h3>
        {evidence.length ? (
          <ul className="evidence-list">
            {evidence.map((item, index) => {
              const url = safeHttpUrl(item.url);
              return <li id={item.id ? `evidence-${item.id}` : undefined} key={item.id || `${item.url}-${index}`}>
                {url ? <a href={url.href} target="_blank" rel="noreferrer noopener">{url.hostname}</a> : <span className="muted">Source unavailable</span>}
                {item.title ? <span> — {item.title}</span> : null}
              </li>;
            })}
          </ul>
        ) : <p className="muted">No independent evidence was attached in this tracer report.</p>}
      </section>
      </div><aside className="model-column"><section className="report-section" aria-labelledby="models-heading">
        <h3 id="models-heading">Model answers</h3>
        <div className="comparison-grid" aria-label="Model comparison">{report.model_comparison?.map((answer, index) => <ModelCard answer={answer} defaultOpen={index === 0} key={answer.id || answer.model} />)}</div>
      </section></aside></div>

      <FeedbackForm report={report} />

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
    <main className="app-shell" aria-busy={loading}>
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
        <p className="status-line" role="status" aria-live="polite">{stage}</p>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
      </form>

      {report ? <Report report={report} /> : null}
    </main>
  );
}

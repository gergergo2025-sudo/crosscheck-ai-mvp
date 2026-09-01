from crosscheck.parser import parse_structured_answer


def test_parser_accepts_fenced_and_embedded_json_with_unknown_fields():
    raw = """Provider note
```json
{"answer":"ok","claims":[{"claim":"a","type":"fact","confidence":0.8}],"constraints_check":{},"future":true}
```"""
    parsed = parse_structured_answer(raw)
    assert parsed.parse_success
    assert parsed.structured.answer == "ok"
    assert parsed.structured.claims[0].source is None


def test_parser_degrades_when_required_shape_or_confidence_is_invalid():
    missing_claims = parse_structured_answer('{"answer":"ok","constraints_check":{}}')
    invalid_confidence = parse_structured_answer(
        '{"answer":"ok","claims":[{"claim":"a","type":"fact","confidence":2}],"constraints_check":{}}'
    )
    assert missing_claims.parse_status == "degraded"
    assert invalid_confidence.parse_status == "degraded"

"""Answerers: turn a review object into claims (plan 14.3).

    answer(review_obj, case) -> {claims: [{rule, step?, evidence: [ids]}]}

Both answerers here are model-free. 14.4 plugs a model answerer into the same
interface and the scorer stays as it is.
"""

INVENTED_ID = "e99"


def _step_of(review_obj, ids):
    by_id = {e["id"]: e for e in review_obj["evidence"]}
    for ident in ids:
        step = by_id.get(ident, {}).get("step")
        if step:
            return step
    return None


def echo_answerer(review_obj, case):
    """One claim per finding, citing the finding's own evidence (a perfect answer)."""
    claims = []
    for finding in review_obj["findings"]:
        claim = {"rule": finding["rule"], "evidence": list(finding["evidence"])}
        step = _step_of(review_obj, finding["evidence"])
        if step:
            claim["step"] = step
        claims.append(claim)
    return {"claims": claims}


def bad_answerer(review_obj, case):
    """Echo claims with the real ids dropped and an invented id cited. It must fail validity."""
    claims = echo_answerer(review_obj, case)["claims"]
    for claim in claims:
        claim["evidence"] = [INVENTED_ID]
    return {"claims": claims}


ANSWERERS = {"echo": echo_answerer, "bad": bad_answerer}

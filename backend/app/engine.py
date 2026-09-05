from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from difflib import SequenceMatcher
from itertools import combinations
from typing import Any
from uuid import uuid4

from .models import (
    ColumnMapping,
    MatchCardinality,
    MatchPair,
    MatchStatus,
    ReconciliationResult,
    ReconciliationRules,
    ReconciliationSummary,
)


def _money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw[:19], fmt).date()
        except ValueError:
            continue
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def _join_values(values: list[str]) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return " | ".join(unique) or None


def _score(
    left: dict[str, Any],
    right: dict[str, Any],
    lm: ColumnMapping,
    rm: ColumnMapping,
    rules: ReconciliationRules,
) -> tuple[float, list[str], dict[str, Any]]:
    la, ra = _money(left.get(lm.amount)), _money(right.get(rm.amount))
    if la is None or ra is None:
        return 0.0, ["valor ausente ou inválido"], {"amount_left": la, "amount_right": ra}
    diff = abs(la - ra)
    amount_score = 1.0 if diff <= rules.amount_tolerance else max(0.0, 1 - (diff / max(abs(la), abs(ra), 1)))
    components = [(amount_score, 0.55)]
    reasons = [f"diferença de valor: {diff:.2f}"]

    ld = _date(left.get(lm.date)) if lm.date else None
    rd = _date(right.get(rm.date)) if rm.date else None
    if lm.date and rm.date:
        if ld and rd:
            day_diff = abs((ld - rd).days)
            date_score = 1.0 if day_diff <= rules.date_tolerance_days else max(0.0, 1 - day_diff / 31)
            reasons.append(f"diferença de data: {day_diff} dia(s)")
        else:
            date_score = 0.0
            reasons.append("data inválida")
        components.append((date_score, 0.2))

    ls = _text(left.get(lm.description)) if lm.description else ""
    rs = _text(right.get(rm.description)) if rm.description else ""
    desc_score = None
    if lm.description and rm.description:
        desc_score = _similarity(ls, rs)
        components.append((desc_score, 0.15))
        reasons.append(f"similaridade da descrição: {desc_score:.0%}")

    ldoc = _text(left.get(lm.document)) if lm.document else ""
    rdoc = _text(right.get(rm.document)) if rm.document else ""
    if lm.document and rm.document:
        doc_score = 1.0 if ldoc and rdoc and ldoc.casefold() == rdoc.casefold() else 0.0
        components.append((doc_score, 0.1))
        reasons.append("documento igual" if doc_score else "documento diferente")
        if rules.require_document_exact and doc_score == 0:
            return 0.0, reasons, {
                "amount_left": la,
                "amount_right": ra,
                "amount_difference": la - ra,
                "date_left": str(ld) if ld else None,
                "date_right": str(rd) if rd else None,
                "description_left": ls or None,
                "description_right": rs or None,
                "document_left": ldoc or None,
                "document_right": rdoc or None,
            }

    weight = sum(w for _, w in components)
    confidence = sum(s * w for s, w in components) / weight if weight else 0.0
    details = {
        "amount_left": la,
        "amount_right": ra,
        "amount_difference": la - ra,
        "date_left": str(ld) if ld else None,
        "date_right": str(rd) if rd else None,
        "description_left": ls or None,
        "description_right": rs or None,
        "document_left": ldoc or None,
        "document_right": rdoc or None,
        "description_similarity": desc_score,
        "amount_exact": diff <= rules.amount_tolerance,
    }
    return round(confidence, 4), reasons, details


def _score_group(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    lm: ColumnMapping,
    rm: ColumnMapping,
    rules: ReconciliationRules,
    cardinality: MatchCardinality,
) -> tuple[float, list[str], dict[str, Any]]:
    left_amounts = [_money(row.get(lm.amount)) for row in left_rows]
    right_amounts = [_money(row.get(rm.amount)) for row in right_rows]
    if any(value is None for value in left_amounts + right_amounts):
        return 0.0, ["valor ausente ou inválido no agrupamento"], {}

    total_left = sum(value or 0 for value in left_amounts)
    total_right = sum(value or 0 for value in right_amounts)
    diff = abs(total_left - total_right)
    if diff > rules.amount_tolerance:
        return 0.0, [f"soma do agrupamento fora da tolerância: {diff:.2f}"], {}

    components: list[tuple[float, float]] = [(1.0, 0.65)]
    reasons = [
        f"match agrupado {cardinality.value}",
        f"soma base A: {total_left:.2f}",
        f"soma base B: {total_right:.2f}",
        f"diferença agrupada: {diff:.2f}",
    ]

    left_dates = [_date(row.get(lm.date)) for row in left_rows] if lm.date else []
    right_dates = [_date(row.get(rm.date)) for row in right_rows] if rm.date else []
    valid_left_dates = [value for value in left_dates if value]
    valid_right_dates = [value for value in right_dates if value]
    if lm.date and rm.date:
        if len(valid_left_dates) != len(left_rows) or len(valid_right_dates) != len(right_rows):
            date_score = 0.0
            reasons.append("data inválida no agrupamento")
        else:
            max_day_diff = max(abs((ld - rd).days) for ld in valid_left_dates for rd in valid_right_dates)
            date_score = 1.0 if max_day_diff <= rules.date_tolerance_days else max(0.0, 1 - max_day_diff / 31)
            reasons.append(f"maior diferença de data no grupo: {max_day_diff} dia(s)")
        components.append((date_score, 0.2))

    left_desc = [_text(row.get(lm.description)) for row in left_rows] if lm.description else []
    right_desc = [_text(row.get(rm.description)) for row in right_rows] if rm.description else []
    if lm.description and rm.description:
        comparisons = [_similarity(a, b) for a in left_desc for b in right_desc if a and b]
        joined_similarity = _similarity(" ".join(left_desc), " ".join(right_desc))
        desc_score = max(comparisons + [joined_similarity]) if comparisons or joined_similarity else 0.0
        components.append((desc_score, 0.1))
        reasons.append(f"similaridade textual do grupo: {desc_score:.0%}")

    left_docs = [_text(row.get(lm.document)) for row in left_rows] if lm.document else []
    right_docs = [_text(row.get(rm.document)) for row in right_rows] if rm.document else []
    if lm.document and rm.document:
        left_doc_set = {value.casefold() for value in left_docs if value}
        right_doc_set = {value.casefold() for value in right_docs if value}
        doc_score = 1.0 if left_doc_set & right_doc_set else 0.0
        components.append((doc_score, 0.05))
        reasons.append("documento relacionado no grupo" if doc_score else "sem documento idêntico no grupo")
        if rules.require_document_exact and doc_score == 0:
            return 0.0, reasons, {}

    weight = sum(weight for _, weight in components)
    confidence = sum(score * weight for score, weight in components) / weight if weight else 0.0
    details = {
        "amount_left": total_left,
        "amount_right": total_right,
        "amount_difference": total_left - total_right,
        "date_left": _join_values([str(value) for value in valid_left_dates]),
        "date_right": _join_values([str(value) for value in valid_right_dates]),
        "description_left": _join_values(left_desc),
        "description_right": _join_values(right_desc),
        "document_left": _join_values(left_docs),
        "document_right": _join_values(right_docs),
        "amount_exact": True,
    }
    return round(confidence, 4), reasons, details


def _same_sign_or_zero(target: float, candidate: float) -> bool:
    if target == 0 or candidate == 0:
        return True
    return (target > 0) == (candidate > 0)


def _group_pool(
    anchor: dict[str, Any],
    candidate_indices: set[int],
    candidate_rows: list[dict[str, Any]],
    anchor_mapping: ColumnMapping,
    candidate_mapping: ColumnMapping,
    rules: ReconciliationRules,
) -> list[int]:
    target = _money(anchor.get(anchor_mapping.amount))
    if target is None:
        return []
    anchor_date = _date(anchor.get(anchor_mapping.date)) if anchor_mapping.date else None
    pool: list[tuple[float, int]] = []
    for index in candidate_indices:
        row = candidate_rows[index]
        amount = _money(row.get(candidate_mapping.amount))
        if amount is None or not _same_sign_or_zero(target, amount):
            continue
        if target != 0 and abs(amount) > abs(target) + rules.amount_tolerance:
            continue
        if anchor_mapping.date and candidate_mapping.date and anchor_date:
            candidate_date = _date(row.get(candidate_mapping.date))
            if candidate_date is None or abs((anchor_date - candidate_date).days) > rules.date_tolerance_days:
                continue
        pool.append((abs(abs(target) - abs(amount)), index))
    pool.sort(key=lambda item: (item[0], item[1]))
    return [index for _, index in pool[: rules.group_candidate_limit]]


def _best_one_to_many(
    left_index: int,
    left_rows: list[dict[str, Any]],
    right_available: set[int],
    right_rows: list[dict[str, Any]],
    lm: ColumnMapping,
    rm: ColumnMapping,
    rules: ReconciliationRules,
) -> tuple[float, tuple[int, ...], list[str], dict[str, Any]] | None:
    pool = _group_pool(left_rows[left_index], right_available, right_rows, lm, rm, rules)
    best: tuple[float, tuple[int, ...], list[str], dict[str, Any]] | None = None
    for size in range(2, min(rules.max_group_size, len(pool)) + 1):
        for combo in combinations(pool, size):
            grouped_rows = [right_rows[index] for index in combo]
            confidence, reasons, details = _score_group(
                [left_rows[left_index]], grouped_rows, lm, rm, rules, MatchCardinality.ONE_TO_MANY
            )
            if confidence < rules.group_match_threshold:
                continue
            candidate = (confidence, combo, reasons, details)
            if best is None or (confidence, -abs(details.get("amount_difference", 0))) > (
                best[0], -abs(best[3].get("amount_difference", 0))
            ):
                best = candidate
            if confidence >= 0.9999:
                return best
    return best


def _best_many_to_one(
    right_index: int,
    right_rows: list[dict[str, Any]],
    left_available: set[int],
    left_rows: list[dict[str, Any]],
    lm: ColumnMapping,
    rm: ColumnMapping,
    rules: ReconciliationRules,
) -> tuple[float, tuple[int, ...], list[str], dict[str, Any]] | None:
    pool = _group_pool(right_rows[right_index], left_available, left_rows, rm, lm, rules)
    best: tuple[float, tuple[int, ...], list[str], dict[str, Any]] | None = None
    for size in range(2, min(rules.max_group_size, len(pool)) + 1):
        for combo in combinations(pool, size):
            grouped_rows = [left_rows[index] for index in combo]
            confidence, reasons, details = _score_group(
                grouped_rows, [right_rows[right_index]], lm, rm, rules, MatchCardinality.MANY_TO_ONE
            )
            if confidence < rules.group_match_threshold:
                continue
            candidate = (confidence, combo, reasons, details)
            if best is None or (confidence, -abs(details.get("amount_difference", 0))) > (
                best[0], -abs(best[3].get("amount_difference", 0))
            ):
                best = candidate
            if confidence >= 0.9999:
                return best
    return best


def _make_pair(
    *,
    left_indices: list[int],
    right_indices: list[int],
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    cardinality: MatchCardinality,
    status: MatchStatus,
    confidence: float,
    reasons: list[str],
    details: dict[str, Any] | None = None,
) -> MatchPair:
    details = details or {}
    selected_left = [left_rows[index] for index in left_indices]
    selected_right = [right_rows[index] for index in right_indices]
    return MatchPair(
        pair_id=str(uuid4()),
        left_index=left_indices[0] if len(left_indices) == 1 else None,
        right_index=right_indices[0] if len(right_indices) == 1 else None,
        left_indices=left_indices,
        right_indices=right_indices,
        match_cardinality=cardinality,
        status=status,
        confidence=confidence,
        reasons=reasons,
        left_row=selected_left[0] if len(selected_left) == 1 else None,
        right_row=selected_right[0] if len(selected_right) == 1 else None,
        left_rows=selected_left,
        right_rows=selected_right,
        **{key: value for key, value in details.items() if key not in {"description_similarity", "amount_exact"}},
    )


def _build_summary(
    reconciliation_id: str,
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    lm: ColumnMapping,
    rm: ColumnMapping,
    pairs: list[MatchPair],
) -> ReconciliationSummary:
    status_counts = Counter(pair.status for pair in pairs)
    accepted_statuses = {MatchStatus.MATCH, MatchStatus.APPROVED}
    reconciled_left = {index for pair in pairs if pair.status in accepted_statuses for index in pair.left_indices}
    reconciled_right = {index for pair in pairs if pair.status in accepted_statuses for index in pair.right_indices}
    one_to_many = sum(pair.match_cardinality == MatchCardinality.ONE_TO_MANY for pair in pairs)
    many_to_one = sum(pair.match_cardinality == MatchCardinality.MANY_TO_ONE for pair in pairs)
    total_left_amount = sum(_money(row.get(lm.amount)) or 0 for row in left_rows)
    total_right_amount = sum(_money(row.get(rm.amount)) or 0 for row in right_rows)
    matched = status_counts[MatchStatus.MATCH] + status_counts[MatchStatus.APPROVED]
    return ReconciliationSummary(
        reconciliation_id=reconciliation_id,
        total_left=len(left_rows),
        total_right=len(right_rows),
        matched=matched,
        probable_matches=status_counts[MatchStatus.PROBABLE_MATCH],
        divergences=status_counts[MatchStatus.DIVERGENCE],
        unmatched=status_counts[MatchStatus.UNMATCHED],
        duplicates=status_counts[MatchStatus.DUPLICATE],
        manual_review=status_counts[MatchStatus.MANUAL_REVIEW],
        one_to_many=one_to_many,
        many_to_one=many_to_one,
        grouped_matches=one_to_many + many_to_one,
        reconciled_left_rows=len(reconciled_left),
        reconciled_right_rows=len(reconciled_right),
        match_rate=round(len(reconciled_left) / max(len(left_rows), 1), 4),
        total_amount_left=round(total_left_amount, 2),
        total_amount_right=round(total_right_amount, 2),
        net_difference=round(total_left_amount - total_right_amount, 2),
    )


def refresh_summary(result: ReconciliationResult) -> ReconciliationResult:
    """Recalcula contadores após decisão humana sem reprocessar os dados originais."""
    summary = result.summary
    status_counts = Counter(pair.status for pair in result.pairs)
    accepted_statuses = {MatchStatus.MATCH, MatchStatus.APPROVED}
    reconciled_left = {index for pair in result.pairs if pair.status in accepted_statuses for index in pair.left_indices}
    reconciled_right = {index for pair in result.pairs if pair.status in accepted_statuses for index in pair.right_indices}
    summary.matched = status_counts[MatchStatus.MATCH] + status_counts[MatchStatus.APPROVED]
    summary.probable_matches = status_counts[MatchStatus.PROBABLE_MATCH]
    summary.divergences = status_counts[MatchStatus.DIVERGENCE]
    summary.unmatched = status_counts[MatchStatus.UNMATCHED]
    summary.duplicates = status_counts[MatchStatus.DUPLICATE]
    summary.manual_review = status_counts[MatchStatus.MANUAL_REVIEW]
    summary.reconciled_left_rows = len(reconciled_left)
    summary.reconciled_right_rows = len(reconciled_right)
    summary.match_rate = round(len(reconciled_left) / max(summary.total_left, 1), 4)
    return result


def reconcile(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    lm: ColumnMapping,
    rm: ColumnMapping,
    rules: ReconciliationRules,
    reconciliation_id: str,
) -> ReconciliationResult:
    pairs: list[MatchPair] = []

    left_keys = [(_text(row.get(lm.document)), _money(row.get(lm.amount))) for row in left_rows] if lm.document else []
    right_keys = [(_text(row.get(rm.document)), _money(row.get(rm.amount))) for row in right_rows] if rm.document else []
    left_counts, right_counts = Counter(left_keys), Counter(right_keys)
    duplicate_left = {
        index for index, key in enumerate(left_keys)
        if key[0] and key[1] is not None and left_counts[key] > 1
    }
    duplicate_right = {
        index for index, key in enumerate(right_keys)
        if key[0] and key[1] is not None and right_counts[key] > 1
    }

    left_available = set(range(len(left_rows))) - duplicate_left
    right_available = set(range(len(right_rows))) - duplicate_right

    for index in sorted(duplicate_left):
        pairs.append(
            _make_pair(
                left_indices=[index], right_indices=[], left_rows=left_rows, right_rows=right_rows,
                cardinality=MatchCardinality.ONE_TO_ONE, status=MatchStatus.DUPLICATE, confidence=1,
                reasons=["registro duplicado na base principal"],
            )
        )
    for index in sorted(duplicate_right):
        pairs.append(
            _make_pair(
                left_indices=[], right_indices=[index], left_rows=left_rows, right_rows=right_rows,
                cardinality=MatchCardinality.ONE_TO_ONE, status=MatchStatus.DUPLICATE, confidence=1,
                reasons=["registro duplicado na base comparada"],
            )
        )

    # 1) Resolve primeiro os matches 1:1 fortes e exatos, preservando os demais para agrupamento.
    for left_index in sorted(list(left_available)):
        candidates: list[tuple[float, int, list[str], dict[str, Any]]] = []
        for right_index in sorted(right_available):
            confidence, reasons, details = _score(left_rows[left_index], right_rows[right_index], lm, rm, rules)
            if details.get("amount_exact") and confidence >= rules.auto_approve_threshold:
                candidates.append((confidence, right_index, reasons, details))
        if not candidates:
            continue
        confidence, right_index, reasons, details = max(candidates, key=lambda item: (item[0], -item[1]))
        left_available.discard(left_index)
        right_available.discard(right_index)
        pairs.append(
            _make_pair(
                left_indices=[left_index], right_indices=[right_index], left_rows=left_rows, right_rows=right_rows,
                cardinality=MatchCardinality.ONE_TO_ONE, status=MatchStatus.MATCH, confidence=confidence,
                reasons=reasons, details=details,
            )
        )

    # 2) Procura 1:N e N:1 apenas nos registros que sobraram do 1:1 exato.
    if rules.group_matching_enabled:
        group_candidates: list[tuple[float, MatchCardinality, tuple[int, ...], tuple[int, ...], list[str], dict[str, Any]]] = []
        for left_index in sorted(left_available):
            best = _best_one_to_many(left_index, left_rows, right_available, right_rows, lm, rm, rules)
            if best:
                confidence, right_group, reasons, details = best
                group_candidates.append((confidence, MatchCardinality.ONE_TO_MANY, (left_index,), right_group, reasons, details))
        for right_index in sorted(right_available):
            best = _best_many_to_one(right_index, right_rows, left_available, left_rows, lm, rm, rules)
            if best:
                confidence, left_group, reasons, details = best
                group_candidates.append((confidence, MatchCardinality.MANY_TO_ONE, left_group, (right_index,), reasons, details))

        group_candidates.sort(
            key=lambda item: (-item[0], abs(item[5].get("amount_difference", 0)), item[1].value, item[2], item[3])
        )
        for confidence, cardinality, left_group, right_group, reasons, details in group_candidates:
            if not set(left_group) <= left_available or not set(right_group) <= right_available:
                continue
            left_available.difference_update(left_group)
            right_available.difference_update(right_group)
            status = MatchStatus.MATCH if confidence >= rules.auto_approve_threshold else MatchStatus.PROBABLE_MATCH
            pairs.append(
                _make_pair(
                    left_indices=list(left_group), right_indices=list(right_group), left_rows=left_rows, right_rows=right_rows,
                    cardinality=cardinality, status=status, confidence=confidence, reasons=reasons, details=details,
                )
            )

    # 3) Só então usa matching 1:1 aproximado/divergente para o restante.
    for left_index in sorted(list(left_available)):
        candidates: list[tuple[float, int, list[str], dict[str, Any]]] = []
        for right_index in sorted(right_available):
            confidence, reasons, details = _score(left_rows[left_index], right_rows[right_index], lm, rm, rules)
            candidates.append((confidence, right_index, reasons, details))
        candidates.sort(reverse=True, key=lambda item: item[0])
        if not candidates or candidates[0][0] < rules.probable_match_threshold:
            pairs.append(
                _make_pair(
                    left_indices=[left_index], right_indices=[], left_rows=left_rows, right_rows=right_rows,
                    cardinality=MatchCardinality.ONE_TO_ONE, status=MatchStatus.UNMATCHED,
                    confidence=candidates[0][0] if candidates else 0,
                    reasons=["nenhuma correspondência acima do limite mínimo"],
                )
            )
            left_available.discard(left_index)
            continue

        confidence, right_index, reasons, details = candidates[0]
        right_available.discard(right_index)
        left_available.discard(left_index)
        if details.get("amount_exact") and confidence >= rules.auto_approve_threshold:
            status = MatchStatus.MATCH
        elif confidence >= rules.auto_approve_threshold:
            status = MatchStatus.DIVERGENCE
        else:
            status = MatchStatus.PROBABLE_MATCH
        pairs.append(
            _make_pair(
                left_indices=[left_index], right_indices=[right_index], left_rows=left_rows, right_rows=right_rows,
                cardinality=MatchCardinality.ONE_TO_ONE, status=status, confidence=confidence,
                reasons=reasons, details=details,
            )
        )

    for right_index in sorted(right_available):
        pairs.append(
            _make_pair(
                left_indices=[], right_indices=[right_index], left_rows=left_rows, right_rows=right_rows,
                cardinality=MatchCardinality.ONE_TO_ONE, status=MatchStatus.UNMATCHED, confidence=0,
                reasons=["registro sem correspondência na base principal"],
            )
        )

    summary = _build_summary(reconciliation_id, left_rows, right_rows, lm, rm, pairs)
    return ReconciliationResult(summary=summary, pairs=pairs)

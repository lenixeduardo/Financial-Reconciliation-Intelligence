from app.engine import reconcile
from app.models import ColumnMapping, MatchCardinality, MatchStatus, ReconciliationRules


def test_exact_and_divergent_matches():
    left = [
        {"doc": "1001", "data": "04/09/2026", "desc": "Empresa A", "valor": "1250,00"},
        {"doc": "1002", "data": "05/09/2026", "desc": "Empresa C", "valor": "2100,00"},
    ]
    right = [
        {"ref": "1001", "date": "04/09/2026", "memo": "EMPRESA A PIX", "amount": "1250,00"},
        {"ref": "1002", "date": "05/09/2026", "memo": "EMPRESA C LTDA", "amount": "2095,00"},
    ]
    lm = ColumnMapping(amount="valor", date="data", description="desc", document="doc")
    rm = ColumnMapping(amount="amount", date="date", description="memo", document="ref")
    rules = ReconciliationRules(amount_tolerance=0, date_tolerance_days=0, probable_match_threshold=0.65)
    result = reconcile(left, right, lm, rm, rules, "rec_test")
    assert result.pairs[0].status == MatchStatus.MATCH
    assert any(pair.status in {MatchStatus.DIVERGENCE, MatchStatus.PROBABLE_MATCH} for pair in result.pairs)
    assert result.summary.total_left == 2


def test_unmatched():
    left = [{"valor": 10}]
    right = [{"valor": 1000}]
    mapping = ColumnMapping(amount="valor")
    result = reconcile(left, right, mapping, mapping, ReconciliationRules(probable_match_threshold=0.9), "rec_test")
    assert any(pair.status == MatchStatus.UNMATCHED for pair in result.pairs)


def test_duplicate_detection():
    left = [{"doc": "A", "valor": 10}, {"doc": "A", "valor": 10}]
    right = [{"doc": "A", "valor": 10}]
    mapping = ColumnMapping(amount="valor", document="doc")
    result = reconcile(left, right, mapping, mapping, ReconciliationRules(), "rec_test")
    assert sum(pair.status == MatchStatus.DUPLICATE for pair in result.pairs) >= 2


def test_one_to_many_group_match():
    left = [{"data": "05/09/2026", "desc": "CLIENTE ALFA", "valor": "1000,00"}]
    right = [
        {"data": "05/09/2026", "desc": "CLIENTE ALFA PARCELA 1", "valor": "600,00"},
        {"data": "05/09/2026", "desc": "CLIENTE ALFA PARCELA 2", "valor": "400,00"},
    ]
    mapping = ColumnMapping(amount="valor", date="data", description="desc")
    rules = ReconciliationRules(auto_approve_threshold=0.9, group_match_threshold=0.8)
    result = reconcile(left, right, mapping, mapping, rules, "rec_group_1n")
    group = next(pair for pair in result.pairs if pair.match_cardinality == MatchCardinality.ONE_TO_MANY)
    assert group.status == MatchStatus.MATCH
    assert group.left_indices == [0]
    assert group.right_indices == [0, 1]
    assert group.amount_difference == 0
    assert result.summary.one_to_many == 1
    assert result.summary.reconciled_right_rows == 2


def test_many_to_one_group_match():
    left = [
        {"data": "05/09/2026", "desc": "REPASSE BETA ITEM 1", "valor": "700,00"},
        {"data": "05/09/2026", "desc": "REPASSE BETA ITEM 2", "valor": "300,00"},
    ]
    right = [{"data": "05/09/2026", "desc": "REPASSE BETA", "valor": "1000,00"}]
    mapping = ColumnMapping(amount="valor", date="data", description="desc")
    rules = ReconciliationRules(auto_approve_threshold=0.9, group_match_threshold=0.8)
    result = reconcile(left, right, mapping, mapping, rules, "rec_group_n1")
    group = next(pair for pair in result.pairs if pair.match_cardinality == MatchCardinality.MANY_TO_ONE)
    assert group.status == MatchStatus.MATCH
    assert group.left_indices == [0, 1]
    assert group.right_indices == [0]
    assert result.summary.many_to_one == 1
    assert result.summary.reconciled_left_rows == 2
    assert result.summary.match_rate == 1.0


def test_group_matching_can_be_disabled():
    left = [{"valor": 1000}]
    right = [{"valor": 600}, {"valor": 400}]
    mapping = ColumnMapping(amount="valor")
    rules = ReconciliationRules(group_matching_enabled=False, probable_match_threshold=0.9)
    result = reconcile(left, right, mapping, mapping, rules, "rec_no_groups")
    assert all(pair.match_cardinality == MatchCardinality.ONE_TO_ONE for pair in result.pairs)
    assert result.summary.grouped_matches == 0


def test_group_rows_are_not_reused():
    left = [{"valor": 1000}, {"valor": 1000}]
    right = [{"valor": 600}, {"valor": 400}]
    mapping = ColumnMapping(amount="valor")
    rules = ReconciliationRules(group_match_threshold=0.8, auto_approve_threshold=0.9)
    result = reconcile(left, right, mapping, mapping, rules, "rec_no_reuse")
    grouped = [pair for pair in result.pairs if pair.match_cardinality == MatchCardinality.ONE_TO_MANY]
    assert len(grouped) == 1
    assert grouped[0].right_indices == [0, 1]
    assert sum(pair.status == MatchStatus.UNMATCHED for pair in result.pairs) == 1

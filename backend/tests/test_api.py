from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def upload(label: str, content: str):
    response = client.post("/datasets/upload", data={"label": label}, files={"file": (f"{label}.csv", content.encode(), "text/csv")})
    assert response.status_code == 201
    return response.json()


def test_full_reconciliation_flow():
    left = upload("ERP", "id;data;cliente;valor\n1001;04/09/2026;Empresa A;1250,00\n1002;05/09/2026;Empresa C;2100,00\n")
    right = upload("BANCO", "referencia;data;descricao;valor\n1001;04/09/2026;EMPRESA A PIX;1250,00\n1002;05/09/2026;EMPRESA C LTDA;2095,00\n")
    payload = {
        "left_dataset_id": left["dataset_id"], "right_dataset_id": right["dataset_id"],
        "left_mapping": {"amount": "valor", "date": "data", "description": "cliente", "document": "id"},
        "right_mapping": {"amount": "valor", "date": "data", "description": "descricao", "document": "referencia"},
        "rules": {"amount_tolerance": 0, "date_tolerance_days": 0, "description_similarity": 0.8, "require_document_exact": False, "auto_approve_threshold": 0.9, "probable_match_threshold": 0.65},
    }
    response = client.post("/reconciliations", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["summary"]["total_left"] == 2
    assert body["summary"]["reconciliation_id"].startswith("rec_")

    candidate = next((pair for pair in body["pairs"] if pair["status"] in {"PROBABLE_MATCH", "DIVERGENCE"}), None)
    assert candidate is not None
    previous_match_rate = body["summary"]["match_rate"]
    decision = client.post(
        f'/reconciliations/{body["summary"]["reconciliation_id"]}/pairs/{candidate["pair_id"]}/decision',
        json={"decision": "approve"},
    )
    assert decision.status_code == 200
    approved = next(pair for pair in decision.json()["pairs"] if pair["pair_id"] == candidate["pair_id"])
    assert approved["status"] == "APPROVED"
    assert decision.json()["summary"]["match_rate"] >= previous_match_rate

    export = client.get(f'/reconciliations/{body["summary"]["reconciliation_id"]}/export.csv')
    assert export.status_code == 200
    assert "pair_id,status,match_cardinality,left_indices,right_indices,confidence" in export.text


def test_group_matching_through_api():
    left = upload("ERP_GROUP", "data;cliente;valor\n05/09/2026;Cliente Alfa;1000,00\n")
    right = upload("BANCO_GROUP", "data;descricao;valor\n05/09/2026;Cliente Alfa P1;600,00\n05/09/2026;Cliente Alfa P2;400,00\n")
    payload = {
        "left_dataset_id": left["dataset_id"],
        "right_dataset_id": right["dataset_id"],
        "left_mapping": {"amount": "valor", "date": "data", "description": "cliente"},
        "right_mapping": {"amount": "valor", "date": "data", "description": "descricao"},
        "rules": {"group_matching_enabled": True, "max_group_size": 3, "group_match_threshold": 0.8, "auto_approve_threshold": 0.9},
    }
    response = client.post("/reconciliations", json=payload)
    assert response.status_code == 201
    body = response.json()
    group = next(pair for pair in body["pairs"] if pair["match_cardinality"] == "1:N")
    assert group["right_indices"] == [0, 1]
    assert body["summary"]["grouped_matches"] == 1
    assert body["summary"]["reconciled_right_rows"] == 2


def test_health_exposes_group_matching_capability():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "0.3.0"
    assert response.json()["group_matching"] == "1:N,N:1"
    assert response.json()["templates"] == "persistent"


def test_template_save_apply_update_and_delete():
    left = upload("ERP_TEMPLATE", "id;data;cliente;valor\n1;05/09/2026;Cliente A;100,00\n")
    right = upload("BANK_TEMPLATE", "referencia;data;descricao;valor\n1;05/09/2026;Cliente A;100,00\n")
    template_payload = {
        "name": "ERP x Banco",
        "description": "Fechamento mensal",
        "left_mapping": {"amount": "valor", "date": "data", "description": "cliente", "document": "id"},
        "right_mapping": {"amount": "valor", "date": "data", "description": "descricao", "document": "referencia"},
        "rules": {"amount_tolerance": 2, "date_tolerance_days": 1, "group_matching_enabled": True},
        "left_columns": left["columns"],
        "right_columns": right["columns"],
    }
    created = client.post("/templates", json=template_payload)
    assert created.status_code == 201
    template = created.json()
    assert template["template_id"].startswith("tpl_")
    assert template["rules"]["amount_tolerance"] == 2

    listed = client.get("/templates")
    assert listed.status_code == 200
    assert any(item["template_id"] == template["template_id"] for item in listed.json())

    applied = client.post(
        f'/templates/{template["template_id"]}/apply',
        json={"left_dataset_id": left["dataset_id"], "right_dataset_id": right["dataset_id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["compatible"] is True

    template_payload["name"] = "ERP x Banco Atualizado"
    updated = client.put(f'/templates/{template["template_id"]}', json=template_payload)
    assert updated.status_code == 200
    assert updated.json()["name"] == "ERP x Banco Atualizado"

    deleted = client.delete(f'/templates/{template["template_id"]}')
    assert deleted.status_code == 204
    assert client.get(f'/templates/{template["template_id"]}').status_code == 404


def test_template_apply_detects_missing_columns():
    left = upload("ERP_TEMPLATE_MISSING", "data;valor\n05/09/2026;100,00\n")
    right = upload("BANK_TEMPLATE_MISSING", "data;valor\n05/09/2026;100,00\n")
    created = client.post(
        "/templates",
        json={
            "name": "Template incompatível",
            "left_mapping": {"amount": "valor", "date": "data", "description": "cliente"},
            "right_mapping": {"amount": "valor", "date": "data", "description": "descricao"},
            "rules": {},
        },
    )
    assert created.status_code == 201
    template_id = created.json()["template_id"]
    applied = client.post(
        f"/templates/{template_id}/apply",
        json={"left_dataset_id": left["dataset_id"], "right_dataset_id": right["dataset_id"]},
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["compatible"] is False
    assert body["missing_left_columns"] == ["cliente"]
    assert body["missing_right_columns"] == ["descricao"]

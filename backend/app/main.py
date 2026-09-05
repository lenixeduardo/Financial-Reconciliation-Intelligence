from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .engine import reconcile, refresh_summary
from .ingest import parse_table, suggest_mapping
from .models import DatasetSummary, ManualDecision, MatchStatus, ReconciliationCreate, ReconciliationResult
from .models import (
    ReconciliationTemplate,
    ReconciliationTemplateCreate,
    TemplateApplication,
    TemplateApplyRequest,
)
from .storage import Storage


DB_PATH = Path(os.getenv("FRI_DB_PATH", "./data/reconciliation.db"))
MAX_UPLOAD_MB = int(os.getenv("FRI_MAX_UPLOAD_MB", "20"))
storage = Storage(DB_PATH)

app = FastAPI(title="Financial Reconciliation Intelligence", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("FRI_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "engine": "deterministic",
        "version": "0.3.0",
        "group_matching": "1:N,N:1",
        "templates": "persistent",
    }


@app.post("/datasets/upload", response_model=DatasetSummary, status_code=201)
async def upload_dataset(file: UploadFile = File(...), label: str = Form("Base")) -> DatasetSummary:
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Arquivo excede {MAX_UPLOAD_MB} MB")
    try:
        columns, rows = parse_table(file.filename or "dataset.csv", data)
    except ValueError as exc:
        raise HTTPException(415, str(exc)) from exc
    if not rows:
        raise HTTPException(422, "A base não possui registros")
    dataset_id = f"ds_{uuid4().hex[:12]}"
    storage.save_dataset(dataset_id, label, file.filename or "dataset", rows, columns)
    return DatasetSummary(dataset_id=dataset_id, label=label, filename=file.filename or "dataset", rows=len(rows), columns=columns, preview=rows[:5], suggested_mapping=suggest_mapping(columns))


@app.get("/templates", response_model=list[ReconciliationTemplate])
def list_templates() -> list[ReconciliationTemplate]:
    return [ReconciliationTemplate.model_validate(item) for item in storage.list_templates()]


@app.post("/templates", response_model=ReconciliationTemplate, status_code=201)
def create_template(payload: ReconciliationTemplateCreate) -> ReconciliationTemplate:
    template_id = f"tpl_{uuid4().hex[:12]}"
    item = storage.save_template(template_id, payload.model_dump(mode="json"))
    return ReconciliationTemplate.model_validate(item)


@app.get("/templates/{template_id}", response_model=ReconciliationTemplate)
def get_template(template_id: str) -> ReconciliationTemplate:
    item = storage.get_template(template_id)
    if not item:
        raise HTTPException(404, "Template não encontrado")
    return ReconciliationTemplate.model_validate(item)


@app.put("/templates/{template_id}", response_model=ReconciliationTemplate)
def update_template(template_id: str, payload: ReconciliationTemplateCreate) -> ReconciliationTemplate:
    if not storage.get_template(template_id):
        raise HTTPException(404, "Template não encontrado")
    item = storage.save_template(template_id, payload.model_dump(mode="json"))
    return ReconciliationTemplate.model_validate(item)


@app.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str) -> None:
    if not storage.delete_template(template_id):
        raise HTTPException(404, "Template não encontrado")


@app.post("/templates/{template_id}/apply", response_model=TemplateApplication)
def apply_template(template_id: str, payload: TemplateApplyRequest) -> TemplateApplication:
    item = storage.get_template(template_id)
    if not item:
        raise HTTPException(404, "Template não encontrado")
    left = storage.get_dataset(payload.left_dataset_id)
    right = storage.get_dataset(payload.right_dataset_id)
    if not left or not right:
        raise HTTPException(404, "Uma das bases não foi encontrada")

    template = ReconciliationTemplate.model_validate(item)
    left_required = [
        column for column in template.left_mapping.model_dump().values() if column
    ]
    right_required = [
        column for column in template.right_mapping.model_dump().values() if column
    ]
    missing_left = sorted({column for column in left_required if column not in left["columns"]})
    missing_right = sorted({column for column in right_required if column not in right["columns"]})
    return TemplateApplication(
        template=template,
        compatible=not missing_left and not missing_right,
        missing_left_columns=missing_left,
        missing_right_columns=missing_right,
    )


@app.post("/reconciliations", response_model=ReconciliationResult, status_code=201)
def create_reconciliation(payload: ReconciliationCreate) -> ReconciliationResult:
    left = storage.get_dataset(payload.left_dataset_id)
    right = storage.get_dataset(payload.right_dataset_id)
    if not left or not right:
        raise HTTPException(404, "Uma das bases não foi encontrada")
    rid = f"rec_{uuid4().hex[:12]}"
    result = reconcile(left["rows"], right["rows"], payload.left_mapping, payload.right_mapping, payload.rules, rid)
    storage.save_reconciliation(rid, payload.model_dump(), result.model_dump(mode="json"))
    return result


@app.get("/reconciliations/{reconciliation_id}", response_model=ReconciliationResult)
def get_reconciliation(reconciliation_id: str) -> ReconciliationResult:
    item = storage.get_reconciliation(reconciliation_id)
    if not item:
        raise HTTPException(404, "Conciliação não encontrada")
    return ReconciliationResult.model_validate(item["result"])


@app.post("/reconciliations/{reconciliation_id}/pairs/{pair_id}/decision", response_model=ReconciliationResult)
def decide_pair(reconciliation_id: str, pair_id: str, decision: ManualDecision) -> ReconciliationResult:
    item = storage.get_reconciliation(reconciliation_id)
    if not item:
        raise HTTPException(404, "Conciliação não encontrada")
    result = ReconciliationResult.model_validate(item["result"])
    found = False
    for pair in result.pairs:
        if pair.pair_id == pair_id:
            pair.status = MatchStatus.APPROVED if decision.decision == "approve" else MatchStatus.REJECTED
            found = True
            break
    if not found:
        raise HTTPException(404, "Par não encontrado")
    result = refresh_summary(result)
    storage.save_reconciliation(reconciliation_id, item["payload"], result.model_dump(mode="json"))
    return result


@app.get("/reconciliations/{reconciliation_id}/export.csv")
def export_reconciliation(reconciliation_id: str) -> StreamingResponse:
    item = storage.get_reconciliation(reconciliation_id)
    if not item:
        raise HTTPException(404, "Conciliação não encontrada")
    result = ReconciliationResult.model_validate(item["result"])
    output = io.StringIO()
    fields = ["pair_id", "status", "match_cardinality", "left_indices", "right_indices", "confidence", "amount_left", "amount_right", "amount_difference", "date_left", "date_right", "description_left", "description_right", "document_left", "document_right", "reasons"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for p in result.pairs:
        row = p.model_dump()
        writer.writerow({
            k: "; ".join(str(v) for v in row[k]) if k in {"reasons", "left_indices", "right_indices"} else row.get(k)
            for k in fields
        })
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={reconciliation_id}.csv"})

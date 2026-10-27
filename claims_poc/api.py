"""FastAPI service.  Run:  uvicorn claims_poc.api:create_app --factory --reload"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Callable, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import Repo
from .llm import LLM
from .service import resume_graph, run_claim, run_claim_graph
from .stores import make_audit_store, make_blob_store

MAX_FILES, MAX_BYTES = 15, 10 * 1024 * 1024
ALLOWED = (".txt", ".pdf", ".png", ".jpg", ".jpeg")


class ReviewIn(BaseModel):
    reviewer: str
    final_decision: Literal["APPROVE", "PARTIAL_APPROVE", "QUERY_MORE_INFO", "REJECT"]
    comment: str = ""


def create_app(repo: Repo | None = None, blobs=None, audits=None,
               llm_factory: Callable[[], LLM] | None = None, seed_demo: bool | None = None,
               engine: str | None = None) -> FastAPI:
    repo = repo or Repo()
    repo.init()
    blobs = blobs or make_blob_store()
    audits = audits or make_audit_store()
    llm_factory = llm_factory or (lambda: LLM())
    engine = (engine or os.getenv("ENGINE", "graph")).lower()      # graph = LangGraph, plain = simple orchestrator
    saver = None
    if engine == "graph":
        from langgraph.checkpoint.memory import InMemorySaver
        saver = InMemorySaver()   # demo only: lost on restart. Use a persistent checkpointer in production.

    seed = os.getenv("SEED_DEMO_DATA", "true").lower() == "true" if seed_demo is None else seed_demo
    data = Path(__file__).resolve().parents[1] / "data"
    if seed and (data / "policy.json").exists():
        repo.seed_policy(json.loads((data / "policy.json").read_text()))
        repo.seed_history(json.loads((data / "claims_history.json").read_text()))

    def check_key(x_api_key: str | None = Header(default=None)):
        expected = os.getenv("API_KEY")  # simple POC protection; use Entra ID in production
        if expected and x_api_key != expected:
            raise HTTPException(401, "Invalid or missing X-API-Key")

    app = FastAPI(title="Mediclaim Desk API", dependencies=[Depends(check_key)])
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/meta")
    def meta():
        """What this server is running on. The UI shows it, so a demo viewer can see mock versus real model."""
        provider = os.getenv("LLM_PROVIDER", "openai")
        model = {"azure": os.getenv("AZURE_OPENAI_DEPLOYMENT"), "openai": os.getenv("OPENAI_MODEL")}.get(provider)
        return {"engine": "langgraph" if engine == "graph" else "plain", "llm_provider": provider, "model": model,
                "sql": "azure-sql" if os.getenv("AZURE_SQL_CONN_STR") else "sqlite",
                "audit_store": "cosmos-db" if os.getenv("COSMOS_ENDPOINT") else "local-files"}

    @app.post("/claims", status_code=202)
    async def submit_claim(background: BackgroundTasks, policy_number: str = Form(...),
                           files: list[UploadFile] = File(...)):
        if repo.get_policy(policy_number) is None:
            raise HTTPException(404, f"Unknown policy {policy_number}")
        if not files or len(files) > MAX_FILES:
            raise HTTPException(422, f"Send 1 to {MAX_FILES} files")
        claim_id = f"CLM-{uuid.uuid4().hex[:10].upper()}"
        saved = []
        for f in files:
            name = Path(f.filename or "file").name  # strip any path parts
            if not name.lower().endswith(ALLOWED):
                raise HTTPException(422, f"Unsupported file type: {name}")
            data = await f.read()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, f"{name} is larger than 10 MB")
            saved.append((name, blobs.put(claim_id, name, data)))
        repo.create_claim(claim_id, policy_number, saved)
        if engine == "graph":
            background.add_task(run_claim_graph, claim_id, repo, blobs, audits, llm_factory(), saver)
        else:
            background.add_task(run_claim, claim_id, repo, blobs, audits, llm_factory())
        return {"claim_id": claim_id, "status": "RECEIVED"}

    @app.get("/claims")
    def list_claims(limit: int = 50):
        return repo.list_claims(min(max(limit, 1), 200))

    @app.get("/claims/{claim_id}")
    def get_claim(claim_id: str):
        c = repo.get_claim(claim_id)
        if not c:
            raise HTTPException(404, "Claim not found")
        return c

    @app.get("/claims/{claim_id}/audit")
    def get_audit(claim_id: str):
        doc = audits.get(claim_id)
        if not doc:
            raise HTTPException(404, "No audit trail yet")
        return doc

    @app.post("/claims/{claim_id}/review")
    def review(claim_id: str, body: ReviewIn):
        c = repo.get_claim(claim_id)
        if not c:
            raise HTTPException(404, "Claim not found")
        if c["status"] != "AWAITING_REVIEW":
            raise HTTPException(409, f"Claim is {c['status']}, not awaiting review")
        repo.add_review(claim_id, body.reviewer, body.final_decision, body.comment)
        if engine == "graph":   # also let the paused LangGraph run finish; the SQL record above is the source of truth
            try:
                resume_graph(claim_id, repo, audits, saver, body.reviewer, body.final_decision, body.comment)
            except Exception:
                logging.getLogger(__name__).exception("Could not resume graph for %s", claim_id)
        return repo.get_claim(claim_id)

    return app

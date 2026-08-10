#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Deep Agents Worker Service (FastAPI) for NemoClaw.
"""
import logging
import secrets
from typing import Literal, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from config import load_config
from task_store import TaskStore
from worker import TOOL_PROFILES, WorkerPool

config = load_config()

logging.basicConfig(
    level=getattr(logging, config.get("log_level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deepagents-worker-service")

app = FastAPI(
    title="DeepAgents Worker Service",
    description="Queue-based long-horizon task delegation for NemoClaw OpenClaw sandboxes",
    version="1.0.0",
)

task_store = TaskStore(state_dir=config["state_dir"], ttl_hours=config["task_ttl_hours"])
worker_pool = WorkerPool(task_store=task_store, config=config)


@app.on_event("startup")
def on_startup():
    if not (config.get("service_secret") or "").strip():
        raise RuntimeError("DEEPAGENTS_SERVICE_SECRET is required")
    logger.info("Starting DeepAgents Worker Service...")
    worker_pool.start()


@app.on_event("shutdown")
def on_shutdown():
    logger.info("Stopping DeepAgents Worker Service...")
    worker_pool.stop()


async def verify_auth(authorization: Optional[str] = Header(None)):
    expected_secret = (config.get("service_secret") or "").strip()
    if not expected_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker authentication is not configured")
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")
    if not secrets.compare_digest(token.strip(), expected_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authorization token")


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    prompt: str = Field(..., min_length=1, max_length=32768, description="High-level research prompt")
    model: str = Field(config.get("default_model", "gpt-5"), description="Target LLM model name")
    mode: Literal["live", "mock"] = Field("live", description="Execution mode")
    timeout_ms: int = Field(600000, ge=30000, le=86400000, description="Task timeout in milliseconds")
    depth: Literal["shallow", "standard", "deep"] = Field("standard", description="Execution depth preset")
    rubric: Optional[str] = Field(None, min_length=1, max_length=8192, description="Optional quality rubric text")
    max_retries: int = Field(config.get("default_task_max_retries", 2), ge=0, le=10, description="Task-level retry count")
    tool_profile: Optional[Literal["research", "minimal"]] = Field(None, description="Read-only tool profile override")
    tool_call_budget: Optional[int] = Field(None, ge=1, le=1000, description="Optional per-task tool call budget override")


@app.get("/health")
@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "service": "deepagents-worker",
        "version": "1.0.0",
        "worker_concurrency": config["worker_concurrency"],
        "ttl_hours": config["task_ttl_hours"],
    }


@app.post("/v1/tasks", dependencies=[Depends(verify_auth)])
async def create_task(req: CreateTaskRequest):
    profile = (req.tool_profile or config.get("default_tool_profile") or "research").strip().lower()
    if profile not in TOOL_PROFILES:
        raise HTTPException(status_code=400, detail=f"Invalid tool_profile '{profile}'. Must be one of: {', '.join(sorted(TOOL_PROFILES))}")
    try:
        task = task_store.enqueue(
            prompt=req.prompt,
            model=req.model,
            mode=req.mode,
            timeout_ms=req.timeout_ms,
            depth=req.depth,
            rubric=req.rubric,
            max_retries=max(req.max_retries, 0),
            tool_profile=profile,
            tool_call_budget=req.tool_call_budget,
        )
        return {
            "task_id": task["task_id"],
            "status": task["status"],
            "prompt": task["prompt"],
            "depth": task["depth"],
            "created_at": task["created_at"],
        }
    except Exception as exc:
        logger.error("Error creating task: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(verify_auth)])
async def get_task(task_id: str):
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@app.get("/v1/tasks", dependencies=[Depends(verify_auth)])
async def list_tasks(limit: int = Query(50, ge=1, le=200)):
    return {"tasks": task_store.list_tasks(limit=limit)}


@app.delete("/v1/tasks/{task_id}", dependencies=[Depends(verify_auth)])
async def cancel_task(task_id: str):
    prior_status = task_store.mark_cancelling(task_id)
    if prior_status is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found or already finished")
    if prior_status == "running":
        worker_pool.request_cancel(task_id)
        return {"task_id": task_id, "status": "cancelling"}
    if prior_status == "queued":
        return {"task_id": task_id, "status": "cancelled"}
    task = task_store.get_task(task_id)
    if task:
        return {"task_id": task_id, "status": task["status"]}
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found or already finished")


if __name__ == "__main__":
    host = config.get("host", "0.0.0.0")
    port = config.get("port", 9050)
    logger.info("Starting DeepAgents Worker Service on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level=config.get("log_level", "info").lower())

"""CRUD endpoints for ETL pipeline designs."""
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from starlette.concurrency import run_in_threadpool

from app.db.firestore_client import FirestoreClient, get_firestore_client
from app.schemas.api_models import (
    CreateDesignRequest,
    CreateDesignResponse,
    DeleteDesignResponse,
    DesignResponse,
    ListDesignsResponse,
    PaginationMeta,
    UpdateDesignRequest,
)
from app.schemas.design import Design, DesignStatus
from app.schemas.guardrail import GuardrailStatus
from app.services.architect_agent import ArchitectAgent, get_architect_agent
from app.services.audit_trail_service import AuditTrailService, get_audit_trail_service
from app.services.logging_service import LoggingService, get_logging_service
from app.services.metrics_service import MetricsService, get_metrics_service
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/designs", tags=["designs"])


async def _generate_design(
    design_id: str,
    client: FirestoreClient,
    agent: ArchitectAgent,
    audit_trail: AuditTrailService,
    metrics_service: MetricsService,
    logging_service: LoggingService,
) -> None:
    """Background task: run the full ArchitectAgent pipeline and persist the result.

    Also records structured decision/constraint-violation logs, an
    immutable audit trail entry, and per-design metrics once generation
    completes.
    """
    start_time = time.monotonic()
    try:
        await client.update_design(design_id, {"status": DesignStatus.IN_PROGRESS.value})
        logger.info("Design generation started for %s", design_id)

        design = await client.get_design(design_id)
        cost_before = api_cost_tracker.summary()

        result = await run_in_threadpool(agent.design, design.requirements, None, design.project_name)

        cost_after = api_cost_tracker.summary()
        calls_delta = sum(
            after["calls"] - cost_before.get(provider, {}).get("calls", 0) for provider, after in cost_after.items()
        )
        cost_delta = sum(
            after["cost_usd"] - cost_before.get(provider, {}).get("cost_usd", 0)
            for provider, after in cost_after.items()
        )
        generation_seconds = time.monotonic() - start_time

        logging_service.log_decision(
            f"Design generation completed with status={result.status.value}",
            design_id=design_id,
            architecture_path=(result.output.decision_matrix or {}).get("selected_path") if result.output else None,
            final_score=(result.output.decision_matrix or {}).get("final_score") if result.output else None,
        )
        for guardrail_result in result.validation_results:
            if guardrail_result.status in (GuardrailStatus.ESCALATE, GuardrailStatus.STOP):
                logging_service.log_constraint_violation(
                    guardrail_result.message,
                    guardrail_source=guardrail_result.source,
                    severity=guardrail_result.severity.value,
                    design_id=design_id,
                )

        updated = await client.update_design(
            design_id,
            {
                "status": result.status.value,
                "output": result.output.model_dump(mode="json") if result.output else None,
                "validation_results": [r.model_dump(mode="json") for r in result.validation_results],
                "generation_seconds": generation_seconds,
                "api_calls_count": calls_delta,
                "api_cost_usd": round(cost_delta, 6),
            },
        )

        try:
            metrics_service.compute_and_store_design_metrics(updated)
        except Exception:
            logger.exception("Failed to store metrics for design '%s' (generation itself succeeded)", design_id)

        try:
            audit_trail.record_event(
                design_id,
                "design_completed",
                details={"status": result.status.value, "generation_seconds": generation_seconds},
            )
        except Exception:
            logger.exception("Failed to record audit trail event for design '%s'", design_id)

        logger.info(
            "Design generation completed for %s in %.1fs (status=%s)", design_id, generation_seconds, result.status.value
        )
    except Exception:
        logger.exception("Design generation failed for %s", design_id)
        await client.update_design(design_id, {"status": DesignStatus.FAILED.value})


@router.post(
    "/create",
    response_model=CreateDesignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new design request and start background generation",
)
async def create_design(
    request: CreateDesignRequest,
    background_tasks: BackgroundTasks,
    client: FirestoreClient = Depends(get_firestore_client),
    agent: ArchitectAgent = Depends(get_architect_agent),
    audit_trail: AuditTrailService = Depends(get_audit_trail_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    logging_service: LoggingService = Depends(get_logging_service),
) -> CreateDesignResponse:
    """Create a design record and kick off asynchronous generation.

    Returns immediately with a minimal payload; poll
    ``GET /api/designs/{design_id}`` for the completed output.
    """
    design = Design(
        project_name=request.project_name,
        requirements=request.requirements,
        status=DesignStatus.PENDING,
    )
    created = await client.create_design(design)

    logging_service.log_user_interaction(
        f"Design '{created.project_name}' requested", action="design_create", design_id=created.id
    )
    try:
        audit_trail.record_event(created.id, "design_created", details={"project_name": created.project_name})
    except Exception:
        logger.exception("Failed to record audit trail event for design '%s'", created.id)

    background_tasks.add_task(_generate_design, created.id, client, agent, audit_trail, metrics_service, logging_service)

    return CreateDesignResponse(
        id=created.id,
        project_name=created.project_name,
        status=created.status,
        created_at=created.created_at,
    )


@router.get(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Get a design by id",
)
async def get_design(
    design_id: str,
    client: FirestoreClient = Depends(get_firestore_client),
) -> DesignResponse:
    """Return the complete design, including output if generation has finished."""
    design = await client.get_design(design_id)
    return DesignResponse.from_design(design)


@router.get(
    "",
    response_model=ListDesignsResponse,
    summary="List designs with pagination and filters",
)
async def list_designs(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum number of records to return"),
    status_filter: Optional[DesignStatus] = Query(
        default=None, alias="status", description="Filter by design status"
    ),
    date_from: Optional[datetime] = Query(
        default=None, description="Only include designs created on/after this timestamp"
    ),
    date_to: Optional[datetime] = Query(
        default=None, description="Only include designs created on/before this timestamp"
    ),
    client: FirestoreClient = Depends(get_firestore_client),
) -> ListDesignsResponse:
    """List non-deleted designs, most recently created first."""
    filters = {}
    if status_filter is not None:
        filters["status"] = status_filter.value
    if date_from is not None:
        filters["date_from"] = date_from
    if date_to is not None:
        filters["date_to"] = date_to

    designs = await client.list_designs(skip=skip, limit=limit, filters=filters)

    return ListDesignsResponse(
        items=[DesignResponse.from_design(d) for d in designs],
        pagination=PaginationMeta(skip=skip, limit=limit, total=len(designs)),
    )


@router.patch(
    "/{design_id}",
    response_model=DesignResponse,
    summary="Update a design (e.g. to record a new iteration)",
)
async def update_design(
    design_id: str,
    request: UpdateDesignRequest,
    client: FirestoreClient = Depends(get_firestore_client),
) -> DesignResponse:
    """Apply a partial update to an existing design."""
    updates = request.model_dump(exclude_unset=True, mode="json")
    updated = await client.update_design(design_id, updates)
    return DesignResponse.from_design(updated)


@router.delete(
    "/{design_id}",
    response_model=DeleteDesignResponse,
    summary="Soft-delete a design",
)
async def delete_design(
    design_id: str,
    client: FirestoreClient = Depends(get_firestore_client),
) -> DeleteDesignResponse:
    """Mark a design as deleted without removing its Firestore document."""
    await client.delete_design(design_id)
    return DeleteDesignResponse(id=design_id, status=DesignStatus.DELETED)

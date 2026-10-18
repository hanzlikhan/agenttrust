"""Tool registry: declare versioned tools with typed argument contracts (M04)."""

from fastapi import APIRouter, Depends, Request
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AppError, require_admin, require_api_key
from ..models import ApiKey, Project, ToolDefinition
from ..schemas import (
    ToolDefinitionResponse,
    ToolListResponse,
    ToolRegisterRequest,
)
from ..util import utcnow

router = APIRouter(tags=["tools"])

_VALID_RISK_CLASSES = {"read_only", "write", "high_impact"}


def _public(tool: ToolDefinition) -> ToolDefinitionResponse:
    return ToolDefinitionResponse(
        id=tool.id,
        project_id=tool.project_id,
        slug=tool.slug,
        version=tool.version,
        schema_json=tool.schema_json,
        risk_class=tool.risk_class,
        created_at=tool.created_at,
    )


@router.post("/tools", status_code=201, response_model=ToolDefinitionResponse)
def register_tool(
    payload: ToolRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> ToolDefinitionResponse:
    """Register a new version of a tool's argument contract.

    Versions are append-only: re-registering an existing (slug, version) is a
    409, never an overwrite.
    """
    project = db.get(Project, payload.project_id)
    if project is None:
        raise AppError(
            "project_not_found", f"Project {payload.project_id} does not exist.", 404
        )
    if payload.risk_class not in _VALID_RISK_CLASSES:
        raise AppError(
            "invalid_risk_class",
            f"risk_class must be one of {sorted(_VALID_RISK_CLASSES)}.",
            422,
        )
    try:
        validator_for(payload.schema_json).check_schema(payload.schema_json)
    except SchemaError as exc:
        raise AppError(
            "invalid_tool_schema",
            f"schema_json is not a valid JSON Schema: {exc.message}",
            422,
        ) from exc

    duplicate = (
        db.query(ToolDefinition)
        .filter(
            ToolDefinition.project_id == project.id,
            ToolDefinition.slug == payload.slug,
            ToolDefinition.version == payload.version,
        )
        .first()
    )
    if duplicate is not None:
        raise AppError(
            "tool_version_exists",
            f"Tool '{payload.slug}' version {payload.version} is already registered.",
            409,
        )

    tool = ToolDefinition(
        project_id=project.id,
        slug=payload.slug,
        version=payload.version,
        schema_json=payload.schema_json,
        risk_class=payload.risk_class,
        created_at=utcnow(),
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return _public(tool)


@router.get("/tools", response_model=ToolListResponse)
def list_tools(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> ToolListResponse:
    """List this project's registered tool versions, newest first."""
    tools = (
        db.query(ToolDefinition)
        .filter(ToolDefinition.project_id == key.project_id)
        .order_by(ToolDefinition.slug, desc(ToolDefinition.version))
        .all()
    )
    return ToolListResponse(tools=[_public(tool) for tool in tools])

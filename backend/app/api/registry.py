"""API endpoints for Node Registry discovery and inspection."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from app.registry.legacy import LEGACY_NODE_TYPES, LegacyNodeType
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.registry import NodeDefinition, RegistryCatalogResponse

router = APIRouter(prefix="/api/registry", tags=["Node Registry"])


def get_registry() -> NodeRegistry:
    """Dependency provider for NodeRegistry."""
    return get_default_registry()


@router.get("/categories", response_model=List[str])
async def list_categories() -> List[str]:
    """List all available node categories."""
    return get_registry().get_categories()


@router.get("/nodes", response_model=RegistryCatalogResponse)
async def list_nodes(
    category: Optional[str] = Query(None, description="Optional category filter (e.g. 'ai_agent', 'tools', 'logic')"),
) -> RegistryCatalogResponse:
    """List registered node definitions, optionally filtered by category."""
    registry = get_registry()
    if category:
        nodes = registry.list_by_category(category)
    else:
        nodes = registry.list_all()

    return RegistryCatalogResponse(
        total_nodes=len(nodes),
        categories=registry.get_categories(),
        nodes=nodes,
    )


@router.get("/nodes/{node_type}", response_model=NodeDefinition)
async def get_node_definition(node_type: str) -> NodeDefinition:
    """Retrieve detailed definition and port semantics for a specific node type."""
    node = get_registry().get(node_type)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node type '{node_type}' not found in registry.",
        )
    return node


@router.get("/legacy", response_model=List[LegacyNodeType])
async def list_legacy_node_types() -> List[LegacyNodeType]:
    """Node types removed from the library. Used to label preserved legacy nodes in old workflows.

    These are identification data only; none of them is executable or mapped to another operation.
    """
    return list(LEGACY_NODE_TYPES.values())

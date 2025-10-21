from fastmcp import FastMCP, Context
from typing import Annotated, Literal
from pydantic import Field
import anyio
from anyio import to_thread
from dataclasses import dataclass


mcp: FastMCP = FastMCP(
    name="Odoo Fast MCP",
    instructions="""
        This server provides tools to interact with Odoo.
    """,
)


@dataclass
class Person:
    name: str
    age: int
    email: str


def sync_heavy():
    import time

    time.sleep(3)
    for i in range(5):
        print(f"Working... {i}")


@mcp.tool(
    annotations={
        "title": "person profile retrieval",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def get_person_profile(user_id: str) -> Person:
    """Get a user's profile information."""
    await to_thread.run_sync(sync_heavy)
    return Person(name="Alice", age=30, email="alice@example.com")


@mcp.tool
async def greet(name: str) -> str:
    return f"Hello, {name}!"


@mcp.tool
async def process_image(
    image_url: Annotated[str, Field(description="URL of the image to process")],
    resize: Annotated[bool, Field(description="Whether to resize the image")] = False,
    width: Annotated[int, Field(description="Target width in pixels", ge=1, le=2000)] = 800,
    format: Annotated[
        Literal["jpeg", "png", "webp"], Field(description="Output image format")
    ] = "jpeg",
) -> dict:
    """Process an image with optional resizing."""
    # Dummy implementation for illustration
    return {
        "original_url": image_url,
        "processed_url": f"{image_url}?format={format}&width={width if resize else 'original'}",
        "resized": resize,
        "format": format,
    }


@mcp.resource("data://config")
async def get_config() -> dict:
    """Provides application configuration as JSON."""
    return {
        "theme": "dark",
        "version": "1.2.0",
        "features": ["tools", "resources"],
    }


@mcp.resource("resource://{name}/details")
async def get_details(name: str, ctx: Context) -> dict:
    """Get details for a specific name."""
    return {"name": name, "accessed_at": ctx.request_id}


# api://users?version=2&limit=50 → version=2, limit=50, offset=0
@mcp.resource("api://{endpoint}{?version,limit,offset}")
def call_api(endpoint: str, version: int = 1, limit: int = 10, offset: int = 0) -> dict:
    """Call API endpoint with pagination."""
    return {
        "endpoint": endpoint,
        "version": version,
        "limit": limit,
        "offset": offset,
    }


@mcp.resource("users://{user_id}/profile")
async def get_user_profile(user_id: int) -> dict:
    """Retrieves a user's profile by ID."""
    # The {user_id} in the URI is extracted and passed to this function
    return {"id": user_id, "name": f"User {user_id}", "status": "active"}


@mcp.prompt
async def analyze_data(data_points: list[float]) -> str:
    """Creates a prompt asking for analysis of numerical data."""
    formatted_data = ", ".join(str(point) for point in data_points)
    return f"Please analyze these data points: {formatted_data}"


async def _main_async() -> None:
    await mcp.run_async(transport="http", host="127.0.0.1", port=8000)


def main_cli() -> None:
    anyio.run(func=_main_async)


if __name__ == "__main__":
    main_cli()

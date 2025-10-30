from fastmcp import FastMCP, Context
from fastmcp.prompts.prompt import Message, PromptResult
from typing import Annotated, Literal
from pydantic import Field
import anyio
from anyio import to_thread
from dataclasses import dataclass
import argparse
import logging
import sys
from functools import partial
from fastmcp.server.elicitation import (
    AcceptedElicitation, 
    DeclinedElicitation, 
    CancelledElicitation,
)
from fastmcp.server.middleware import Middleware, MiddlewareContext
# TODO: check existing middleware and possibly reuse here fastmcp.server.middleware 

logger = logging.getLogger(__name__)


class LoggingMiddleware(Middleware):
    """Middleware that logs all MCP operations."""
    
    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages."""
        print(f"Processing {context.method} from {context.source}")
        
        result = await call_next(context)
        
        print(f"Completed {context.method}")
        return result


mcp: FastMCP = FastMCP(
    name="Odoo Fast MCP",
    instructions="""
        This server provides tools to interact with Odoo.
    """,
)
mcp.add_middleware(LoggingMiddleware())

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


@mcp.tool
async def pattern_example(ctx: Context) -> str:
    result = await ctx.elicit("Approve this action?", response_type=None)
    if result == DeclinedElicitation():
        return "Action not approved"
    result = await ctx.elicit("Enter your response:", response_type=str)
    match result:
        case AcceptedElicitation(data=information):
            return f"Hello {information}!"
        case DeclinedElicitation():
            return "No name provided"
        case CancelledElicitation():
            return "Operation cancelled"


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
async def generate_code_request(language: str, task_description: str) -> PromptResult:
    """Generates a user message requesting code generation."""
    content = f"Write a {language} function that performs the following task: {task_description}"

    return Message(content)


@mcp.prompt
async def analyze_data(numbers: list[int], metadata: dict[str, str], threshold: float) -> str:
    """Analyze numerical data."""
    avg = sum(numbers) / len(numbers)
    return f"Average: {avg}, above threshold: {avg > threshold}"


@mcp.prompt
async def roleplay_scenario(character: str, situation: str) -> PromptResult:
    """Sets up a roleplaying scenario with initial messages."""
    return [
        Message(f"Let's roleplay. You are {character}. The situation is: {situation}"),
        Message("Okay, I understand. I am ready. What happens next?", role="assistant"),
    ]


# @mcp.prompt
# async def data_based_prompt(data_id: str) -> str:
#     """Generates a prompt based on data that needs to be fetched."""
#     # In a real scenario, you might fetch data from a database or API
#     async with aiohttp.ClientSession() as session:
#         async with session.get(f"https://api.example.com/data/{data_id}") as response:
#             data = await response.json()
#             return f"Analyze this data: {data['content']}"


async def _main_async(config_path: str = ".env") -> None:
    # await mcp.run_async(transport="http", host="127.0.0.1", port=8080)
    await mcp.run_async(transport="stdio")


def main_cli() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="Run the Odoo Fast MCP server.")
    parser.add_argument("--config", help="Path to configuration file")
    args = parser.parse_args()
    anyio.run(partial(_main_async, config_path=args.config))


if __name__ == "__main__":
    main_cli()

# Code Style and Conventions

## Python Version
- Minimum Python 3.10 (uses `X | Y` union syntax, `Annotated` type hints)

## Type Hints
- All function parameters and return types should have type hints
- Use `Annotated` with `pydantic.Field` for MCP tool parameters
- Use `dict[str, Any]` not `Dict[str, Any]`
- Use `list[int]` not `List[int]`
- Use `X | None` not `Optional[X]`

## Naming Conventions
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: Not used, but would be `UPPER_SNAKE_CASE`
- MCP tools: `snake_case` (same as function names)

## Docstrings
- Use triple-quoted docstrings for all public functions
- Include description, parameter explanations, and examples where helpful
- MCP tools use docstrings as tool descriptions shown to LLMs

## Code Organization
- Sections separated by comment blocks:
  ```python
  # =============================================================================
  # Section Name
  # =============================================================================
  ```
- Group related functionality together
- Imports ordered: standard library, third-party, local

## Ruff Configuration
- Line length: 100 characters
- Target Python: 3.10
- Many linting rules enabled (see pyproject.toml)
- Key ignores: E501 (line-too-long), some style rules

## Async Patterns
- Use `async def` for MCP tools
- Use `to_thread.run_sync()` for blocking OdooRPC calls
- Global connection manager instance (not per-request)

## Error Handling
- Raise `ConnectionError` for connection issues
- Let OdooRPC exceptions propagate (they contain useful info)
- Use descriptive error messages

## MCP Tool Annotations
- Always include annotations dict with hints:
  - `title`: Human-readable title
  - `readOnlyHint`: True for read operations
  - `destructiveHint`: True for delete operations
  - `idempotentHint`: True if repeated calls have same effect
  - `openWorldHint`: True if tool accesses external systems

import asyncio
from fastmcp import Client


client = Client("http://localhost:8000/mcp")


async def call_tool(name: str):
    async with client:
        result = await client.call_tool("get_person_profile", {"user_id": "123"})
        print()
        print(result)
        print("Person profile retrieval completed.")
        print()

        result = await client.call_tool("greet", {"name": name})
        print()
        print(result)
        print("Tool call completed.")
        print()
        result = await client.call_tool(
            "process_image",
            {
                "image_url": "http://example.com/image.jpg",
                "resize": True,
                "width": 600,
                "format": "png",
            },
        )
        print()
        print(result)
        print("Image processing completed.")
        print()


asyncio.run(call_tool("Ford"))

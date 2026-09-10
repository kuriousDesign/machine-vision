import asyncio

from stream_only_config import build_stream_only_config
from stream_only_service import StreamOnlyService


async def main():
    cfg = build_stream_only_config()
    print(
        f"[STREAM_ONLY] Starting camera {cfg.camera_id} ({cfg.camera_name}) "
        f"searchType={cfg.connection_search_type.value} streamPort={cfg.stream_port}"
    )
    service = StreamOnlyService(cfg)
    await service.run()


asyncio.run(main())
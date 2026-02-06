import asyncio

from loguru import logger

from api.osc import OscServer


class AppController:
    """Minimal controller for OSC server management"""

    def __init__(self, config: dict):
        logger.info("Initialize App Controller...")
        self.config = config
        self.osc_server = OscServer(config)

    async def run(self):
        """Start OSC server and run event loop"""
        logger.info("Starting OSC server")
        await self.osc_server.start_server()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Error: {e}")

try:
    from api.agent import router as agent_router
except ImportError:
    from backend.api.agent import router as agent_router

__all__ = ["agent_router"]

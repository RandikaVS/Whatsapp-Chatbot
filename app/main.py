from typing import Union
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# from .api.webhook import router as webhook
from .api.webhooks import router as webhooks_router
from .api.auth.auth import router as auth_router
from app.api.agent import router as agent_router
from app.api.auth.tenant_auth import router as tenant_auth_router

def create_app():

    app = FastAPI(title="Chatbot API", description="A simple chatbot API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],

    )

    app.include_router(webhooks_router)
    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(tenant_auth_router)

    @app.get("/")
    async def health():
        return {"status": "Chatbot API is running"}
    

    return app

app = create_app()
"""Pydantic request/response schemas."""
from typing import List, Optional

from pydantic import BaseModel


class ItemIn(BaseModel):
    name: str
    type: str
    color: str = ""
    season: str = ""
    formality: str = ""
    material: str = ""
    notes: str = ""


class Item(ItemIn):
    id: int


class LoginIn(BaseModel):
    username: str
    password: str


class OutfitRequest(BaseModel):
    occasion: str = "casual day out"
    item_ids: Optional[List[int]] = None


class ShoppingRequest(BaseModel):
    goal: str = "build a versatile everyday wardrobe"


class EvaluateRequest(BaseModel):
    kind: str  # "outfit" | "shopping"
    conversation_id: str = ""
    parent_generation_id: str = ""
    context: dict = {}
    output: dict = {}


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class OutfitChatRequest(BaseModel):
    conversation_id: str = ""  # "" => server mints one on the first turn
    occasion: str = "casual day out"  # the new user message / intent
    history: List[ChatMessage] = []  # prior turns (not including this message)
    item_ids: Optional[List[int]] = None
    run_research: bool = True


class ShoppingChatRequest(BaseModel):
    conversation_id: str = ""
    goal: str = "build a versatile everyday wardrobe"
    history: List[ChatMessage] = []
    run_research: bool = True

import asyncio
import json
import re
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import ChatSession, Note, Notebook, Source
from open_notebook.exceptions import (
    NotFoundError,
)
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


# Request/Response models
class CreateSessionRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to create session for")
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatMessage(BaseModel):
    id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (human|ai)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")


class ChatSessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    notebook_id: Optional[str] = Field(None, description="Notebook ID")
    created: str = Field(..., description="Creation timestamp")
    updated: str = Field(..., description="Last update timestamp")
    message_count: Optional[int] = Field(
        None, description="Number of messages in session"
    )
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )


class ChatSessionWithMessagesResponse(ChatSessionResponse):
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Session messages"
    )


class ExecuteChatRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID")
    message: str = Field(..., description="User message content")
    context: Dict[str, Any] = Field(
        ..., description="Chat context with sources and notes"
    )
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )


class ExecuteChatResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    messages: List[ChatMessage] = Field(..., description="Updated message list")
    added_sources: List[str] = Field(default_factory=list, description="Source titles added by RAG")


class BuildContextRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID")
    context_config: Dict[str, Any] = Field(..., description="Context configuration")


class BuildContextResponse(BaseModel):
    context: Dict[str, Any] = Field(..., description="Built context data")
    token_count: int = Field(..., description="Estimated token count")
    char_count: int = Field(..., description="Character count")


class SuccessResponse(BaseModel):
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


@router.get("/chat/sessions", response_model=List[ChatSessionResponse])
async def get_sessions(notebook_id: str = Query(..., description="Notebook ID")):
    """Get all chat sessions for a notebook."""
    try:
        # Get notebook to verify it exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Get sessions for this notebook
        sessions_list = await notebook.get_chat_sessions()

        results = []
        for session in sessions_list:
            session_id = str(session.id)

            # Get message count from LangGraph state
            msg_count = await get_session_message_count(chat_graph, session_id)

            results.append(
                ChatSessionResponse(
                    id=session.id or "",
                    title=session.title or "Untitled Session",
                    notebook_id=notebook_id,
                    created=str(session.created),
                    updated=str(session.updated),
                    message_count=msg_count,
                    model_override=getattr(session, "model_override", None),
                )
            )

        return results
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching chat sessions: {str(e)}"
        )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create a new chat session."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Create new session
        session = ChatSession(
            title=request.title
            or f"Chat Session {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
        )
        await session.save()

        # Relate session to notebook
        await session.relate_to_notebook(request.notebook_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=request.notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
            model_override=session.model_override,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating chat session: {str(e)}"
        )


@router.get(
    "/chat/sessions/{session_id}", response_model=ChatSessionWithMessagesResponse
)
async def get_session(session_id: str):
    """Get a specific session with its messages."""
    try:
        # Get session
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get session state from LangGraph to retrieve messages
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Extract messages from state
        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(
                    ChatMessage(
                        id=getattr(msg, "id", f"msg_{len(messages)}"),
                        type=msg.type if hasattr(msg, "type") else "unknown",
                        content=msg.content if hasattr(msg, "content") else str(msg),
                        timestamp=None,  # LangChain messages don't have timestamps by default
                    )
                )

        # Find notebook_id (we need to query the relationship)
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )

        notebook_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )

        notebook_id = notebook_query[0]["out"] if notebook_query else None

        if not notebook_id:
            # This might be an old session created before API migration
            logger.warning(
                f"No notebook relationship found for session {session_id} - may be an orphaned session"
            )

        return ChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error fetching session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching session: {str(e)}")


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest):
    """Update session title."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        update_data = request.model_dump(exclude_unset=True)

        if "title" in update_data:
            session.title = update_data["title"]

        if "model_override" in update_data:
            session.model_override = update_data["model_override"]

        await session.save()

        # Find notebook_id
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        notebook_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )
        notebook_id = notebook_query[0]["out"] if notebook_query else None

        # Get message count from LangGraph state
        msg_count = await get_session_message_count(chat_graph, full_session_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
            model_override=session.model_override,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.delete("/chat/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(session_id: str):
    """Delete a chat session."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        await session.delete()

        return SuccessResponse(success=True, message="Session deleted successfully")
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@router.post("/chat/execute", response_model=ExecuteChatResponse)
async def execute_chat(request: ExecuteChatRequest):
    """Execute a chat request and get AI response."""
    try:
        # Verify session exists
        # Ensure session_id has proper table prefix
        full_session_id = (
            request.session_id
            if request.session_id.startswith("chat_session:")
            else f"chat_session:{request.session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Determine model override (per-request override takes precedence over session-level)
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        # Get current state
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Prepare state for execution
        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = request.context
        state_values["model_override"] = model_override

        # Add user message to state
        from langchain_core.messages import HumanMessage

        user_message = HumanMessage(content=request.message)
        state_values["messages"].append(user_message)

        # ── Resolve notebook_id for tool injection ───────────────────────────────
        # notebook_id is a graph relationship, not a direct attribute of ChatSession.
        # Pass it into the LangGraph configurable so the search_documents tool can use it.
        nb_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )
        notebook_id = nb_query[0]["out"] if nb_query else None
        # ── end notebook_id resolution ─────────────────────────────────────────

        # Execute chat graph
        result = chat_graph.invoke(
            input=state_values,  # type: ignore[arg-type]
            config=RunnableConfig(
                configurable={
                    "thread_id": full_session_id,
                    "model_id": model_override,
                    "notebook_id": notebook_id,
                }
            ),
        )

        # Update session timestamp
        await session.save()

        # Collect titles of any sources added via the search_documents tool
        added_sources: List[str] = []
        from langchain_core.messages import ToolMessage
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage) and msg.name == "search_documents":
                # Extract source titles from the tool output header line
                for line in (msg.content or "").splitlines():
                    if line.startswith("## "):
                        title = line[3:].split(" [")[0].strip()
                        if title:
                            added_sources.append(title)

        # Convert messages to response format
        messages: list[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(
                ChatMessage(
                    id=getattr(msg, "id", f"msg_{len(messages)}"),
                    type=msg.type if hasattr(msg, "type") else "unknown",
                    content=msg.content if hasattr(msg, "content") else str(msg),
                    timestamp=None,
                )
            )

        return ExecuteChatResponse(session_id=request.session_id, messages=messages, added_sources=added_sources)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        # Log detailed error with context for debugging
        logger.error(
            f"Error executing chat: {str(e)}\n"
            f"  Session ID: {request.session_id}\n"
            f"  Model override: {request.model_override}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error executing chat: {str(e)}")


@router.post("/chat/context", response_model=BuildContextResponse)
async def build_context(request: BuildContextRequest):
    """Build context for a notebook based on context configuration."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        context_data: dict[str, list[dict[str, str]]] = {"sources": [], "notes": []}
        total_content = ""

        # Process context configuration if provided
        if request.context_config:
            # Process sources
            for source_id, status in request.context_config.get("sources", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_source_id = (
                        source_id
                        if source_id.startswith("source:")
                        else f"source:{source_id}"
                    )

                    try:
                        source = await Source.get(full_source_id)
                    except Exception:
                        continue

                    if "insights" in status:
                        source_context = await source.get_context(context_size="short")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                    elif "full content" in status:
                        source_context = await source.get_context(context_size="long")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source_id}: {str(e)}")
                    continue

            # Process notes
            for note_id, status in request.context_config.get("notes", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
                    full_note_id = (
                        note_id if note_id.startswith("note:") else f"note:{note_id}"
                    )
                    note = await Note.get(full_note_id)
                    if not note:
                        continue

                    if "full content" in status:
                        note_context = note.get_context(context_size="long")
                        context_data["notes"].append(note_context)
                        total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note_id}: {str(e)}")
                    continue
        else:
            # Default behavior - include all sources and notes with short context
            sources = await notebook.get_sources()
            for source in sources:
                try:
                    source_context = await source.get_context(context_size="short")
                    context_data["sources"].append(source_context)
                    total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source.id}: {str(e)}")
                    continue

            notes = await notebook.get_notes()
            for note in notes:
                try:
                    note_context = note.get_context(context_size="short")
                    context_data["notes"].append(note_context)
                    total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note.id}: {str(e)}")
                    continue

        # Calculate character and token counts
        char_count = len(total_content)
        # Use token count utility if available
        try:
            from open_notebook.utils import token_count

            estimated_tokens = token_count(total_content) if total_content else 0
        except ImportError:
            # Fallback to simple estimation
            estimated_tokens = char_count // 4

        return BuildContextResponse(
            context=context_data, token_count=estimated_tokens, char_count=char_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building context: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error building context: {str(e)}")


# ── Thinking-tag filter helpers ──────────────────────────────────────────────

class _ThinkFilterResult:
    """Result from _ThinkFilter.feed() containing both visible and thinking text."""

    __slots__ = ("visible", "thinking")

    def __init__(self, visible: str = "", thinking: str = "") -> None:
        self.visible = visible
        self.thinking = thinking


class _ThinkFilter:
    """Stateful filter that separates <think>...</think> blocks from a token stream."""

    def __init__(self) -> None:
        self._buf = ""          # partial tag accumulation buffer
        self._in_think = False  # are we inside a <think> block?

    def feed(self, text: str) -> _ThinkFilterResult:
        """Feed *text* and return visible and thinking portions separately."""
        out_parts: list[str] = []
        think_parts: list[str] = []
        for ch in text:
            if self._in_think:
                self._buf += ch
                if self._buf.endswith("</think>"):
                    # Emit accumulated thinking content (without the closing tag)
                    think_parts.append(self._buf[: -len("</think>")])
                    self._in_think = False
                    self._buf = ""
            else:
                self._buf += ch
                # Check for opening tag
                if "<think>" in self._buf:
                    pre, _, rest = self._buf.partition("<think>")
                    out_parts.append(pre)
                    self._in_think = True
                    self._buf = rest  # rest is content inside <think>
                elif not "<think>".startswith(self._buf.lstrip()):
                    # No partial match for a tag – safe to flush
                    out_parts.append(self._buf)
                    self._buf = ""
        # If we're inside a <think> block, emit buffered thinking so far
        if self._in_think and self._buf:
            think_parts.append(self._buf)
            self._buf = ""
        return _ThinkFilterResult(
            visible="".join(out_parts),
            thinking="".join(think_parts),
        )

    def flush(self) -> _ThinkFilterResult:
        """Flush any remaining buffer content (call after the stream ends)."""
        if self._in_think:
            thinking = self._buf
            self._buf = ""
            self._in_think = False
            return _ThinkFilterResult(thinking=thinking)
        result = self._buf
        self._buf = ""
        return _ThinkFilterResult(visible=result)


async def _stream_chat_tokens(
    request: ExecuteChatRequest,
) -> AsyncGenerator[str, None]:
    """Core generator that streams chat tokens as SSE events."""
    from ai_prompter import Prompter

    from open_notebook.graphs.chat import tools as chat_tools
    from open_notebook.utils import clean_thinking_content

    # ── 1. Validate session ──────────────────────────────────────────────────
    full_session_id = (
        request.session_id
        if request.session_id.startswith("chat_session:")
        else f"chat_session:{request.session_id}"
    )
    try:
        session = await ChatSession.get(full_session_id)
    except Exception:
        session = None
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'error': 'Session not found'})}\n\n"
        return

    model_override = (
        request.model_override
        if request.model_override is not None
        else getattr(session, "model_override", None)
    )

    # ── 2. Load existing LangGraph message history ───────────────────────────
    config = RunnableConfig(configurable={"thread_id": full_session_id})
    try:
        current_state = await asyncio.to_thread(chat_graph.get_state, config)
    except Exception:
        current_state = None

    existing_messages: list = []
    context_obj = None
    if current_state and current_state.values:
        existing_messages = list(current_state.values.get("messages", []))
        context_obj = current_state.values.get("context")

    human_message = HumanMessage(content=request.message)
    all_messages = existing_messages + [human_message]

    # ── 3. Provision model ───────────────────────────────────────────────────
    try:
        model = await provision_langchain_model(
            str(all_messages), model_override, "chat", max_tokens=8192
        )
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': f'Model unavailable: {e}'})}\n\n"
        return

    # Enable structured reasoning for Ollama thinking models so that
    # thinking content arrives in additional_kwargs["reasoning_content"]
    # instead of being mixed into the main content as <think> tags.
    try:
        from langchain_ollama import ChatOllama

        if isinstance(model, ChatOllama):
            model.reasoning = True
    except ImportError:
        pass

    # ── 4. Build prompt ──────────────────────────────────────────────────────
    # Resolve notebook_id for tool injection (same pattern as /chat/execute)
    nb_query = await repo_query(
        "SELECT out FROM refers_to WHERE in = $session_id",
        {"session_id": ensure_record_id(full_session_id)},
    )
    notebook_id = nb_query[0]["out"] if nb_query else None

    tool_config = RunnableConfig(
        configurable={
            "thread_id": full_session_id,
            "model_id": model_override,
            "notebook_id": notebook_id,
        }
    )

    state_for_prompt = {
        "messages": all_messages,
        "context": request.context or context_obj,
        "model_override": model_override,
    }
    try:
        system_prompt = Prompter(prompt_template="chat/system").render(data=state_for_prompt)  # type: ignore[arg-type]
    except Exception:
        system_prompt = "You are a helpful assistant."

    payload = [SystemMessage(content=system_prompt)] + all_messages

    # ── 5. Bind tools and stream model response ──────────────────────────────
    full_content = ""
    think_filter = _ThinkFilter()
    tool_call_chunks: list = []
    accumulated_tool_calls: dict = {}  # index → tool call accumulator

    # Try to bind tools; fall back gracefully if the model does not support it
    try:
        model_with_tools = model.bind_tools(chat_tools)
    except Exception:
        model_with_tools = model

    try:
        async for chunk in model_with_tools.astream(payload):
            # Collect tool call chunks (structured output from the model)
            if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                for tc_chunk in chunk.tool_call_chunks:
                    idx = tc_chunk.get("index", 0) if isinstance(tc_chunk, dict) else getattr(tc_chunk, "index", 0)
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {"name": "", "id": "", "args": ""}
                    tc = accumulated_tool_calls[idx]
                    name = (tc_chunk.get("name", "") if isinstance(tc_chunk, dict) else getattr(tc_chunk, "name", "")) or ""
                    id_ = (tc_chunk.get("id", "") if isinstance(tc_chunk, dict) else getattr(tc_chunk, "id", "")) or ""
                    args = (tc_chunk.get("args", "") if isinstance(tc_chunk, dict) else getattr(tc_chunk, "args", "")) or ""
                    if name:
                        tc["name"] = name
                    if id_:
                        tc["id"] = id_
                    tc["args"] += args

            raw: str = ""
            c = chunk.content
            if isinstance(c, str):
                raw = c
            elif isinstance(c, list):
                raw = "".join(
                    item.get("text", "") for item in c if isinstance(item, dict)
                )

            # Check for structured reasoning_content (Ollama with reasoning=True)
            reasoning_content = ""
            if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                reasoning_content = chunk.additional_kwargs.get(
                    "reasoning_content", ""
                )
            if reasoning_content:
                yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning_content})}\n\n"

            if not raw:
                continue
            full_content += raw
            # Also handle <think> tags in content (fallback for reasoning=None)
            result = think_filter.feed(raw)
            if result.thinking:
                yield f"data: {json.dumps({'type': 'thinking', 'content': result.thinking})}\n\n"
            if result.visible:
                yield f"data: {json.dumps({'type': 'token', 'content': result.visible})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        return

    # Flush any buffered tail content
    tail = think_filter.flush()
    if tail.thinking:
        yield f"data: {json.dumps({'type': 'thinking', 'content': tail.thinking})}\n\n"
    if tail.visible:
        yield f"data: {json.dumps({'type': 'token', 'content': tail.visible})}\n\n"

    # Clean full content (removes any thinking tags that leaked through)
    full_content = clean_thinking_content(full_content)

    # ── 5b. Execute tool calls if the model requested any ────────────────────
    messages_to_persist = [human_message]
    added_sources: list[str] = []

    if accumulated_tool_calls:
        import json as _json

        from langchain_core.messages import ToolMessage

        # Build the AIMessage that contains the tool calls
        tool_calls_list = []
        for tc in accumulated_tool_calls.values():
            try:
                parsed_args = _json.loads(tc["args"]) if tc["args"] else {}
            except Exception:
                parsed_args = {}
            tool_calls_list.append({
                "name": tc["name"],
                "id": tc["id"] or tc["name"],
                "args": parsed_args,
            })

        ai_tool_call_message = AIMessage(content="", tool_calls=tool_calls_list)
        messages_to_persist.append(ai_tool_call_message)

        # Build a map of tool name → callable
        tool_map = {t.name: t for t in chat_tools}

        tool_results: list = []
        for tc in tool_calls_list:
            tool_name = tc["name"]
            yield f"data: {json.dumps({'type': 'tool_executing', 'tool': tool_name})}\n\n"

            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                tool_output = f"Gereedschap '{tool_name}' niet gevonden."
            else:
                try:
                    tool_output = await asyncio.to_thread(
                        tool_fn.invoke, tc["args"], tool_config
                    )
                except Exception as tool_err:
                    tool_output = f"Fout bij uitvoeren van {tool_name}: {tool_err}"

            tool_msg = ToolMessage(
                content=str(tool_output),
                tool_call_id=tc["id"] or tool_name,
                name=tool_name,
            )
            messages_to_persist.append(tool_msg)
            tool_results.append(tool_msg)

            # Track added sources for the done event
            if tool_name == "summarize_transcription_to_word":
                added_sources.append(str(tool_output))

        # ── Follow-up model call with tool results ────────────────────────
        follow_up_payload = payload + [ai_tool_call_message] + tool_results
        follow_up_content = ""
        follow_up_think = _ThinkFilter()

        try:
            async for chunk in model.astream(follow_up_payload):
                raw = ""
                c = chunk.content
                if isinstance(c, str):
                    raw = c
                elif isinstance(c, list):
                    raw = "".join(
                        item.get("text", "") for item in c if isinstance(item, dict)
                    )

                reasoning_content = ""
                if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                    reasoning_content = chunk.additional_kwargs.get("reasoning_content", "")
                if reasoning_content:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning_content})}\n\n"

                if not raw:
                    continue
                follow_up_content += raw
                res = follow_up_think.feed(raw)
                if res.thinking:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': res.thinking})}\n\n"
                if res.visible:
                    yield f"data: {json.dumps({'type': 'token', 'content': res.visible})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            return

        tail2 = follow_up_think.flush()
        if tail2.thinking:
            yield f"data: {json.dumps({'type': 'thinking', 'content': tail2.thinking})}\n\n"
        if tail2.visible:
            yield f"data: {json.dumps({'type': 'token', 'content': tail2.visible})}\n\n"

        follow_up_content = clean_thinking_content(follow_up_content)
        messages_to_persist.append(AIMessage(content=follow_up_content))
    else:
        messages_to_persist.append(AIMessage(content=full_content))

    # ── 6. Persist to LangGraph state ────────────────────────────────────────
    try:
        await asyncio.to_thread(
            chat_graph.update_state,
            config,
            {"messages": messages_to_persist},
        )
    except Exception as e:
        logger.warning(f"Failed to persist chat state after streaming: {e}")

    await session.save()

    # ── 7. Return final message list ─────────────────────────────────────────
    try:
        final_state = await asyncio.to_thread(chat_graph.get_state, config)
        messages_out: list[dict] = []
        if final_state and final_state.values:
            for i, msg in enumerate(final_state.values.get("messages", [])):
                content = msg.content if hasattr(msg, "content") else str(msg)
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                messages_out.append(
                    {
                        "id": getattr(msg, "id", f"msg_{i}"),
                        "type": msg.type if hasattr(msg, "type") else "unknown",
                        "content": content,
                        "timestamp": None,
                    }
                )
    except Exception as e:
        logger.warning(f"Error fetching final state: {e}")
        messages_out = []

    yield f"data: {json.dumps({'type': 'done', 'messages': messages_out, 'added_sources': added_sources})}\n\n"


@router.post("/chat/stream")
async def stream_chat(request: ExecuteChatRequest):
    """Stream a chat response token-by-token via Server-Sent Events."""
    return StreamingResponse(
        _stream_chat_tokens(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

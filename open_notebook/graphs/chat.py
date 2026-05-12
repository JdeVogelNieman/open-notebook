import asyncio
import concurrent.futures
import sqlite3
from typing import Annotated, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[str]
    context_config: Optional[dict]
    model_override: Optional[str]


def _run_async(coro):
    """Run an async coroutine safely from a synchronous context.

    Works even when a FastAPI event loop is already running, by spawning a
    fresh event loop in a dedicated worker thread.
    """
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(runner).result()


@tool
def search_documents(query: str, config: RunnableConfig) -> str:
    """Search the Digilab knowledge base for relevant documents.

    Use this tool whenever the user asks to find, search for, retrieve or look up
    documents, reports ("verslag", "notulen"), agendas, or any topic that might
    exist in the knowledge base. The tool adds found documents as Sources to the
    active notebook and returns their content so you can answer immediately.

    Args:
        query: A search query in any language (Dutch or English).

    Returns:
        Formatted document content with source IDs you can use for citations.
    """
    notebook_id: Optional[str] = (config.get("configurable") or {}).get("notebook_id")

    async def _search():
        from collections import defaultdict

        from api.rag_integration_service import get_rag_service
        from api.routers.sources import create_source_from_rag_result
        from open_notebook.domain.content_settings import ContentSettings

        if not notebook_id:
            return "Zoeken niet mogelijk: geen notebook context beschikbaar."

        settings = await ContentSettings.get_instance()
        if not settings or not settings.rag_enabled:
            return "RAG zoeken is niet ingeschakeld in de instellingen."

        rag_url = settings.rag_service_url or "http://host.docker.internal:3001"
        rag_svc = get_rag_service(rag_url)

        if not await rag_svc.is_available():
            return "De documentzoekdienst is momenteel niet bereikbaar."

        max_results = settings.rag_max_results or 3
        rag_results = await rag_svc.query(query, limit=max_results * 3)

        if not rag_results:
            return f"Geen relevante documenten gevonden voor '{query}'."

        # Group chunks by source file
        file_chunks: dict = defaultdict(list)
        for result in rag_results:
            if result.file_path:
                file_chunks[result.file_path].append(result)

        output_parts = [f"Gevonden documenten voor zoekopdracht: '{query}'\n"]

        for file_path, chunks in list(file_chunks.items())[:max_results]:
            result = await create_source_from_rag_result(file_path, chunks, notebook_id)
            if result is None:
                continue

            title, source_id = result

            # Build content from the RAG chunks (available immediately,
            # before async file processing has completed).
            content = "\n".join(
                c.text for c in sorted(chunks, key=lambda x: x.chunk_index) if c.text
            )
            output_parts.append(f"## {title} [{source_id}]\n\n{content}\n")

        if len(output_parts) == 1:
            return f"Geen nieuwe documenten gevonden voor '{query}'."

        return "\n".join(output_parts)

    return _run_async(_search())


tools = [search_documents]


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        system_prompt = Prompter(prompt_template="chat/system").render(data=state)  # type: ignore[arg-type]
        payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])
        model_id = config.get("configurable", {}).get("model_id") or state.get(
            "model_override"
        )

        # Handle async model provisioning from sync context
        def run_in_new_loop():
            """Run the async function in a new event loop"""
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(
                    provision_langchain_model(
                        str(payload), model_id, "chat", max_tokens=8192
                    )
                )
            finally:
                new_loop.close()
                asyncio.set_event_loop(None)

        try:
            # Try to get the current event loop
            asyncio.get_running_loop()
            # If we're in an event loop, run in a thread with a new loop
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                model = future.result()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run()
            model = asyncio.run(
                provision_langchain_model(
                    str(payload),
                    model_id,
                    "chat",
                    max_tokens=8192,
                )
            )

        # Bind tools when the model supports it; fall back gracefully if not.
        try:
            model_with_tools = model.bind_tools(tools)
            ai_message = model_with_tools.invoke(payload)
        except Exception:
            ai_message = model.invoke(payload)

        # Clean thinking content from AI response (e.g., <think>...</think> tags)
        content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(content)
        cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

        return {"messages": cleaned_message}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


def should_continue(state: ThreadState) -> str:
    """Route to tool execution or end based on whether the model made tool calls."""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if last_message and getattr(last_message, "tool_calls", None):
        return "tools"
    return END


conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
memory = SqliteSaver(conn)

agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_node("tools", ToolNode(tools))
agent_state.add_edge(START, "agent")
agent_state.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
agent_state.add_edge("tools", "agent")
graph = agent_state.compile(checkpointer=memory)

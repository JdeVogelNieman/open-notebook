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


@tool
def summarize_transcription_to_word(
    config: RunnableConfig,
    template_source_id: Optional[str] = None,
    source_ids: Optional[list] = None,
    existing_summary: Optional[str] = None,
) -> str:
    """Maak een Word-document met vergadernotulen vanuit transcriptieteksten in het notebook.

    Gebruik dit gereedschap wanneer de gebruiker vraagt om:
    - Een transcriptie om te zetten naar notulen
    - Een samenvatting te maken in Word-formaat
    - Een vergaderverslag te genereren

    Het gereedschap haalt automatisch transcriptieteksten en een Word-sjabloon op uit de bronnen van het notebook.
    Als het sjabloon onduidelijk is, geeft het gereedschap een vraag terug voor de gebruiker.

    Args:
        template_source_id: Optioneel. Bron-ID van de Word-sjabloon (.docx) als de gebruiker die heeft opgegeven.
        source_ids: Optioneel. Lijst van bron-IDs om als transcriptietekst te gebruiken. Als leeg, worden alle tekstbronnen gebruikt.
        existing_summary: Optioneel. Als de chatbot al een tekstsamenvatting heeft gemaakt in dit gesprek,
            geef die hier door. De eerste LLM-stap (transcriptie → JSON) wordt dan overgeslagen en
            de samenvatting wordt direct omgezet naar het vereiste JSON-formaat, wat sneller is.

    Returns:
        Bevestiging met het nieuwe bron-ID, of een verduidelijkingsvraag als het sjabloon onduidelijk is.
    """
    notebook_id: Optional[str] = (config.get("configurable") or {}).get("notebook_id")

    async def _run() -> str:
        import shutil

        from open_notebook.config import UPLOADS_FOLDER
        from open_notebook.domain.notebook import Asset, Notebook, Source

        if not notebook_id:
            return "Geen notebook beschikbaar. Kan geen notulen genereren."

        notebook = await Notebook.get(str(notebook_id))
        if not notebook:
            return "Notebook niet gevonden."

        all_sources = await notebook.get_sources()
        if not all_sources:
            return "Dit notebook heeft geen bronnen. Voeg eerst transcriptieteksten toe als bron."

        # Fetch full_text for each source to determine type
        transcription_sources = []
        template_sources = []

        for src in all_sources:
            asset = getattr(src, "asset", None)
            file_path = asset.file_path if asset else None
            is_docx = file_path and str(file_path).lower().endswith(".docx")

            if is_docx:
                template_sources.append(src)
            else:
                transcription_sources.append(src)

        # Resolve explicit template source override
        if template_source_id:
            full_tid = (
                template_source_id
                if template_source_id.startswith("source:")
                else f"source:{template_source_id}"
            )
            try:
                explicit_template = await Source.get(full_tid)
                asset = getattr(explicit_template, "asset", None)
                if not (asset and asset.file_path and str(asset.file_path).lower().endswith(".docx")):
                    return f"Bron '{template_source_id}' is geen Word-bestand (.docx). Geef een geldige Word-sjabloon op."
                selected_template = explicit_template
            except Exception:
                return f"Bron '{template_source_id}' kon niet worden gevonden."
        elif len(template_sources) == 1:
            selected_template = template_sources[0]
        elif len(template_sources) == 0:
            return (
                "Er is geen Word-sjabloon (.docx) gevonden in het notebook. "
                "Voeg een Word-sjabloon toe als bron en probeer het opnieuw."
            )
        else:
            names = ", ".join(
                f"'{s.title or s.id}'" for s in template_sources
            )
            return (
                f"Er zijn meerdere Word-sjablonen gevonden: {names}. "
                "Welk sjabloon wil je gebruiken? Noem de naam of het bron-ID."
            )

        # Filter transcription sources by explicit source_ids if given
        if source_ids:
            norm_ids = {
                sid if sid.startswith("source:") else f"source:{sid}"
                for sid in source_ids
            }
            transcription_sources = [s for s in transcription_sources if str(s.id) in norm_ids]

        # When existing_summary is provided we don't need source text
        combined_text = ""
        if not existing_summary:
            if not transcription_sources:
                return "Geen transcriptieteksten gevonden in het notebook. Voeg eerst transcriptieteksten toe als bron."

            texts = []
            for src in transcription_sources:
                try:
                    full_src = await Source.get(str(src.id))
                    if full_src and full_src.full_text:
                        texts.append(f"# {full_src.title or 'Bron'}\n\n{full_src.full_text}")
                except Exception:
                    pass

            if not texts:
                return "Geen transcriptietekst gevonden in de bronnen. Zorg dat de bronnen verwerkt zijn."

            combined_text = "\n\n---\n\n".join(texts)

        template_path = selected_template.asset.file_path  # type: ignore[union-attr]

        # Generate the Word document
        try:
            from api.transcription_to_word import main as generate_word

            output_path = generate_word(
                transcription_text=combined_text,
                template_word_path=template_path,
                output_dir=UPLOADS_FOLDER,
                existing_summary=existing_summary or None,
            )
        except Exception as e:
            return f"Fout bij het genereren van het Word-document: {e}"

        # Register the generated document as a new source
        try:
            import os
            output_filename = os.path.basename(output_path)
            new_source = Source(
                title=f"Notulen - {output_filename}",
                asset=Asset(file_path=output_path),
            )
            await new_source.save()
            await new_source.add_to_notebook(str(notebook_id))

            return (
                f"Het Word-document met notulen is aangemaakt en toegevoegd aan het notebook. "
                f"Bron-ID: [{new_source.id}]. "
                f"Bestandsnaam: {output_filename}."
            )
        except Exception as e:
            return f"Word-document gegenereerd ({output_path}), maar kon niet worden opgeslagen als bron: {e}"

    return _run_async(_run())


tools = [search_documents, summarize_transcription_to_word]


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

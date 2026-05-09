import warnings
# Suppress noisy LangChain/LangGraph deprecation warnings immediately
warnings.filterwarnings("ignore", message=".*allowed_objects.*will change.*")

import sys, os
import argparse
from pathlib import Path
from typing import List, Union

from langchain_core.messages import HumanMessage, AIMessage

from .agent import build_agent, extract_reply

def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="CLI for an Ollama ReAct agent with file-management tools."
    )
    parser.add_argument("-d", "--workdir", type=str, default="./",
                        help="Working directory for the agent (default: current directory).")
    parser.add_argument("-m", "--model", type=str, default="qwen3-coder:480b-cloud",
                        help="Ollama model name (default: qwen3-coder:480b-cloud).")
    parser.add_argument("-s", "--stream", action="store_true",
                        help="Enable token-by-token streaming output.")
    parser.add_argument("-H", "--history", action="store_true",
                        help="Maintain conversation history across turns.")
    parser.add_argument("-w", "--whatsapp", type=str, default=None,
                        help="Target WhatsApp number/JID. If not provided, WhatsApp tools are disabled.")
    parser.add_argument("-u", "--whatsapp-url", type=str, default="http://localhost:3000",
                        help="WhatsApp API base URL (default: http://localhost:3000).")
    parser.add_argument("-U", "--ollama-url", type=str, default=None,
                        help="Ollama API base URL.")
    parser.add_argument("-K", "--ollama-key", type=str, default=None,
                        help="Ollama API Key (if required).")
    parser.add_argument("-T", "--max-tool-output", type=int, default=60000,
                        help="Maximum character length for tool outputs (default: 60000).")
    parser.add_argument("-C", "--ollama-ctx", type=int, default=65536,
                        help="Ollama context window size (default: 65536).")
    parser.add_argument("-p", "--prompt", type=str, default=None,
                        help="Run a single prompt and exit.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress all logging and prefixes, displaying only the raw agent response.")
    args = parser.parse_args(argv)

    work_dir = Path(args.workdir).expanduser().resolve()
    model_name = args.model
    streaming = args.stream
    use_history = args.history
    whatsapp_jid = args.whatsapp
    whatsapp_url = args.whatsapp_url
    ollama_url = args.ollama_url
    ollama_key = args.ollama_key
    single_prompt = args.prompt
    max_tool_output = args.max_tool_output
    ollama_ctx = args.ollama_ctx
    quiet = args.quiet or (single_prompt is not None)
    
    os.environ["MAX_TOOL_OUTPUT"] = str(max_tool_output)

    if not quiet:
        print("="*50)
        print(f"[AI Agent] Initializing...")
        print(f" - Workdir:  {work_dir}")
        print(f" - Model:    {model_name}")
        print(f" - Stream:   {'ON' if streaming else 'OFF'}")
        print(f" - History:  {'ON' if use_history else 'OFF'}")
        print(f" - WhatsApp: {whatsapp_jid if whatsapp_jid else 'DISABLED'}")
        if whatsapp_jid:
            print(f" - WA URL:   {whatsapp_url}")
        print(f" - Ollama URL: {ollama_url if ollama_url else 'http://localhost:11434 (default)'}")
        print(f" - Max Tool Out: {max_tool_output}")
        print(f" - Ollama Ctx: {ollama_ctx}")
        if single_prompt:
            print(f" - Mode:     Single Prompt")
        print("="*50 + "\n")

    try:
        agent = build_agent(work_dir, model_name, streaming=streaming, 
                           whatsapp_jid=whatsapp_jid, whatsapp_url=whatsapp_url,
                           ollama_url=ollama_url, ollama_key=ollama_key,
                           ollama_ctx=ollama_ctx)
    except Exception as e:
        if not quiet:
            print(f"[Critical] Failed to initialize agent: {e}")
        else:
            print(e, file=sys.stderr)
        sys.exit(1)

    message_history: List[Union[HumanMessage, AIMessage]] = []

    def process_query(query: str):
        human_msg = HumanMessage(content=query)
        if use_history:
            message_history.append(human_msg)
            msgs_to_send = list(message_history)
        else:
            msgs_to_send = [human_msg]

        config = {"configurable": {"thread_id": "standalone_session"}}
        if streaming:
            if not quiet:
                print("Agent: ", end="", flush=True)
            try:
                full_reply = ""
                for event in agent.stream({"messages": msgs_to_send}, config=config):
                    # LangGraph events are dicts like {'agent': {'messages': [...]}} or {'tools': {...}}
                    for node_name, node_data in event.items():
                        if "messages" in node_data:
                            last_msg = node_data["messages"][-1]
                            if isinstance(last_msg, AIMessage) and last_msg.content:
                                print(last_msg.content, end="", flush=True)
                                full_reply += last_msg.content
                if not quiet:
                    print()
                if use_history:
                    message_history.append(AIMessage(content=full_reply))
                return True
            except Exception as exc:
                if not quiet:
                    print(f"\n[Error] Streaming failed: {exc}")
                else:
                    print(exc, file=sys.stderr)
                return False
        else:
            try:
                result = agent.invoke({"messages": msgs_to_send}, config=config)
                reply_text = extract_reply(result) or ("[No response received]" if not quiet else "")
                if not quiet:
                    print(f"Agent: {reply_text}\n")
                else:
                    print(reply_text.strip())
                if use_history:
                    message_history.append(AIMessage(content=reply_text))
                return True
            except Exception as exc:
                if not quiet:
                    print(f"[Error] Agent call failed: {exc}\n")
                else:
                    print(exc, file=sys.stderr)
                return False

    if single_prompt:
        if not process_query(single_prompt):
            sys.exit(1)
        return

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
                
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", "bye"}:
                print("Goodbye!")
                break

            process_query(user_input)
                    
    except KeyboardInterrupt:
        print("\n[Info] Interrupted by user. Exiting.")

if __name__ == "__main__":
    main()

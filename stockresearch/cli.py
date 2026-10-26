from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from .graph import run_research
from .hints import EXAMPLES, PROMPT, TICKER_HINTS


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="LangGraph stock research assistant (market data via yfinance)",
        epilog=TICKER_HINTS + "\n\nExamples:\n" + "\n".join(f"  {example}" for example in EXAMPLES),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("question", nargs="*", help="Research question; omit to enter interactive mode")
    args = parser.parse_args()
    if args.question:
        print(run_research(" ".join(args.question)).answer)
        return
    source = "mock data" if os.getenv("STOCK_PROVIDER", "").strip().lower() == "mock" else "Yahoo Finance via yfinance"
    print(f"Stock Research Assistant ({source}; type 'exit' to quit)\n")
    print(TICKER_HINTS)
    print("\nTry: " + " | ".join(EXAMPLES[:3]) + "\n")
    while True:
        try:
            question = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.casefold() in {"exit", "quit"}:
            break
        if not question:
            continue
        result = run_research(question)
        print(f"assistant> {result.answer}\n")


if __name__ == "__main__":
    main()

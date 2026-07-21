"""Command-line interface for the Flight Route Advisor."""

from __future__ import annotations

import argparse
import sys

from .advisor import FlightRouteAdvisor
from .graph import OptimizeBy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight-route-advisor",
        description="Find the best flight routes between airports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- search ----
    search = sub.add_parser("search", help="Find routes between two airports.")
    search.add_argument("origin", metavar="ORIGIN", help="Departure IATA code (e.g. JFK)")
    search.add_argument(
        "destination", metavar="DESTINATION", help="Arrival IATA code (e.g. SIN)"
    )
    search.add_argument(
        "--optimize",
        choices=["cost", "duration", "stops"],
        default="cost",
        dest="optimize_by",
        help="Optimisation criterion (default: cost).",
    )
    search.add_argument(
        "--max-stops",
        type=int,
        default=2,
        metavar="N",
        help="Maximum number of stops (default: 2).",
    )
    search.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="Number of results to display (default: 5).",
    )

    # ---- airports ----
    sub.add_parser("airports", help="List all available airports.")

    # ---- flights ----
    flights = sub.add_parser(
        "flights", help="List direct flights from an airport."
    )
    flights.add_argument("origin", metavar="ORIGIN", help="Departure IATA code.")

    return parser


def _print_route(idx: int, route) -> None:
    """Pretty-print a single route."""
    hours, minutes = divmod(route.total_duration_minutes, 60)
    stops_label = "non-stop" if route.stops == 0 else f"{route.stops} stop(s)"
    print(f"\n  #{idx + 1}  {stops_label}  |  {hours}h {minutes:02d}m  |  ${route.total_cost_usd:.2f}")
    for i, flight in enumerate(route.flights, start=1):
        prefix = "       " if i == 1 else "    ↳  "
        print(f"  {prefix}{flight}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    advisor = FlightRouteAdvisor()

    if args.command == "airports":
        airports = advisor.list_airports()
        print(f"{'Code':<6}  {'City':<22}  {'Country':<8}  Name")
        print("-" * 72)
        for ap in airports:
            print(f"{ap.code:<6}  {ap.city:<22}  {ap.country:<8}  {ap.name}")
        return 0

    if args.command == "flights":
        flights = advisor.direct_flights(args.origin.upper())
        if not flights:
            print(f"No direct flights found from {args.origin.upper()}.")
            return 0
        print(f"Direct flights from {args.origin.upper()}:")
        for f in flights:
            print(f"  {f}")
        return 0

    # search
    origin: str = args.origin.upper()
    destination: str = args.destination.upper()
    optimize_by: OptimizeBy = args.optimize_by

    print(
        f"\nSearching routes: {origin} → {destination}"
        f"  (optimize by {optimize_by}, max {args.max_stops} stop(s))"
    )

    try:
        routes = advisor.recommend(
            origin,
            destination,
            optimize_by=optimize_by,
            max_stops=args.max_stops,
            top_n=args.top,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not routes:
        print(f"No routes found from {origin} to {destination}.")
        return 0

    print(f"\nTop {len(routes)} route(s) found:\n")
    for idx, route in enumerate(routes):
        _print_route(idx, route)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

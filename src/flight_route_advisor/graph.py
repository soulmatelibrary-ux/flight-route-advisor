"""Graph representation and pathfinding for flight routes."""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from typing import Literal

from .models import Airport, Flight, Route

OptimizeBy = Literal["cost", "duration", "stops"]


class RouteGraph:
    """Directed weighted graph of airports connected by flights.

    Supports finding optimal routes using Dijkstra's algorithm with
    selectable optimisation criteria (cost, duration, or fewest stops).
    """

    def __init__(self) -> None:
        self._airports: dict[str, Airport] = {}
        self._adjacency: dict[str, list[Flight]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_airport(self, airport: Airport) -> None:
        """Register an airport in the graph."""
        self._airports[airport.code.upper()] = airport

    def add_flight(self, flight: Flight) -> None:
        """Add a directed edge representing a flight."""
        if flight.origin not in self._airports:
            raise ValueError(f"Unknown origin airport: {flight.origin}")
        if flight.destination not in self._airports:
            raise ValueError(f"Unknown destination airport: {flight.destination}")
        self._adjacency[flight.origin].append(flight)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def airports(self) -> list[Airport]:
        """Return all registered airports sorted by code."""
        return sorted(self._airports.values(), key=lambda a: a.code)

    def flights_from(self, code: str) -> list[Flight]:
        """Return all direct flights departing from *code*."""
        return list(self._adjacency.get(code.upper(), []))

    def find_routes(
        self,
        origin: str,
        destination: str,
        optimize_by: OptimizeBy = "cost",
        max_stops: int = 2,
    ) -> list[Route]:
        """Find all optimal routes from *origin* to *destination*.

        Uses a modified Dijkstra's algorithm that tracks the full path
        so that the complete sequence of flights is returned.

        Args:
            origin: IATA code of the departure airport.
            destination: IATA code of the arrival airport.
            optimize_by: Primary optimisation criterion –
                ``"cost"`` minimises total ticket price,
                ``"duration"`` minimises total flight time,
                ``"stops"`` minimises number of intermediate stops
                (and uses cost as a secondary sort key).
            max_stops: Maximum number of intermediate stops allowed.

        Returns:
            A list of :class:`Route` objects sorted by the chosen
            criterion (best first).  Returns an empty list when no route
            exists.
        """
        origin = origin.upper()
        destination = destination.upper()

        if origin not in self._airports:
            raise ValueError(f"Unknown origin airport: {origin}")
        if destination not in self._airports:
            raise ValueError(f"Unknown destination airport: {destination}")

        # Unique counter used to break ties in the heap without comparing
        # Flight objects (which do not support ordering).
        _counter = itertools.count()

        # Priority queue entries:
        #   (accumulated_weight_tuple, tiebreak_int, current_airport, flights_so_far)
        if optimize_by == "stops":
            zero: tuple = (0, 0.0)
        else:
            zero = (0.0,)

        heap: list[tuple] = [(zero, next(_counter), origin, [])]
        # best[airport] = best accumulated weight seen so far
        best: dict[str, tuple] = {}

        found_routes: list[Route] = []

        while heap:
            acc_w, _, current, path = heapq.heappop(heap)

            if current == destination:
                found_routes.append(Route(flights=list(path)))
                continue

            stops_so_far = len(path)
            if stops_so_far > max_stops:
                continue

            # Skip if we've already reached this node with a better weight
            if current in best and best[current] <= acc_w:
                continue
            best[current] = acc_w

            for flight in self._adjacency.get(current, []):
                next_code = flight.destination
                # Avoid cycles
                visited = {f.origin for f in path} | {current}
                if next_code in visited:
                    continue

                if optimize_by == "stops":
                    new_w = (acc_w[0] + (1 if path else 0), acc_w[1] + flight.cost_usd)
                elif optimize_by == "cost":
                    new_w = (acc_w[0] + flight.cost_usd,)
                else:
                    new_w = (acc_w[0] + flight.duration_minutes,)

                heapq.heappush(heap, (new_w, next(_counter), next_code, path + [flight]))

        # Sort results by chosen criterion
        if optimize_by == "cost":
            found_routes.sort(key=lambda r: r.total_cost_usd)
        elif optimize_by == "duration":
            found_routes.sort(key=lambda r: r.total_duration_minutes)
        else:
            found_routes.sort(key=lambda r: (r.stops, r.total_cost_usd))

        return found_routes
